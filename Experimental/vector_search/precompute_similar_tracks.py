"""GPU chamfer precompute: top-N similar tracks for every track in a chunk store.

Two-stage, mirroring the serving design: exact pooled-cosine recall picks K
candidates per track (no ANN index -- at catalogue scale the full pooled matrix
fits in VRAM, so recall is brute-force and exact), then symmetric Chamfer over
chunk embeddings reranks them. The whole chunk store is resident in VRAM as one
fp16 tensor; per-track chunk lists are gathered through a precomputed padded
index, so scoring is batched einsum with masks rather than ragged loops.

Padding note: tracks longer than --pad chunks are uniformly subsampled at
gather time (the store keeps every chunk). That bounds the score workspace and
the document-length bias at once.

Modes:
  bench   validate the GPU kernel against the numpy reference in rerank.py
          (same candidates, tracks that fit the pad -- must agree), check
          chamfer symmetry, then measure throughput and report a full-run ETA
  run     the full precompute; CSV shards of (anchor, neighbor, rank, score),
          resumable per shard
"""

import argparse
import csv
import importlib.util
import json
import os
import sys
import time
import types

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chunk_store as cs_mod  # noqa: E402
from chunk_store import ChunkStore  # noqa: E402


def load_rerank_module():
    """Loads rerank.py despite its package-qualified chunk_store import."""
    pkg = types.ModuleType("Experimental")
    pkg.__path__ = []
    sub = types.ModuleType("Experimental.vector_search")
    sub.__path__ = []
    sys.modules.setdefault("Experimental", pkg)
    sys.modules.setdefault("Experimental.vector_search", sub)
    sys.modules["Experimental.vector_search.chunk_store"] = cs_mod
    spec = importlib.util.spec_from_file_location(
        "rerank", os.path.join(HERE, "rerank.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GpuStore:
    """The chunk store resident on the GPU, with padded gather."""

    def __init__(self, root: str, device: str = "cuda", pad: int = 96):
        st = ChunkStore(root)
        self.cpu = st
        self.n = len(st)
        self.dim = st.dim
        self.pad = pad
        self.device = device
        self.ids = [str(t) for t in st.track_ids]

        total = st.total_chunks
        print(f"store: {self.n} tracks, {total} chunks; uploading "
              f"{total * st.dim * 2 / 1e9:.1f} GB fp16 to {device}", flush=True)
        t0 = time.time()
        self.vecs = torch.empty((total, st.dim), dtype=torch.float16, device=device)
        step = 1_000_000
        for i in range(0, total, step):
            j = min(total, i + step)
            block = np.ascontiguousarray(st._vectors[i:j])
            self.vecs[i:j] = torch.from_numpy(block).to(device)
        print(f"  upload {time.time() - t0:.1f}s", flush=True)

        offs = st.offsets.astype(np.int64)
        cnts = st.counts.astype(np.int64)
        idx = np.zeros((self.n, pad), dtype=np.int64)
        msk = np.zeros((self.n, pad), dtype=bool)
        for r in range(self.n):
            c = int(cnts[r])
            o = int(offs[r])
            if c <= pad:
                idx[r, :c] = o + np.arange(c)
                msk[r, :c] = True
            else:
                idx[r] = o + np.linspace(0, c - 1, pad).round().astype(np.int64)
                msk[r] = True
        self.idx = torch.from_numpy(idx).to(device)
        self.mask = torch.from_numpy(msk).to(device)
        self.eff = self.mask.sum(1)
        self.counts_full = torch.from_numpy(cnts).to(device)

    def gather(self, rows: torch.Tensor):
        """rows [M] -> vectors [M, pad, dim] fp16, mask [M, pad] bool."""
        ii = self.idx[rows]
        v = self.vecs[ii.reshape(-1)].view(rows.shape[0], self.pad, self.dim)
        return v, self.mask[rows]


def build_pooled(gs: GpuStore, block: int = 4096) -> torch.Tensor:
    """Masked mean of each track's (subsampled) chunks, re-normalized, fp16."""
    out = torch.empty((gs.n, gs.dim), dtype=torch.float16, device=gs.device)
    for i in range(0, gs.n, block):
        rows = torch.arange(i, min(gs.n, i + block), device=gs.device)
        v, m = gs.gather(rows)
        s = (v.float() * m[..., None]).sum(1) / m.sum(1, keepdim=True).clamp(min=1)
        out[rows] = torch.nn.functional.normalize(s, dim=-1).half()
    return out


def topk_candidates(pooled: torch.Tensor, k: int, tile: int = 4096) -> torch.Tensor:
    """Exact pooled-cosine top-k per track, self excluded. Returns CPU int32 [n, k]."""
    n = pooled.shape[0]
    cand = torch.empty((n, k), dtype=torch.int32)
    for i in range(0, n, tile):
        j = min(n, i + tile)
        sims = pooled[i:j] @ pooled.T  # fp16, fp32 accumulate in cuBLAS
        rows = torch.arange(j - i, device=pooled.device)
        sims[rows, rows + i] = float("-inf")
        cand[i:j] = sims.topk(k, dim=1).indices.to(torch.int32).cpu()
    return cand


def chamfer_batch(gs: GpuStore, a_rows: torch.Tensor, cand_rows: torch.Tensor) -> torch.Tensor:
    """Symmetric chamfer of each anchor against its K candidates. [B, K] fp32.

    Mask order matters: candidate pads are silenced before the per-query max,
    query pads before the per-candidate max. Pad slots gather row 0's real
    vector, so an unmasked pad would inject an arbitrary chunk into the max.
    """
    B, K = cand_rows.shape
    Q, qm = gs.gather(a_rows)                       # [B, C, D], [B, C]
    Dv, dm = gs.gather(cand_rows.reshape(-1))       # [B*K, C, D]
    C = gs.pad
    Dv = Dv.view(B, K, C, gs.dim)
    dm = dm.view(B, K, C)

    sims = torch.einsum("bqd,bkcd->bkqc", Q, Dv).float()  # [B, K, Cq, Cc]

    sims.masked_fill_(~dm[:, :, None, :], float("-inf"))
    q_max = sims.max(dim=3).values                        # [B, K, Cq]
    q_side = q_max.masked_fill(~qm[:, None, :], 0).sum(2) \
        / gs.eff[a_rows][:, None].float()

    sims.masked_fill_(~qm[:, None, :, None], float("-inf"))
    d_max = sims.max(dim=2).values                        # [B, K, Cc]
    d_side = d_max.masked_fill(~dm, 0).sum(2) \
        / gs.eff[cand_rows].float()

    return 0.5 * (q_side + d_side)


def validate(gs: GpuStore, cand: torch.Tensor, n_anchors: int, k_val: int) -> bool:
    """GPU kernel vs the numpy reference, on tracks the pad does not subsample."""
    rr = load_rerank_module()
    rng = np.random.default_rng(42)
    fits = (gs.counts_full <= gs.pad).cpu().numpy()
    ok_rows = np.flatnonzero(fits)
    anchors = rng.choice(ok_rows, n_anchors, replace=False)

    worst = 0.0
    top10_hits = 0
    for r in anchors:
        cand_r = [c for c in cand[r].tolist() if fits[c]][:k_val]
        rows_t = torch.tensor([r], device=gs.device)
        cands_t = torch.tensor([cand_r], device=gs.device)
        gpu = chamfer_batch(gs, rows_t, cands_t)[0].cpu().numpy()

        query = np.asarray(gs.cpu.get(gs.ids[r]), dtype=np.float32)
        matrix, starts, counts, resolved = gs.cpu.gather([gs.ids[c] for c in cand_r])
        ref = rr.chamfer_scores(query, matrix, starts, counts)

        worst = max(worst, float(np.abs(gpu - ref).max()))
        top10_hits += len(set(np.argsort(-gpu)[:10]) & set(np.argsort(-ref)[:10]))

    sym_rows = rng.choice(ok_rows, 200, replace=False)
    a = torch.tensor(sym_rows[:100], device=gs.device)
    b = torch.tensor(sym_rows[100:], device=gs.device)
    ab = chamfer_batch(gs, a, b[:, None])[:, 0]
    ba = chamfer_batch(gs, b, a[:, None])[:, 0]
    sym_err = float((ab - ba).abs().max())

    print(f"validate: |gpu-ref| max {worst:.2e} over {n_anchors} anchors x "
          f"{k_val} candidates; top-10 overlap {top10_hits}/{n_anchors * 10}; "
          f"symmetry err {sym_err:.2e}", flush=True)
    passed = worst < 5e-3 and sym_err < 5e-3 and top10_hits >= n_anchors * 9
    print("validate:", "PASS" if passed else "FAIL", flush=True)
    return passed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--mode", choices=["bench", "run"], required=True)
    ap.add_argument("--k", type=int, default=500, help="recall candidates per track")
    ap.add_argument("--top", type=int, default=100, help="neighbors kept per track")
    ap.add_argument("--pad", type=int, default=96)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--out", default=None, help="output dir (run mode)")
    ap.add_argument("--bench-anchors", type=int, default=2048)
    args = ap.parse_args()

    torch.backends.cuda.matmul.allow_tf32 = True
    gs = GpuStore(args.store, pad=args.pad)

    t0 = time.time()
    pooled = build_pooled(gs)
    print(f"pooled: {tuple(pooled.shape)} in {time.time() - t0:.1f}s", flush=True)

    t0 = time.time()
    cand = topk_candidates(pooled, args.k)
    print(f"recall: exact top-{args.k} for {gs.n} tracks in "
          f"{time.time() - t0:.1f}s", flush=True)
    del pooled
    torch.cuda.empty_cache()

    if args.mode == "bench":
        if not validate(gs, cand, n_anchors=25, k_val=100):
            sys.exit(1)

        rows = torch.arange(min(args.bench_anchors, gs.n), device=gs.device)
        torch.cuda.synchronize()
        t0 = time.time()
        for i in range(0, rows.shape[0], args.batch):
            a = rows[i:i + args.batch]
            c = cand[a.cpu().long()].to(gs.device).long()
            chamfer_batch(gs, a, c)
        torch.cuda.synchronize()
        dt = time.time() - t0
        rate = rows.shape[0] / dt
        flops = rows.shape[0] * args.k * args.pad * args.pad * gs.dim * 2
        print(f"bench: {rate:.1f} anchors/s at K={args.k} pad={args.pad} "
              f"batch={args.batch} ({flops / dt / 1e12:.0f} TFLOPS padded); "
              f"full {gs.n} tracks ~= {gs.n / rate / 3600:.2f} h", flush=True)
        peak = torch.cuda.max_memory_allocated() / 1e9
        print(f"bench: peak VRAM {peak:.1f} GB", flush=True)
        return

    out = args.out or os.path.join(args.store, "similar_tracks")
    os.makedirs(out, exist_ok=True)
    shard_size = 10_000
    t_run = time.time()
    for s0 in range(0, gs.n, shard_size):
        s1 = min(gs.n, s0 + shard_size)
        shard_path = os.path.join(out, f"similar_{s0:07d}_{s1:07d}.csv")
        if os.path.exists(shard_path):
            print(f"shard {shard_path} exists, skipping", flush=True)
            continue
        tmp = shard_path + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            wcsv = csv.writer(f)
            wcsv.writerow(["anchor_id", "neighbor_id", "rank", "score"])
            for i in range(s0, s1, args.batch):
                a = torch.arange(i, min(s1, i + args.batch), device=gs.device)
                c = cand[a.cpu().long()].to(gs.device).long()
                scores = chamfer_batch(gs, a, c)
                top = scores.topk(min(args.top, args.k), dim=1)
                idx = torch.gather(c, 1, top.indices).cpu().numpy()
                val = top.values.cpu().numpy()
                for bi, row in enumerate(a.tolist()):
                    aid = gs.ids[row]
                    for rank in range(idx.shape[1]):
                        wcsv.writerow([aid, gs.ids[idx[bi, rank]], rank + 1,
                                       f"{val[bi, rank]:.6f}"])
        os.replace(tmp, shard_path)
        done = s1
        rate = done / (time.time() - t_run)
        eta_h = (gs.n - done) / rate / 3600
        print(f"shard {s0}-{s1} done ({rate:.1f} anchors/s overall, "
              f"~{eta_h:.2f} h remaining)", flush=True)

    with open(os.path.join(out, "run_manifest.json"), "w", encoding="utf-8") as f:
        json.dump({
            "store": args.store, "tracks": gs.n, "k_recall": args.k,
            "top_kept": args.top, "pad": args.pad,
            "scoring": "chamfer, symmetric, masked mean-of-max both sides",
            "recall": "exact pooled cosine (masked mean of chunks, renormalized)",
            "wall_seconds": round(time.time() - t_run, 1),
        }, f, indent=2)
    print("run complete", flush=True)


if __name__ == "__main__":
    main()
