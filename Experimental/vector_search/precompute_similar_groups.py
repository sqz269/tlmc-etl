"""GPU chamfer precompute at album and circle level.

An album is to its tracks what a track is to its 6s chunks, so this reuses the
two-stage design of the track precompute one level up: exact pooled-cosine
recall over group centroids, then symmetric Chamfer between groups' member
vector sets. Members are track pooled vectors for albums, and album centroids
for circles -- the latter keeps thousand-track circles at a set size that
subsampling does not have to butcher.

Every neighbor gets three scores:

  score_raw    plain symmetric chamfer. Near-duplicate recordings (pooled
               cosine >= --dup-thresh, the ~0.999 band the v5 run measured)
               dominate this: an album and its re-release or a compilation
               containing it score near 1.0. Useful as a "shares recordings"
               signal.
  score_style  the same chamfer with duplicate member pairs removed from the
               max entirely, so a shared recording must find its best
               *different* counterpart. A pure re-release collapses toward 0
               here rather than topping the list.
  score_kde    what KDE similarity becomes once it must live in 1024
               dimensions: the cosine of RBF kernel mean embeddings, which is
               the closed form of two Gaussian KDEs' overlap integral -- the
               mean kernel over all cross member pairs, self-normalized so
               identical groups score exactly 1. Unlike chamfer it weighs
               where the mass sits (a 90/10 metal/piano circle no longer
               matches its 10/90 mirror), and duplicates dilute into an n*m
               average instead of winning a max. Bandwidth comes from the
               median heuristic over recall-candidate member pairs; Scott's
               rule from the 2-D UMAP demo has no meaning up here.

Each flavor gets its own ranked file (similar_<level>s.csv by style,
similar_<level>s_raw.csv by raw, similar_<level>s_kde.csv by kde), all with
identical anchor_id, neighbor_id, rank, score_style, score_raw, score_kde
columns, so the rankings can be compared row for row.

Group ids: the preferred source is database exports -- --track-release-csv
(track_id,release_id) and --release-circle-csv (release_id,circle_id), plain
two-column CSVs from the live catalogue -- which yields real entity uuids and
models collab releases correctly: a release linked to two circles contributes
its centroid to both. Without them, --targets-csv falls back to path parsing:
albums become "<circle dir>/<album dir>" pairs and circles the circle
directory name, which mis-models joint circle directories as circles of their
own and needs path normalization at load time.
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
    """Path-parsed fallback: ((track, album) pairs, (album, circle) pairs)."""
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
    return list(track_album.items()), list(album_circle.items())


def read_pairs(path: str):
    """Two-column (item_id, group_id) CSV, as exported by psql COPY."""
    with open(path, encoding="utf-8") as f:
        return [(r[0], r[1]) for r in csv.reader(f) if len(r) >= 2 and r[0]]


def build_groups(pairs, item_ids, pad: int, device: str):
    """Padded member index per group over an item-vector matrix.

    pairs is an iterable of (item_id, group_id); items may belong to several
    groups (collab releases). Items absent from `item_ids` (the row order of
    the vector matrix) are skipped. Groups larger than the pad are uniformly
    subsampled, same policy as the chunk-level gather.
    Returns (group_ids, idx [G, pad] int64, mask [G, pad] bool).
    """
    row_of = {item: r for r, item in enumerate(item_ids)}
    rows_of = {}
    for item, g in pairs:
        row = row_of.get(item)
        if row is not None:
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


def calibrate_gamma(vecs, idx, mask, cand, sample=256, per=4):
    """Median-heuristic RBF bandwidth, as 1/median cosine distance.

    Measured over member pairs of anchors vs their own recall candidates --
    the pairs the kernel actually has to discriminate -- rather than global
    random pairs, which sit further apart and would over-smooth. The kernel
    evaluates to e^-1 at the median.
    """
    rng = np.random.default_rng(3)
    n = idx.shape[0]
    a = torch.from_numpy(
        rng.choice(n, min(sample, n), replace=False)).to(vecs.device)
    pick = torch.from_numpy(
        rng.integers(0, cand.shape[1], (a.shape[0], per))).to(vecs.device)
    c = torch.gather(cand[a.long()], 1, pick)
    B, K = c.shape
    C, dim = idx.shape[1], vecs.shape[1]
    Q = vecs[idx[a].reshape(-1)].view(B, C, dim)
    Dv = vecs[idx[c.reshape(-1)].reshape(-1)].view(B, K, C, dim)
    sims = torch.einsum("bqd,bkcd->bkqc", Q, Dv).float()
    valid = mask[a][:, None, :, None] & mask[c][:, :, None, :]
    med = float((1.0 - sims[valid]).median())
    return 1.0 / max(med, 1e-4), med


def self_kernel_mass(vecs, idx, mask, eff, gamma, block=2048):
    """Each group's mean self-kernel <mu, mu>, diagonal included. [G] fp32."""
    G = idx.shape[0]
    out = torch.empty(G, dtype=torch.float32, device=vecs.device)
    for i in range(0, G, block):
        rows = torch.arange(i, min(G, i + block), device=vecs.device)
        V = vecs[idx[rows].reshape(-1)].view(rows.shape[0], idx.shape[1], -1)
        s = torch.einsum("bcd,bed->bce", V, V).float()
        k = torch.exp(gamma * (s - 1.0))
        valid = (mask[rows][:, :, None] & mask[rows][:, None, :]).float()
        out[rows] = (k * valid).sum((1, 2)) / eff[rows].float().pow(2)
    return out


def chamfer_groups(vecs, idx, mask, eff, kaa, a_rows, cand_rows,
                   dup_thresh, gamma):
    """Chamfer (raw, style) and KDE similarity of anchors vs candidates.

    Returns (raw, style, kde), each [B, K] fp32. Style masks member pairs at
    or above dup_thresh out of both maxes; a member whose every counterpart is
    a duplicate contributes 0 (nan_to_num on the -inf max), which is what
    demotes pure re-releases. Mask order follows the track kernel: candidate
    pads before the per-query max, query pads before the per-candidate max.

    kde reuses the candidate-pad -inf fill: exp maps those slots to a clean 0
    contribution, query pads are zeroed by the qm factor, and the cross mean
    is normalized by both groups' self-kernel mass so self-similarity is 1.
    """
    B, K = cand_rows.shape
    C, dim = idx.shape[1], vecs.shape[1]
    Q = vecs[idx[a_rows].reshape(-1)].view(B, C, dim)
    qm = mask[a_rows]
    Dv = vecs[idx[cand_rows.reshape(-1)].reshape(-1)].view(B, K, C, dim)
    dm = mask[cand_rows]

    sims = torch.einsum("bqd,bkcd->bkqc", Q, Dv).float()
    sims.masked_fill_(~dm[:, :, None, :], float("-inf"))

    kern = torch.exp(gamma * (sims - 1.0)) * qm[:, None, :, None]
    cross = kern.sum((2, 3)) / (eff[a_rows][:, None] * eff[cand_rows]).float()
    kde = cross / (kaa[a_rows][:, None] * kaa[cand_rows]).sqrt()

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

    return both_sides(sims), both_sides(style), kde


def check_symmetry(vecs, idx, mask, eff, kaa, n_groups, dup_thresh, gamma,
                   pairs=128):
    """All three flavors must be symmetric; raw and kde self-scores ~1."""
    rng = np.random.default_rng(7)
    a = torch.from_numpy(rng.choice(n_groups, pairs)).cuda()
    b = torch.from_numpy(rng.choice(n_groups, pairs)).cuda()
    ab = chamfer_groups(vecs, idx, mask, eff, kaa, a, b[:, None],
                        dup_thresh, gamma)
    ba = chamfer_groups(vecs, idx, mask, eff, kaa, b, a[:, None],
                        dup_thresh, gamma)
    sym = max(float((x - y).abs().max()) for x, y in zip(ab, ba))
    self_raw, _, self_kde = chamfer_groups(vecs, idx, mask, eff, kaa,
                                           a, a[:, None], dup_thresh, gamma)
    self_err = max(float((self_raw - 1.0).abs().max()),
                   float((self_kde - 1.0).abs().max()))
    print(f"check: symmetry err {sym:.2e}, self-score err {self_err:.2e}",
          flush=True)
    if sym > 5e-3 or self_err > 5e-3:
        sys.exit("chamfer self-check failed")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--track-release-csv", default=None,
                    help="track_id,release_id rows exported from the catalogue")
    ap.add_argument("--release-circle-csv", default=None,
                    help="release_id,circle_id rows exported from the catalogue")
    ap.add_argument("--targets-csv", default=None,
                    help="AlbumID,TrackID,PlaylistPath fallback; groups come "
                         "from playlist paths instead of entity ids")
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

    if args.track_release_csv:
        track_album = read_pairs(args.track_release_csv)
        album_circle = (read_pairs(args.release_circle_csv)
                        if args.release_circle_csv else None)
        mapping_src = "database export"
    elif args.targets_csv:
        track_album, album_circle = read_mappings(args.targets_csv)
        mapping_src = "playlist paths"
    else:
        ap.error("need --track-release-csv or --targets-csv")
    if args.level == "circle" and not album_circle:
        ap.error("circle level needs --release-circle-csv or --targets-csv")
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

    gamma, med = calibrate_gamma(vecs, idx, mask, cand)
    print(f"kde: median candidate member distance {med:.4f} "
          f"-> gamma {gamma:.1f}", flush=True)
    kaa = self_kernel_mass(vecs, idx, mask, eff, gamma)

    check_symmetry(vecs, idx, mask, eff, kaa, n, args.dup_thresh, gamma)

    os.makedirs(args.out, exist_ok=True)
    paths = {
        "style": os.path.join(args.out, f"similar_{args.level}s.csv"),
        "raw": os.path.join(args.out, f"similar_{args.level}s_raw.csv"),
        "kde": os.path.join(args.out, f"similar_{args.level}s_kde.csv"),
    }
    keep = {"style": min(args.top, k), "raw": min(args.top_raw, k),
            "kde": min(args.top, k)}
    t_run = time.time()
    handles = {fl: open(p + ".tmp", "w", newline="", encoding="utf-8")
               for fl, p in paths.items()}
    writers = {}
    for fl, h in handles.items():
        writers[fl] = csv.writer(h)
        writers[fl].writerow(["anchor_id", "neighbor_id", "rank",
                              "score_style", "score_raw", "score_kde"])
    for i in range(0, n, args.batch):
        a = torch.arange(i, min(n, i + args.batch), device=device)
        c = cand[a.long()]
        raw, style, kde = chamfer_groups(
            vecs, idx, mask, eff, kaa, a, c, args.dup_thresh, gamma)
        scores = {"style": style, "raw": raw, "kde": kde}
        for fl, w in writers.items():
            top = scores[fl].topk(keep[fl], dim=1)
            nbr = torch.gather(c, 1, top.indices).cpu().numpy()
            cols = [torch.gather(scores[s], 1, top.indices).cpu().numpy()
                    for s in ("style", "raw", "kde")]
            for bi, row in enumerate(a.tolist()):
                for r in range(nbr.shape[1]):
                    w.writerow([gids[row], gids[nbr[bi, r]], r + 1]
                               + [f"{col[bi, r]:.6f}" for col in cols])
    for fl, h in handles.items():
        h.close()
        os.replace(paths[fl] + ".tmp", paths[fl])

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
            "kde_gamma": round(gamma, 2),
            "kde_median_dist": round(med, 6),
            "mapping": mapping_src,
            "members": "track pooled vectors" if args.level == "album"
                       else "album centroids",
            "scoring": "symmetric chamfer; style flavor drops member pairs "
                       ">= dup_thresh from both maxes; kde is the cosine of "
                       "RBF kernel mean embeddings, median-heuristic gamma",
            "wall_seconds": round(time.time() - t_run, 1),
        }, f, indent=2)
    print(f"run complete: {n} {args.level}s in {time.time() - t_run:.1f}s",
          flush=True)


if __name__ == "__main__":
    main()
