"""Sanity-check precomputed similar-track shards against catalogue metadata.

Prints a sample of anchors with their top neighbors (titles and artists), and
two aggregate signals with a random-pair baseline for contrast:

  same-artist@10   fraction of top-10 neighbors sharing the anchor's artist
  same-album@10    fraction sharing the anchor's album

These are weak labels, not ground truth -- a low-but-above-baseline rate is
expected and healthy (an artist's tracks should cluster, but a similarity
feature that only returns the same artist would be useless).
"""

import argparse
import csv
import glob
import os
import random
from collections import defaultdict


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", required=True, help="similar_tracks output dir")
    ap.add_argument("--metadata", required=True, help="id_metadata.csv")
    ap.add_argument("--sample", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    meta = {}
    with open(args.metadata, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            meta[row["TrackID"]] = (
                row["TrackName"], row["ArtistName"], row["AlbumID"], row["AlbumName"])

    neighbors = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(args.shards, "similar_*.csv"))):
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                neighbors[row["anchor_id"]].append(
                    (row["neighbor_id"], float(row["score"])))
    print(f"{len(neighbors)} anchors loaded from shards")
    if not neighbors:
        return

    rng = random.Random(args.seed)
    anchors = list(neighbors)

    known = [a for a in anchors if a in meta]
    same_artist = same_album = considered = 0
    for a in known:
        _, artist, album, _ = meta[a]
        for nid, _ in neighbors[a][:10]:
            if nid not in meta:
                continue
            considered += 1
            same_artist += meta[nid][1] == artist
            same_album += meta[nid][2] == album

    ids_known = [t for t in meta if t in neighbors or True]
    rand_artist = rand_album = 0
    pairs = 20000
    for _ in range(pairs):
        x, y = rng.choice(known), rng.choice(ids_known)
        rand_artist += meta[x][1] == meta[y][1]
        rand_album += meta[x][2] == meta[y][2]

    print(f"metadata coverage: {len(known)}/{len(anchors)} anchors")
    print(f"same-artist@10: {same_artist / considered:.3f}  "
          f"(random-pair baseline {rand_artist / pairs:.4f})")
    print(f"same-album@10:  {same_album / considered:.3f}  "
          f"(random-pair baseline {rand_album / pairs:.4f})")
    print()

    for a in rng.sample(known, min(args.sample, len(known))):
        name, artist, _, album = meta[a]
        print(f"ANCHOR  {name}  --  {artist}  [{album}]")
        for nid, score in neighbors[a][:5]:
            if nid in meta:
                n_name, n_artist, _, n_album = meta[nid]
                print(f"  {score:.4f}  {n_name}  --  {n_artist}  [{n_album}]")
            else:
                print(f"  {score:.4f}  <no metadata: {nid}>")
        print()


if __name__ == "__main__":
    main()
