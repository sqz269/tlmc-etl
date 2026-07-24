"""
Late interaction scoring over chunk embeddings.

Two scoring functions, for two different questions:

  maxsim    asymmetric, "does this track contain the query"
            score(Q,D) = mean_i max_j <q_i, d_j>
            Correct for moment search. Unnormalised in |D|, so a long track gets
            more draws at the max for every query chunk. Prefer the sum variant
            only when |D| is capped.

  chamfer   symmetric, "are these two tracks alike"
            score(A,B) = 1/2 (mean_i max_j <a_i,b_j> + mean_j max_i <b_j,a_i>)
            Correct for track-to-track similarity. Both sides are mean
            normalised so length bias largely cancels, and the relation is
            symmetric, which matters when caching related tracks per track.

Both take a query matrix and a batch of candidate tracks laid out end to end,
score every candidate with one matmul, and reduce per segment. That is much
faster than looping a matmul per candidate: at 200 candidates x ~60 chunks the
similarity matrix is only [60, 12000].

Vectors are assumed L2 normalised (the embedding pipeline emits them that way),
so a dot product is cosine similarity.
"""

from typing import List, Optional, Sequence, Tuple

import numpy as np

from Experimental.vector_search.chunk_store import COMPUTE_DTYPE, ChunkStore


def _prepare(query: np.ndarray, normalize: bool) -> np.ndarray:
    query = np.asarray(query, dtype=COMPUTE_DTYPE)
    if query.ndim == 1:
        query = query[None, :]
    if query.ndim != 2:
        raise ValueError(f"query must be [n_chunks, dim], got {query.shape}")
    if normalize:
        norms = np.linalg.norm(query, axis=1, keepdims=True)
        np.maximum(norms, 1e-12, out=norms)
        query = query / norms
    return query


def _segment_scores(
    query: np.ndarray,
    matrix: np.ndarray,
    starts: np.ndarray,
    counts: np.ndarray,
    query_weights: Optional[np.ndarray],
    symmetric: bool,
) -> np.ndarray:
    """
    Core reduction. Returns one score per segment (candidate track).

    `starts`/`counts` describe contiguous row ranges of `matrix`, as produced by
    ChunkStore.gather.
    """
    if matrix.shape[0] == 0:
        return np.zeros(0, dtype=COMPUTE_DTYPE)

    # [n_query_chunks, n_candidate_chunks]
    sims = query @ matrix.T

    # Query side: best matching candidate chunk for each query chunk, per track.
    # np.maximum.reduceat segments along the candidate axis in one pass.
    seg_max = np.maximum.reduceat(sims, starts, axis=1)  # [n_query, n_segments]

    if query_weights is None:
        q_side = seg_max.mean(axis=0)
    else:
        weights = np.asarray(query_weights, dtype=COMPUTE_DTYPE)
        if weights.shape[0] != query.shape[0]:
            raise ValueError("query_weights must have one entry per query chunk")
        total = float(weights.sum())
        if total <= 0:
            raise ValueError("query_weights must sum to a positive value")
        q_side = (seg_max * weights[:, None]).sum(axis=0) / total

    if not symmetric:
        return q_side

    # Document side: best matching query chunk for each candidate chunk, then
    # averaged within each track.
    col_max = sims.max(axis=0)  # [n_candidate_chunks]
    d_side = np.add.reduceat(col_max, starts) / counts.astype(COMPUTE_DTYPE)

    return 0.5 * (q_side + d_side)


def maxsim_scores(
    query: np.ndarray,
    matrix: np.ndarray,
    starts: np.ndarray,
    counts: np.ndarray,
    query_weights: Optional[np.ndarray] = None,
    normalize: bool = False,
) -> np.ndarray:
    """Asymmetric late interaction, mean normalised over query chunks."""
    query = _prepare(query, normalize)
    return _segment_scores(query, matrix, starts, counts, query_weights, False)


def chamfer_scores(
    query: np.ndarray,
    matrix: np.ndarray,
    starts: np.ndarray,
    counts: np.ndarray,
    query_weights: Optional[np.ndarray] = None,
    normalize: bool = False,
) -> np.ndarray:
    """Symmetric Chamfer similarity, mean normalised on both sides."""
    query = _prepare(query, normalize)
    return _segment_scores(query, matrix, starts, counts, query_weights, True)


def rerank(
    store: ChunkStore,
    query: np.ndarray,
    candidate_ids: Sequence[str],
    mode: str = "chamfer",
    top_k: Optional[int] = None,
    query_weights: Optional[np.ndarray] = None,
    normalize: bool = False,
) -> List[Tuple[str, float]]:
    """
    Scores `candidate_ids` against `query` and returns them ranked.

    Candidates typically come from a cheap first stage (pooled-vector ANN in
    pgvector, or a chunk level ANN index for moment search). Unknown ids are
    dropped by the store rather than raising.
    """
    scorer = {"chamfer": chamfer_scores, "maxsim": maxsim_scores}.get(mode)
    if scorer is None:
        raise ValueError(f"unknown mode {mode!r}, expected 'chamfer' or 'maxsim'")

    matrix, starts, counts, resolved = store.gather(candidate_ids)
    if not resolved:
        return []

    scores = scorer(
        query, matrix, starts, counts, query_weights=query_weights, normalize=normalize
    )

    order = np.argsort(-scores)
    if top_k is not None:
        order = order[:top_k]

    return [(resolved[i], float(scores[i])) for i in order]


def self_similarity(
    store: ChunkStore,
    track_id: str,
    candidate_ids: Sequence[str],
    top_k: Optional[int] = None,
) -> List[Tuple[str, float]]:
    """
    Convenience wrapper for track-to-track similarity: uses the track's own
    chunks as the query and drops it from its own results.
    """
    query = np.asarray(store.get(track_id), dtype=COMPUTE_DTYPE)
    others = [t for t in candidate_ids if t != track_id]
    return rerank(store, query, others, mode="chamfer", top_k=top_k)


def estimate_chunk_weights(
    query: np.ndarray,
    background: np.ndarray,
    strength: float = 1.0,
) -> np.ndarray:
    """
    Down-weights generic query chunks, the audio analogue of IDF.

    Silence, fade-ins, applause and plain drum loops sit near the centre of the
    embedding space and match everything, inflating scores for tracks that share
    nothing musically. A chunk's mean similarity to a random background sample
    estimates how generic it is; weight falls as that rises.

    `background` should be a random sample of chunk vectors from the corpus
    (100k rows is plenty). Returns weights in (0, 1], one per query chunk.
    """
    query = np.asarray(query, dtype=COMPUTE_DTYPE)
    if query.ndim == 1:
        query = query[None, :]
    background = np.asarray(background, dtype=COMPUTE_DTYPE)

    generic = (query @ background.T).mean(axis=1)
    spread = generic.std()
    if spread < 1e-6:
        return np.ones(query.shape[0], dtype=COMPUTE_DTYPE)

    z = (generic - generic.mean()) / spread
    weights = 1.0 / (1.0 + np.exp(strength * z))
    return weights.astype(COMPUTE_DTYPE)
