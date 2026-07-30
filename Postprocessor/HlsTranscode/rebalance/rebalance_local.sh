#!/usr/bin/env bash
# Switch the LOCAL worker to sub-shards 1 then 3 of 8, once its shard-0 run
# exits. Fire-and-forget: it waits for shard 0 to finish on its own.
#
#   cd ~/prog_other/tlmc-etl
#   nohup bash Postprocessor/HlsTranscode/rebalance/rebalance_local.sh \
#     > ~/hls-rebalance-local.log 2>&1 &
set -euo pipefail

REPO=/home/sqz269/prog_other/tlmc-etl
STAGE=/home/sqz269/hls-stage
OUT="$REPO/Postprocessor/HlsTranscode/output"
REMOTE=sqz269@192.168.88.241
REMOTE_LIST=prog_other/tlmc-etl/Postprocessor/HlsTranscode/output/hls_transcode.completed.output.shard1of2.txt

# 1. Wait for the shard-0 run to finish; a running worker means the node's
#    cores are already spoken for and buckets 0/2/4/6 are still in flight.
while docker ps --format '{{.Names}}' | grep -qx tlmc-hls; do
  echo "$(date -Is) shard-0 worker still running, checking again in 5 min"
  sleep 300
done
echo "=== $(date -Is) shard-0 worker has exited ==="

# 2. The remote must be OFF shard 1 of 2, or both nodes would encode buckets
#    1/3 concurrently and race publishes into the same destination dirs.
remote_env=$(ssh -o ConnectTimeout=10 "$REMOTE" \
  'docker inspect tlmc-hls --format "{{json .Config.Env}}" 2>/dev/null' || true)
if echo "$remote_env" | grep -q 'TLMC_SHARD_COUNT=2'; then
  echo "ABORT: remote is still on shard 1 of 2 -- run rebalance_remote.sh there first" >&2
  exit 1
fi
if [ -z "$remote_env" ]; then
  # No container to inspect (remote may be between its two sub-shard runs).
  # Accept only if its shard1of2 list has been quiet for a while.
  age=$(ssh -o ConnectTimeout=10 "$REMOTE" \
    "echo \$(( \$(date +%s) - \$(stat -c %Y '$REMOTE_LIST') ))")
  if [ "$age" -lt 600 ]; then
    echo "ABORT: no remote container, but its shard1of2 list changed ${age}s ago" >&2
    exit 1
  fi
fi

# 3. Freeze-copy the remote's shard-1 completed list; remove_completed globs
#    every completed.output*.txt in the output dir, so dropping the file here
#    is the entire hand-off -- no journal surgery.
scp -q "$REMOTE:$REMOTE_LIST" "$OUT/hls_transcode.completed.output.shard1of2.txt"
echo "=== $(date -Is) imported remote completed list: $(wc -l < "$OUT/hls_transcode.completed.output.shard1of2.txt") ids ==="

docker rm tlmc-hls 2>/dev/null || true
rm -rf "$STAGE"/*

for IDX in 1 3; do
  echo "=== $(date -Is) starting sub-shard $IDX of 8 ==="
  docker run --rm --name tlmc-hls \
    -v "$REPO":/repo \
    -v /mnt/tlmc:/mnt/tlmc \
    -v "$STAGE":/stage \
    -e TLMC_SHARD_COUNT=8 -e TLMC_SHARD_INDEX="$IDX" -e TLMC_STAGE_DIR=/stage \
    tlmc-ffmpeg:runner
done
echo "=== $(date -Is) local sub-shards 1 and 3 complete ==="
