"""
Derives the per-track pooled vectors Postgres serves (mean 1024, mean+max 2048)
straight from the chunk store, replacing make_embeddings.py's
load-everything-into-RAM pass over raw .pt files — 10.3M chunks do not fit.

Pooling matches utils.pool exactly: mean over chunks, and concat(mean, max),
accumulated in fp32 from the store's fp16, no renormalization. Output is the
push_ready layout PushToDb consumes: <out>/mean/<uuid>.bin (1024 x float32)
and <out>/mean+max/<uuid>.bin (2048 x float32), plus a manifest recording
provenance so embedding_config is filled from data rather than memory.
"""

import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.append(os.path.dirname(__file__))
from chunk_store import ChunkStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, help="chunk store root")
    parser.add_argument("--out", required=True, help="push_ready output root")
    args = parser.parse_args()

    store = ChunkStore(args.store)
    mean_dir = os.path.join(args.out, "mean")
    meanmax_dir = os.path.join(args.out, "mean+max")
    os.makedirs(mean_dir, exist_ok=True)
    os.makedirs(meanmax_dir, exist_ok=True)

    started = time.time()
    for i, track_id in enumerate(store.track_ids):
        track_id = str(track_id)
        offset = int(store.offsets[i])
        count = int(store.counts[i])
        chunks = np.asarray(store._vectors[offset:offset + count], dtype=np.float32)

        mean = chunks.mean(axis=0)
        meanmax = np.concatenate((mean, chunks.max(axis=0)))

        mean.astype(np.float32).tofile(os.path.join(mean_dir, f"{track_id}.bin"))
        meanmax.astype(np.float32).tofile(os.path.join(meanmax_dir, f"{track_id}.bin"))

        if (i + 1) % 10000 == 0:
            rate = (i + 1) / (time.time() - started)
            print(f"[{i + 1}/{len(store)}] {rate:.0f} tracks/s", flush=True)

    manifest = {
        "source_store": os.path.abspath(args.store),
        "store_manifest": store.manifest,
        "poolings": {"mean": 1024, "mean+max": 2048},
        "dtype": "float32",
        "tracks": len(store),
    }
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4, ensure_ascii=False)

    print(f"Done: {len(store)} tracks in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
