"""
Flat on-disk store for per-track chunk embeddings.

Late interaction scoring needs every chunk of a candidate track, not a pooled
summary, so the access pattern is "give me all vectors for these ~200 track ids".
This lays chunks out contiguously per track in one fp16 file, so a track is a
single sequential read and the whole store can be mmapped: after warmup the
working set lives in page cache and reranking touches no disk at all.

Layout:
    <root>/vectors.f16     raw little-endian float16, [total_chunks, dim]
    <root>/index.npz       track_ids (str), offsets (int64), counts (int32)
    <root>/manifest.json   model, chunking config and dtype the vectors came from

Size at TLMC scale: ~9.7M chunks x 1024 dims x 2 bytes = 19.9 GiB, or 16 GiB
with chunks capped at 48 per track. The pooled vectors that live in Postgres are
derived from this store, not the other way around.
"""

import json
import os
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

VECTORS_NAME = "vectors.f16"
INDEX_NAME = "index.npz"
MANIFEST_NAME = "manifest.json"

STORE_DTYPE = np.float16
# Scores are accumulated in fp32; fp16 matmuls lose too much precision once a
# few thousand candidate chunks are involved.
COMPUTE_DTYPE = np.float32


class ChunkStoreWriter:
    """
    Builds a chunk store by appending one track at a time.

    Vectors are expected L2 normalised, which is what the embedding pipeline
    already emits, so scoring can use a plain dot product as cosine similarity.
    """

    def __init__(self, root: str, dim: int, manifest: Optional[dict] = None):
        self.root = root
        self.dim = dim
        self.manifest = dict(manifest or {})

        os.makedirs(root, exist_ok=True)
        self._vectors = open(os.path.join(root, VECTORS_NAME), "wb")
        self._ids: List[str] = []
        self._offsets: List[int] = []
        self._counts: List[int] = []
        self._total = 0

    def add(self, track_id: str, vectors: np.ndarray) -> None:
        """Appends one track's chunk vectors, shape [n_chunks, dim]."""
        vectors = np.asarray(vectors)
        if vectors.ndim != 2 or vectors.shape[1] != self.dim:
            raise ValueError(
                f"{track_id}: expected [n_chunks, {self.dim}], got {vectors.shape}"
            )
        if vectors.shape[0] == 0:
            raise ValueError(f"{track_id}: no chunks")

        self._vectors.write(vectors.astype(STORE_DTYPE, copy=False).tobytes())
        self._ids.append(track_id)
        self._offsets.append(self._total)
        self._counts.append(vectors.shape[0])
        self._total += vectors.shape[0]

    def close(self) -> None:
        self._vectors.close()

        np.savez(
            os.path.join(self.root, INDEX_NAME),
            track_ids=np.array(self._ids, dtype=object),
            offsets=np.array(self._offsets, dtype=np.int64),
            counts=np.array(self._counts, dtype=np.int32),
        )

        manifest = dict(self.manifest)
        manifest.update(
            {
                "dim": self.dim,
                "dtype": "float16",
                "tracks": len(self._ids),
                "total_chunks": self._total,
                "vectors_bytes": self._total * self.dim * 2,
            }
        )
        with open(os.path.join(self.root, MANIFEST_NAME), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=4, ensure_ascii=False)

    def __enter__(self) -> "ChunkStoreWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class ChunkStore:
    """
    Read-only mmapped view over a chunk store.

    The vectors file is never read in full; slicing a track touches only its own
    pages, so memory use tracks the working set rather than the store size.
    """

    def __init__(self, root: str):
        self.root = root

        with open(os.path.join(root, MANIFEST_NAME), "r", encoding="utf-8") as f:
            self.manifest = json.load(f)

        self.dim = int(self.manifest["dim"])

        index = np.load(os.path.join(root, INDEX_NAME), allow_pickle=True)
        self.track_ids: np.ndarray = index["track_ids"]
        self.offsets: np.ndarray = index["offsets"]
        self.counts: np.ndarray = index["counts"]

        total = int(self.offsets[-1] + self.counts[-1]) if len(self.counts) else 0
        self._vectors = np.memmap(
            os.path.join(root, VECTORS_NAME),
            dtype=STORE_DTYPE,
            mode="r",
            shape=(total, self.dim),
        )

        self._row: Dict[str, int] = {
            str(tid): i for i, tid in enumerate(self.track_ids)
        }

    def __len__(self) -> int:
        return len(self.track_ids)

    def __contains__(self, track_id: str) -> bool:
        return track_id in self._row

    @property
    def total_chunks(self) -> int:
        return int(self._vectors.shape[0])

    def get(self, track_id: str) -> np.ndarray:
        """Returns this track's chunk vectors as an fp16 view, [n_chunks, dim]."""
        row = self._row[track_id]
        start = int(self.offsets[row])
        return self._vectors[start : start + int(self.counts[row])]

    def chunk_start_seconds(self, chunk_index: int) -> float:
        """
        Wall clock offset of a chunk within its track.

        Chunks advance by (chunk_size - overlap), not by chunk_size: with the
        6s/2s config the step is 4s, so chunk 30 begins at 120s, not 180s. Derive
        it from the manifest rather than hardcoding, which is how
        faiss_index_search.py ended up reporting timestamps 50% too far in.
        """
        chunk_s = self.manifest.get("chunk_s")
        overlap_s = self.manifest.get("overlap_s", 0)
        if chunk_s is None:
            raise KeyError(
                "manifest has no 'chunk_s'; cannot derive chunk timestamps"
            )
        return chunk_index * (float(chunk_s) - float(overlap_s))

    def gather(
        self, track_ids: Sequence[str]
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[str]]:
        """
        Concatenates several tracks' chunks into one matrix for batched scoring.

        Returns (matrix [total, dim] float32, starts, counts, resolved_ids).
        Unknown ids are skipped rather than raising, so a candidate list coming
        from a stale ANN index does not break the query. `starts` indexes into
        `matrix`, which is what the reranker segments on.
        """
        present = [t for t in track_ids if t in self._row]
        if not present:
            empty = np.zeros((0, self.dim), dtype=COMPUTE_DTYPE)
            return (empty, np.zeros(0, np.int64), np.zeros(0, np.int64), [])

        rows = [self._row[t] for t in present]
        counts = self.counts[rows].astype(np.int64)
        starts = np.zeros(len(counts), dtype=np.int64)
        np.cumsum(counts[:-1], out=starts[1:])

        matrix = np.empty((int(counts.sum()), self.dim), dtype=COMPUTE_DTYPE)
        for slot, row in enumerate(rows):
            src = int(self.offsets[row])
            n = int(self.counts[row])
            dst = int(starts[slot])
            matrix[dst : dst + n] = self._vectors[src : src + n]

        return (matrix, starts, counts, present)


def write_store_from_tensors(
    tensor_dir: str,
    out_root: str,
    dim: int = 1024,
    manifest: Optional[dict] = None,
    max_chunks_per_track: Optional[int] = None,
    id_from_filename=None,
) -> Tuple[int, int]:
    """
    Builds a store from a directory of per-track `.pt` files.

    `max_chunks_per_track` caps long tracks by uniform subsampling. That bounds
    both the store size and the document-length bias in MaxSim, where a 300 chunk
    DJ mix otherwise gets 300 draws at the max for every query chunk.

    Returns (tracks_written, chunks_written).
    """
    import torch

    if id_from_filename is None:
        import re

        uuid_re = re.compile(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
        )

        def id_from_filename(name: str) -> Optional[str]:
            match = uuid_re.search(name)
            return match.group(0) if match else None

    paths = []
    for root, _, files in os.walk(tensor_dir):
        for name in files:
            if name.endswith(".pt"):
                paths.append(os.path.join(root, name))
    paths.sort()

    meta = dict(manifest or {})
    meta.setdefault("source_tensor_dir", tensor_dir)
    if max_chunks_per_track:
        meta.setdefault("max_chunks_per_track", max_chunks_per_track)

    tracks = 0
    chunks = 0
    skipped: List[str] = []

    with ChunkStoreWriter(out_root, dim=dim, manifest=meta) as writer:
        for path in paths:
            track_id = id_from_filename(os.path.basename(path))
            if track_id is None:
                skipped.append(f"{path}: no track id in filename")
                continue

            tensor = torch.load(path, map_location="cpu")
            if isinstance(tensor, list):
                tensor = torch.stack(tensor)
            if tensor.dim() == 1:
                tensor = tensor.unsqueeze(0)

            vectors = tensor.float().numpy()
            if vectors.shape[0] == 0:
                skipped.append(f"{path}: zero chunks")
                continue

            if max_chunks_per_track and vectors.shape[0] > max_chunks_per_track:
                pick = np.linspace(
                    0, vectors.shape[0] - 1, max_chunks_per_track
                ).round().astype(int)
                vectors = vectors[pick]

            writer.add(track_id, vectors)
            tracks += 1
            chunks += vectors.shape[0]

    if skipped:
        print(f"Skipped {len(skipped)} files:")
        for line in skipped[:20]:
            print(f"  {line}")

    return (tracks, chunks)
