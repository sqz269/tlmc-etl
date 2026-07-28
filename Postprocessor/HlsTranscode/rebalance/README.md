# Rebalancing the two-node transcode (2026-07-28)

## Why

At 59% overall, the shards had diverged badly: local (shard 0 of 2) at 77%
finishing in ~5.4 h, remote (shard 1 of 2) at 41% needing ~30 h more — it pays
SMB round-trips in both directions and lost hours to the MERT container work.
Without intervention the local node idles for a day while the remote grinds.

## How it works

Two properties of `hls_runner.py` make this a config change, not surgery:

* Ownership is `blake2b(track_id) % TLMC_SHARD_COUNT`, so mod-8 buckets nest
  exactly inside mod-2 shards: `{0,2,4,6}` ≡ shard 0 of 2, `{1,3,5,7}` ≡
  shard 1 of 2.
* `remove_completed()` honours **every** `completed.output*.txt` it can glob in
  the output dir — its comment: the shard count "can change between runs".
  Dropping another node's list into the dir is the entire hand-off.

Shard 1's remainder is split by measured node speed (~0.88 vs ~0.45 tracks/s),
with the remote starting immediately while the local first drains shard 0:

| bucket | owner | remaining (at prep time) |
|---|---|---|
| 1, 3 | local, after its shard-0 run exits | 23,237 |
| 5, 7 | remote, immediately | 23,058 |

Projected completion ~14 h from firing, vs ~30 h unbalanced. Numbers above are
from `shard_math.py` run 2026-07-28; re-run it any time to get fresh counts
(pass paths of other nodes' completed lists as extra args).

## Procedure

1. **Remote, any time** (safe immediately — its completed list keeps
   everything it already did):

       scp Postprocessor/HlsTranscode/rebalance/rebalance_remote.sh sqz269@192.168.88.241:
       ssh sqz269@192.168.88.241 'nohup bash rebalance_remote.sh > ~/hls-rebalance.log 2>&1 &'

2. **Local, fire-and-forget** (waits for the shard-0 container to exit, then
   verifies the remote is off shard 1 of 2, imports its completed list, and
   runs buckets 1 then 3):

       nohup bash Postprocessor/HlsTranscode/rebalance/rebalance_local.sh \
         > ~/hls-rebalance-local.log 2>&1 &

Order matters only in that the local script refuses to start buckets 1/3
while the remote still owns all of shard 1 — both nodes encoding the same
track would race their publishes into one destination directory.

## Both scripts replicate the production container exactly

Captured via `docker inspect tlmc-hls` on each node before writing these:
image `tlmc-ffmpeg:runner`, mounts `repo->/repo`, `/mnt/tlmc->/mnt/tlmc`,
`~/hls-stage->/stage`, env `TLMC_STAGE_DIR=/stage` — only
`TLMC_SHARD_COUNT/INDEX` change. Interrupted in-flight tracks are never
marked completed, so a stop loses at most a few minutes of encode time, and
staged partials are swept while the worker is down.

## Afterwards (mop-up)

1. Gather every node's `completed.output*.txt` into the local output dir
   (buckets 5/7 lists live on the remote: `*.shard5of8.txt`, `*.shard7of8.txt`).
2. Run one final local pass with `TLMC_SHARD_COUNT=2 TLMC_SHARD_INDEX=1`: it
   skips everything completed and retries only failures — including the ~30
   remote `Failed to publish: No such file or directory` errors on
   CJK-heavy paths, which look like an SMB path-resolution problem on the
   remote and should succeed from the node that owns the disks.
   (The handful of upstream-truncated FLACs will fail again; they are
   unrecoverable by re-encoding.)
3. `hls_verify.py` / `hls_finalizer.py` as originally planned.
