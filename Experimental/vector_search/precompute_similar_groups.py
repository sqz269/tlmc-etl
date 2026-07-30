"""GPU chamfer precompute at album and circle level.

An album is to its tracks what a track is to its 6s chunks, so this reuses the
two-stage design of the track precompute one level up: exact pooled-cosine
recall over group centroids, then symmetric Chamfer between groups' member
vector sets. Members are track pooled vectors for albums, and album centroids
for circles -- the latter keeps thousand-track circles at a set size that
subsampling does not have to butcher.

Every neighbor gets two scores:

  score_raw    plain symmetric chamfer. Near-duplicate recordings (pooled
               cosine >= --dup-thresh, the ~0.999 band the v5 run measured)
               dominate this: an album and its re-release or a compilation
               containing it score near 1.0. Useful as a "shares recordings"
               signal.
  score_style  the same chamfer with duplicate member pairs removed from the
               max entirely, so a shared recording must find its best
               *different* counterpart. A pure re-release collapses toward 0
               here rather than topping the list.

similar_<level>s.csv ranks by score_style. A pure re-release scores ~0 there
and would drop out of a style-ranked top list entirely, taking its raw signal
with it, so the raw flavor gets its own file: similar_<level>s_raw.csv keeps
the top --top-raw neighbors ranked by score_raw.

Group ids: albums use the AlbumID column of the targets CSV when it is
populated (the generated all_targets.csv leaves it empty), otherwise the
"<circle dir>/<album dir>" pair from the playlist path; circles always use the
circle directory name. The CSV predates any on-disk renames, so path-derived
names are canonical, and multi-disc layouts do not matter because only the two
components directly under "TLMC v6" are read.
"""

import argparse
import csv
import json
import os
import re
import sys
import time

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from chunk_store import ChunkStore  # noqa: E402

UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def pool_tracks(store: ChunkStore, device: str) -> torch.Tensor:
    """Every track's chunks mean-pooled and renormalized, [n_tracks, dim] fp16.

    Streams the mmapped store in slices and segment-sums on the GPU, so peak
    VRAM is one slice plus the output rather than the whole 21 GB store --
    chamfer here never needs chunk vectors, only these pooled ones.

    Unlike the track-level precompute this pools over *all* chunks, not the
    pad-subsampled first 96; at pooling granularity the difference is noise,
    and it saves materializing the padded gather index.
    """
    n = len(store)
    counts = store.counts.astype(np.int64)
    seg = np.repeat(np.arange(n, dtype=np.int64), counts)

    pool = torch.zeros((n, store.dim), dtype=torch.float32, device=device)
    step = 1_000_000
    total = store.total_chunks
    for i in range(0, total, step):
        j = min(total, i + step)
        block = torch.from_numpy(np.ascontiguousarray(store._vectors[i:j]))
        pool.index_add_(0, torch.from_numpy(seg[i:j]).to(device),
                        block.to(device).float())
    pool /= torch.from_numpy(counts).to(device)[:, None].float()
    return torch.nn.functional.normalize(pool, dim=-1).half()


def read_mappings(targets_csv: str):
    """(track_id -> album_id, album_id -> circle_name), CSV order preserved."""
    track_album = {}
    album_circle = {}
    with open(targets_csv, encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 3 or not UUID_RE.fullmatch(row[1] or ""):
                continue
            # /mnt/tlmc/TLMC v6/<circle dir>/<album dir>/...
            parts = row[2].split("/")
            if len(parts) < 6:
                continue
            circle = parts[4]
            album = row[0] or f"{circle}/{parts[5]}"
            track_album[row[1]] = album
            album_circle.setdefault(album, circle)
    return track_album, album_circle


def build_groups(member_of: dict, item_ids, pad: int, device: str):
    """Padded member index per group over an item-vector matrix.

    member_of maps item_id -> group_id for items that exist in `item_ids`
    (row order of the vector matrix). Groups larger than the pad are uniformly
    subsampled, same policy as the chunk-level gather.
    Returns (group_ids, idx [G, pad] int64, mask [G, pad] bool).
    """
    rows_of = {}
    for row, item in enumerate(item_ids):
        g = member_of.get(item)
        if g is not None:
            rows_of.setdefault(g, []).append(row)

    gids = sorted(rows_of)
    idx = np.zeros((len(gids), pad), dtype=np.int64)
    msk = np.zeros((len(gids), pad), dtype=bool)
    for gi, g in enumerate(gids):
        rows = rows_of[g]
        if len(rows) > pad:
            pick = np.linspace(0, len(rows) - 1, pad).round().astype(int)
            rows = [rows[p] for p in pick]
        idx[gi, :len(rows)] = rows
        msk[gi, :len(rows)] = True
    return gids, torch.from_numpy(idx).to(device), torch.from_numpy(msk).to(device)


def centroids(vecs: torch.Tensor, idx: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Masked mean of each group's member vectors, renormalized, fp16."""
    v = vecs[idx.reshape(-1)].view(*idx.shape, vecs.shape[1]).float()
    s = (v * mask[..., None]).sum(1) / mask.sum(1, keepdim=True).clamp(min=1)
    return torch.nn.functional.normalize(s, dim=-1).half()


def chamfer_groups(vecs, idx, mask, eff, a_rows, cand_rows, dup_thresh):
    """Symmetric chamfer of anchors against candidates, raw and style flavors.

    Returns (raw [B, K] fp32, style [B, K] fp32). Style masks member pairs at
    or above dup_thresh out of both maxes; a member whose every counterpart is
    a duplicate contributes 0 (nan_to_num on the -inf max), which is what
    demotes pure re-releases. Mask order follows the track kernel: candidate
    pads before the per-query max, query pads before the per-candidate max.
    """
    B, K = cand_rows.shape
    C, dim = idx.shape[1], vecs.shape[1]
    Q = vecs[idx[a_rows].reshape(-1)].view(B, C, dim)
    qm = mask[a_rows]
    Dv = vecs[idx[cand_rows.reshape(-1)].reshape(-1)].view(B, K, C, dim)
    dm = mask[cand_rows]

    sims = torch.einsum("bqd,bkcd->bkqc", Q, Dv).float()
    sims.masked_fill_(~dm[:, :, None, :], float("-inf"))
    style = sims.clone()
    style.masked_fill_(style >= dup_thresh, float("-inf"))

    def both_sides(s):
        q_max = s.max(dim=3).values.nan_to_num(neginf=0.0)
        q_side = q_max.masked_fill(~qm[:, None, :], 0).sum(2) \
            / eff[a_rows][:, None].float()
        s = s.masked_fill(~qm[:, None, :, None], float("-inf"))
        d_max = s.max(dim=2).values.nan_to_num(neginf=0.0)
        d_side = d_max.masked_fill(~dm, 0).sum(2) / eff[cand_rows].float()
        return 0.5 * (q_side + d_side)

    return both_sides(sims), both_sides(style)


def check_symmetry(vecs, idx, mask, eff, n_groups, dup_thresh, pairs=128):
    """Both chamfer flavors must be symmetric; self-similarity must be ~1."""
    rng = np.random.default_rng(7)
    a = torch.from_numpy(rng.choice(n_groups, pairs)).cuda()
    b = torch.from_numpy(rng.choice(n_groups, pairs)).cuda()
    r_ab, s_ab = chamfer_groups(vecs, idx, mask, eff, a, b[:, None], dup_thresh)
    r_ba, s_ba = chamfer_groups(vecs, idx, mask, eff, b, a[:, None], dup_thresh)
    sym = max(float((r_ab - r_ba).abs().max()), float((s_ab - s_ba).abs().max()))
    self_raw, _ = chamfer_groups(vecs, idx, mask, eff, a, a[:, None], dup_thresh)
    self_err = float((self_raw - 1.0).abs().max())
    print(f"check: symmetry err {sym:.2e}, self-score err {self_err:.2e}",
          flush=True)
    if sym > 5e-3 or self_err > 5e-3:
        sys.exit("chamfer self-check failed")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--targets-csv", required=True,
                    help="AlbumID,TrackID,PlaylistPath rows for the corpus")
    ap.add_argument("--level", choices=["album", "circle"], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--k", type=int, default=500, help="recall candidates")
    ap.add_argument("--top", type=int, default=100, help="neighbors kept")
    ap.add_argument("--top-raw", type=int, default=20,
                    help="neighbors kept in the raw-ranked file")
    ap.add_argument("--pad", type=int, default=64, help="max members per set")
    ap.add_argument("--batch", type=int, default=24)
    ap.add_argument("--dup-thresh", type=float, default=0.9985,
                    help="pooled cosine at which two members count as the "
                         "same recording (v5 measured the dup band at ~0.999)")
    args = ap.parse_args()

    device = "cuda"
    torch.backends.cuda.matmul.allow_tf32 = True
    store = ChunkStore(args.store)
    t0 = time.time()
    pooled = pool_tracks(store, device)
    print(f"pooled {len(store)} tracks in {time.time() - t0:.1f}s", flush=True)

    track_album, album_circle = read_mappings(args.targets_csv)
    track_ids = [str(t) for t in store.track_ids]

    alb_ids, alb_idx, alb_mask = build_groups(
        track_album, track_ids, args.pad, device)
    if args.level == "album":
        gids, idx, mask = alb_ids, alb_idx, alb_mask
        vecs = pooled
    else:
        alb_cent = centroids(pooled, alb_idx, alb_mask)
        gids, idx, mask = build_groups(album_circle, alb_ids, args.pad, device)
        vecs = alb_cent
    eff = mask.sum(1)
    n = len(gids)
    print(f"{args.level}s: {n} groups over {vecs.shape[0]} member vectors",
          flush=True)

    cent = centroids(vecs, idx, mask)
    k = min(args.k, n - 1)
    sims = cent.float() @ cent.float().T
    sims.fill_diagonal_(float("-inf"))
    cand = sims.topk(k, dim=1).indices
    del sims

    check_symmetry(vecs, idx, mask, eff, n, args.dup_thresh)

    os.makedirs(args.out, exist_ok=True)
    out_csv = os.path.join(args.out, f"similar_{args.level}s.csv")
    raw_csv = os.path.join(args.out, f"similar_{args.level}s_raw.csv")
    t_run = time.time()
    with open(out_csv + ".tmp", "w", newline="", encoding="utf-8") as f, \
         open(raw_csv + ".tmp", "w", newline="", encoding="utf-8") as fr:
        w = csv.writer(f)
        w.writerow(["anchor_id", "neighbor_id", "rank",
                    "score_style", "score_raw"])
        wr = csv.writer(fr)
        wr.writerow(["anchor_id", "neighbor_id", "rank",
                     "score_raw", "score_style"])
        for i in range(0, n, args.batch):
            a = torch.arange(i, min(n, i + args.batch), device=device)
            c = cand[a.long()]
            raw, style = chamfer_groups(
                vecs, idx, mask, eff, a, c, args.dup_thresh)

            top = style.topk(min(args.top, k), dim=1)
            nbr = torch.gather(c, 1, top.indices).cpu().numpy()
            sty = top.values.cpu().numpy()
            rw = torch.gather(raw, 1, top.indices).cpu().numpy()

            top_r = raw.topk(min(args.top_raw, k), dim=1)
            nbr_r = torch.gather(c, 1, top_r.indices).cpu().numpy()
            rw_r = top_r.values.cpu().numpy()
            sty_r = torch.gather(style, 1, top_r.indices).cpu().numpy()

            for bi, row in enumerate(a.tolist()):
                for r in range(nbr.shape[1]):
                    w.writerow([gids[row], gids[nbr[bi, r]], r + 1,
                                f"{sty[bi, r]:.6f}", f"{rw[bi, r]:.6f}"])
                for r in range(nbr_r.shape[1]):
                    wr.writerow([gids[row], gids[nbr_r[bi, r]], r + 1,
                                 f"{rw_r[bi, r]:.6f}", f"{sty_r[bi, r]:.6f}"])
    os.replace(out_csv + ".tmp", out_csv)
    os.replace(raw_csv + ".tmp", raw_csv)

    np.savez(os.path.join(args.out, f"{args.level}_centroids.npz"),
             ids=np.array(gids, dtype=object),
             centroids=cent.cpu().numpy())
    with open(os.path.join(args.out, f"{args.level}_manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump({
            "level": args.level, "groups": n, "store": args.store,
            "k_recall": k, "top_kept": min(args.top, k),
            "top_raw_kept": min(args.top_raw, k), "pad": args.pad,
            "dup_thresh": args.dup_thresh,
            "members": "track pooled vectors" if args.level == "album"
                       else "album centroids",
            "scoring": "symmetric chamfer; style flavor drops member pairs "
                       ">= dup_thresh from both maxes",
            "wall_seconds": round(time.time() - t_run, 1),
        }, f, indent=2)
    print(f"run complete: {n} {args.level}s in {time.time() - t_run:.1f}s",
          flush=True)


if __name__ == "__main__":
    main()
