# Similarity search: architecture decisions and the chamfer precompute plan

Written 2026-07-28, while the v6 HLS transcode was still running and before the
full MERT embedding pass. Records the investigation and decisions so far so the
precompute can be built without re-deriving any of it.

## Architecture decided

Two-tier retrieval, ColBERT-shaped (cheap candidate generation, then exact
late-interaction scoring), with **no Python serving component**:

1. **pgvector tier (recall + serving)** — pooled vectors per track in Postgres.
   Done and verified 2026-07-28 on branches `pgvector-ann-tier` (tlmc-player)
   and `pushtodb-halfvec` (tlmc-etl), uncommitted at time of writing:
   `EmbeddingMeanMax` converted `vector(2048)` → `halfvec(2048)` (pgvector
   indexes cap at 2000 dims for `vector`, 4000 for `halfvec`), HNSW indexes on
   both columns, two-phase ANN-then-hydrate query in `TrackRepo`, package bump
   to Pgvector.EntityFrameworkCore 0.3.0, dev compose → `pgvector/pgvector:pg15`,
   PV 5Gi → 20Gi. Migration `EmbeddingHalfvecAndHnsw` verified against live
   pgvector 0.8.5 with seeded data; EF-generated SQL confirmed HNSW-eligible.
2. **Chunk tier (precision)** — fp16 chunk store + chamfer scoring, run as an
   **offline GPU precompute** into a `SimilarTracks` table, not a live service.
   The current product feature takes a trackId (closed query set), so serving
   becomes a SQL lookup. A live in-backend .NET rerank
   (MemoryMappedFile + TensorPrimitives, ~a day of work) and a chunk-level ANN
   index (usearch / P/Invoked faiss) are fallback options only if open queries
   (query-by-audio, moment search) become real features. There is no maintained
   .NET faiss; that gap is why open-query search would reopen this decision.

## Chamfer precompute: what exists (verified 2026-07-28)

- `Experimental/vector_search/rerank.py` — chamfer math is correct: symmetric
  mean-of-max both directions, fp32 accumulation, batched via one matmul +
  `np.maximum.reduceat` segment reduction. `self_similarity()` is exactly the
  precompute inner op (track's own chunks as query, drop self-match).
- `Experimental/vector_search/chunk_store.py` — fp16 append writer, mmap
  reader, ragged `gather()`, and `write_store_from_tensors` (streams one `.pt`
  at a time, optional uniform-subsampling cap per track).
- **Cosine assumption holds**: chunks are L2-normalized before saving
  (`mert_batched_uuid.py:288`, `F.normalize(vec, p=2, dim=-1)`), so dot
  product == cosine throughout.
- `Experimental/utils/journal.py` (`RunJournal`) — reusable for resume.
- `tlmc-mert:runner` container — torch+CUDA already validated on the 5090.

## What's missing (the work)

1. **GPU port of chamfer** — rerank.py is numpy/CPU only (~weeks at this
   scale on CPU; ~2–3 h on GPU). Design: whole store resident in VRAM as one
   ragged fp16 tensor `[~9.7M, 1024]` + offsets; precomputed padded index
   matrix `[164k, C]` int32 + mask; chamfer as batched einsum with masked max.
   ~150 lines of torch.
2. **Pooled recall stage** — at 164k tracks this is EXACT, not ANN: derive
   pooled vectors from the store by segment mean, tiled `[164k × 164k]`
   matmul + topK. No faiss, no pgvector dependency.
3. **Driver script** — anchor batching, RunJournal resume, parquet shards of
   `(anchor_id, neighbor_id, rank, score)`; 164k × top-100 ≈ 16M rows.
4. **Store build** — one `write_store_from_tensors` pass over the `.pt`
   directory after inference completes (~30 min on the GPU box NVMe).
5. **Backend landing zone** — `SimilarTracks` table + migration + PushToDb
   step; the existing `DiversitySampler` endpoint logic survives by
   overfetching from the precomputed top-100.

## Budget (RTX 5090, 32 GB)

| item | size / time |
|---|---|
| chunk store in VRAM, fp16 | 19.9 GB uncapped · 16 GB @ cap 48 |
| candidate gather workspace (64 anchors × K=500, C=64) | ~4–5 GB |
| pooled matrix + recall tile + topK buffers | ~3.5 GB |
| total VRAM | ~25–28 GB — fits, no spill |
| store build from `.pt` | ~30 min, once |
| exact pooled recall (164k × 164k, ~110 TFLOP) | ~2–5 min |
| chamfer rerank K=500 (~585 TFLOP) | ~2–3 h |

Full brute-force late interaction without a recall stage is ~190 PFLOP ≈ 3
weeks — that is why the recall stage exists. The driver must assert VRAM
allocations up front: exceeding 32 GB on this card silently spills to host
memory over PCIe on WSL (measured 14× slowdown during the MERT batch sweep,
see `Experimental/docker/README.md`).

## Design defaults (revisit with the eval, below)

- **K = 500** candidates per anchor, keep **top-100**, chunk cap **C = 64**
  (uniform subsample; covers ~4:20 of audio, longer tracks sampled across
  their whole length).
- **Skip `estimate_chunk_weights` in v1**: it is query-side only, so in
  chamfer it silently breaks symmetry — chamfer(a,b) ≠ chamfer(b,a). The
  generic-chunk problem it addresses (silence/fades match everything) is
  real; a symmetric treatment is a v2 item.
- **Correctness gate for the GPU port**: a few hundred random pairs scored on
  GPU must match the numpy path within fp16 tolerance; plus invariants
  (symmetry, self-score ≈ 1.0).
- Use **chamfer, not maxsim**, for track-to-track (maxsim is asymmetric —
  right for moment search only).

## Sequencing

Blocked ONLY by the audio pipeline, not by tagging:

    transcode (running) → MERT inference (~10 h) → store build (~30 min)
                        → precompute (~2–3 h) → PushToDb → backend lookup

The driver can be written and tested now against the partial `chunked_6s`
embeddings so it is ready the moment inference finishes.

## Parked: metadata eval (waiting on complete tagging + transcode)

Design agreed, execution deferred. Weak labels from metadata, three probe
sets, each measuring a different similarity axis:

| probe | positives | measures | trap |
|---|---|---|---|
| same-original | same ZUN original via `OriginalTracks`, restricted to different albums/circles | melody across styles | without the restriction it measures circle sound |
| same-album | same album | production/timbre floor | near-trivial; failing it means broken |
| same-circle | same circle, different album | style signature | genre-hopping circles add noise — fine in aggregate |

~2,000 seeded anchors per probe, fixed across configs (paired comparison).
Metrics: Hit@k (10/50/100), median rank of first positive, MRR — reported per
probe, never blended; bootstrap CIs over anchors. Two-stage failure
attribution: stage-1 recall@K (did the positive reach the candidate pool) vs
stage-2 oracle test (inject known positives into the pool; does chamfer rank
them above pooled cosine — if not, late interaction isn't earning its
complexity). Whole battery runs in minutes on the 5090. Outputs the decisions:
pooling mode for pgvector, whether chamfer stays in the precompute, and K.
Known blind spot: labels inherit the embeddings' vocal-vs-instrumental bias;
patch with a 20-minute listening spot-check of the winning config only.

Also known and accepted: MERT+cosine measures "sounds alike"
(timbre/production/genre), not "same melody" — cover identification is a
different task, and same-original is already a metadata join
(`OriginalTracks`), better served as its own UI rail than blended into the
similarity score. If recall quality disappoints, try VLAD (prototyped in
`vector_search/`) or MUVERA-style fixed-dim encodings before touching the
model; only layer-choice ablation would force a re-run of inference.
