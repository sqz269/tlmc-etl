"""Build a chunk store from a directory of per-track .pt chunk tensors.

Parallel readers feed a single writer thread. The parallelism is for the
filesystem, not the CPU: against the 9p-mounted v5 embeddings a single reader
manages ~59 files/s while 32 readers sustain ~470, turning a 40-minute walk
into a 5-minute one. The store format itself is written by the append-only
ChunkStoreWriter, so ordering between readers does not matter.
"""

import argparse
import os
import queue
import re
import sys
import threading
import time

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chunk_store import ChunkStoreWriter

UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="directory of .pt chunk tensors")
    ap.add_argument("--out", required=True, help="chunk store root to create")
    ap.add_argument("--dim", type=int, default=1024)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--cap", type=int, default=0,
                    help="max chunks per track via uniform subsample, 0 = keep all")
    args = ap.parse_args()

    paths = []
    for root, _, files in os.walk(args.src):
        for f in files:
            if f.endswith(".pt"):
                paths.append(os.path.join(root, f))
    paths.sort()
    print(f"{len(paths)} .pt files under {args.src}", flush=True)

    q: "queue.Queue" = queue.Queue(maxsize=256)
    skipped = []
    skip_lock = threading.Lock()

    def skip(path: str, reason: str) -> None:
        with skip_lock:
            skipped.append((path, reason))

    def reader(sub) -> None:
        for p in sub:
            m = UUID_RE.search(os.path.basename(p))
            if not m:
                skip(p, "no uuid in filename")
                continue
            try:
                t = torch.load(p, map_location="cpu")
                if isinstance(t, list):
                    t = torch.stack(t)
                v = t.float().numpy()
            except Exception as e:  # noqa: BLE001 - journal and continue
                skip(p, repr(e)[:160])
                continue
            if v.ndim != 2 or v.shape[1] != args.dim or v.shape[0] == 0:
                skip(p, f"bad shape {v.shape}")
                continue
            if args.cap and v.shape[0] > args.cap:
                pick = np.linspace(0, v.shape[0] - 1, args.cap).round().astype(int)
                v = v[pick]
            q.put((m.group(0), v))

    shards = [paths[i:: args.workers] for i in range(args.workers)]
    threads = [threading.Thread(target=reader, args=(s,), daemon=True) for s in shards]
    for t in threads:
        t.start()

    manifest = {
        "source": args.src,
        "model": "m-a-p/MERT-v1-330M last4-mean L2-normalized",
        "chunk_s": 6,
        "overlap_s": 2,
    }
    if args.cap:
        manifest["max_chunks_per_track"] = args.cap

    done = 0
    total_chunks = 0
    t0 = time.time()
    with ChunkStoreWriter(args.out, dim=args.dim, manifest=manifest) as w:
        while any(t.is_alive() for t in threads) or not q.empty():
            try:
                tid, v = q.get(timeout=1.0)
            except queue.Empty:
                continue
            w.add(tid, v)
            done += 1
            total_chunks += v.shape[0]
            if done % 5000 == 0:
                rate = done / (time.time() - t0)
                print(f"  {done}/{len(paths)} tracks ({rate:.0f}/s, "
                      f"{total_chunks} chunks)", flush=True)

    dt = time.time() - t0
    print(f"DONE: {done} tracks, {total_chunks} chunks "
          f"({total_chunks * args.dim * 2 / 1e9:.1f} GB fp16), "
          f"{len(skipped)} skipped, {dt:.0f}s", flush=True)
    for p, r in skipped[:20]:
        print(f"  skip: {p}: {r}", flush=True)


if __name__ == "__main__":
    main()
