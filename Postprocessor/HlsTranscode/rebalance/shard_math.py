"""Sub-shard accounting for rebalancing the two-node HLS transcode.

The runner assigns work by blake2b(track_id) % TLMC_SHARD_COUNT, so mod-8
sub-shards nest exactly inside the mod-2 shards: {0,2,4,6} is shard 0 of 2,
{1,3,5,7} is shard 1 of 2. That, plus remove_completed() honouring every
completed list it can glob, means the shard config can change between runs
with no journal surgery: put every node's completed list in the output dir
and relaunch with the new count/index.

Run from the repo root. Reads the worklist plus every
hls_transcode.completed.output*.txt in the output dir (drop copies of other
nodes' lists there before running) and prints per-bucket totals so the
node split can be chosen from real remaining counts, not estimates.
"""

import glob
import hashlib
import json
import os
import sys

OUT = "Postprocessor/HlsTranscode/output"
WORKLIST = os.path.join(OUT, "hls_transcode.worklist.output.json")

MOD = 8
# Planned ownership of shard-1-of-2's sub-buckets; shard 0 of 2 ({0,2,4,6})
# stays with the local node's original run and is listed for completeness.
PLAN = {
    1: "local (phase 2)",
    3: "local (phase 2)",
    5: "remote (now)",
    7: "remote (now)",
}


def bucket(track_id: str) -> int:
    digest = hashlib.blake2b(track_id.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % MOD


def main() -> int:
    extra = sys.argv[1:]  # optional: extra completed-list files to honour

    with open(WORKLIST, "r", encoding="utf-8") as f:
        worklist = json.load(f)

    completed = set()
    root, ext = os.path.splitext(
        os.path.join(OUT, "hls_transcode.completed.output.txt")
    )
    root = root[: -len(".output")] + ".output"  # keep the glob identical to the runner's
    paths = sorted(glob.glob(f"{root}*{ext}")) + extra
    for path in paths:
        with open(path, "r", encoding="utf-8") as f:
            ids = {line.strip() for line in f if line.strip()}
        print(f"  {len(ids):>7,}  {path}")
        completed |= ids

    print(f"\nWorklist {len(worklist):,} tracks, {len(completed):,} unique completed\n")

    total = [0] * MOD
    done = [0] * MOD
    for tid in worklist:
        b = bucket(tid)
        total[b] += 1
        if tid in completed:
            done[b] += 1

    print(f"{'bucket':>6} {'owner':<16} {'total':>8} {'done':>8} {'remaining':>10}")
    rem_shard1 = 0
    for b in range(MOD):
        owner = PLAN.get(b, "local (shard 0 run)" if b % 2 == 0 else "?")
        rem = total[b] - done[b]
        if b % 2 == 1:
            rem_shard1 += rem
        print(f"{b:>6} {owner:<16} {total[b]:>8,} {done[b]:>8,} {rem:>10,}")

    print(f"\nshard 1 of 2 remaining across buckets 1,3,5,7: {rem_shard1:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
