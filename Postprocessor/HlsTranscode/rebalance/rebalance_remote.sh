#!/usr/bin/env bash
# Switch the REMOTE worker from shard 1 of 2 to sub-shards 5 then 7 of 8.
#
# Safe to fire at any time: everything it has already completed stays in its
# shard1of2 completed list, which every later run honours. Run ON the remote
# host, detached so an ssh drop does not kill the second sub-shard:
#
#   nohup bash rebalance_remote.sh > ~/hls-rebalance.log 2>&1 &
set -euo pipefail

REPO=/home/sqz269/prog_other/tlmc-etl
STAGE=/home/sqz269/hls-stage

echo "=== $(date -Is) stopping shard-1of2 worker ==="
docker stop tlmc-hls || true
docker rm tlmc-hls 2>/dev/null || true

# Tracks in flight at the stop died unrecorded (they will be re-encoded), so
# their staged partials are garbage. Only safe while no worker is running.
rm -rf "$STAGE"/*

for IDX in 5 7; do
  echo "=== $(date -Is) starting sub-shard $IDX of 8 ==="
  docker run --rm --name tlmc-hls \
    -v "$REPO":/repo \
    -v /mnt/tlmc:/mnt/tlmc \
    -v "$STAGE":/stage \
    -e TLMC_SHARD_COUNT=8 -e TLMC_SHARD_INDEX="$IDX" -e TLMC_STAGE_DIR=/stage \
    tlmc-ffmpeg:runner
done
echo "=== $(date -Is) remote sub-shards 5 and 7 complete ==="
