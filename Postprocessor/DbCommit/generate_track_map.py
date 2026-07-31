"""Projects the pooled MERT embeddings onto a 2D map for the explore point cloud.

The backend stores one pooled vector per track (track_embedding.embedding_mean,
vector(1024), provenance in embedding_config). This stage flattens that space
into screen coordinates once, offline, so the frontend can draw the whole
library as a WebGL scatterplot without ever touching the 1024-dim vectors:

  l2-normalize -> PCA(100) -> UMAP(2d, cosine) + k-means cluster labels

Clusters come from k-means over the PCA features, not density over the layout:
the layout is one connected continent (HDBSCAN finds either ~3 regions or
shatters into noise), while k-means always yields k acoustic families that
project onto the map as contiguous colored regions. Labels are relabeled by
descending cluster size. They exist to color the map into nameable regions,
not to be authoritative genres.

Reads track_embeddings.csv, exported from the DB first:

  COPY (
    SELECT track_id, embedding_mean::text FROM track_embedding
  ) TO STDOUT WITH CSV

Produces track_map.csv (track_id, x, y, cluster) with x/y scaled to [-0.95,
0.95] preserving aspect ratio — regl-scatterplot's normalized device space —
applied by apply_track_map.sql into the backend-owned track_map table.

Run with the heavy deps injected (umap-learn brings scikit-learn):

  uv run --with umap-learn python generate_track_map.py
"""

import csv
import sys
import time

import numpy as np

INPUT_CSV = "track_embeddings.csv"
OUTPUT_CSV = "track_map.csv"

PCA_DIMS = 100
UMAP_NEIGHBORS = 50
UMAP_MIN_DIST = 0.1
# Enough families that each is one kind of sound, few enough that a categorical
# palette and a future naming pass stay tractable.
KMEANS_CLUSTERS = 48


def load_embeddings():
  ids, rows = [], []
  with open(INPUT_CSV, newline="") as f:
    for track_id, vec_text in csv.reader(f):
      ids.append(track_id)
      rows.append(np.fromstring(vec_text[1:-1], dtype=np.float32, sep=","))
  return ids, np.vstack(rows)


def main():
  t0 = time.time()
  print("Loading embeddings...")
  ids, embeddings = load_embeddings()
  print(f"  {len(ids)} tracks, dim {embeddings.shape[1]}, {time.time() - t0:.0f}s")

  from sklearn.cluster import KMeans
  from sklearn.decomposition import PCA
  from umap import UMAP

  norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
  embeddings /= np.maximum(norms, 1e-12)

  print(f"PCA -> {PCA_DIMS} dims...")
  reduced = PCA(n_components=PCA_DIMS, svd_solver="randomized").fit_transform(
    embeddings
  )
  del embeddings

  # No random_state on purpose: setting one forces single-threaded layout.
  print("UMAP -> 2d (this is the long part)...")
  coords = UMAP(
    n_components=2,
    n_neighbors=UMAP_NEIGHBORS,
    min_dist=UMAP_MIN_DIST,
    metric="cosine",
    verbose=True,
  ).fit_transform(reduced)
  print(f"  done at {time.time() - t0:.0f}s")

  print(f"k-means ({KMEANS_CLUSTERS}) over the PCA features...")
  raw_labels = KMeans(n_clusters=KMEANS_CLUSTERS, n_init=4).fit_predict(reduced)
  by_size = np.argsort(-np.bincount(raw_labels, minlength=KMEANS_CLUSTERS))
  relabel = np.empty(KMEANS_CLUSTERS, dtype=np.int64)
  relabel[by_size] = np.arange(KMEANS_CLUSTERS)
  labels = relabel[raw_labels]
  sizes = np.bincount(labels)
  print(f"  sizes: largest {sizes[0]}, smallest {sizes[-1]}")

  # A handful of stray points otherwise dictate the frame and shove the dense
  # continent off-center: clamp to the 0.1..99.9 percentile box first (strays
  # pin to the edge instead of stretching it). Then center and scale both axes
  # by the same factor: aspect ratio is signal.
  lo, hi = np.percentile(coords, [0.1, 99.9], axis=0)
  coords = np.clip(coords, lo, hi)
  coords -= (coords.min(axis=0) + coords.max(axis=0)) / 2
  coords *= 0.95 / np.abs(coords).max()

  with open(OUTPUT_CSV, "w", newline="") as f:
    writer = csv.writer(f)
    for track_id, (x, y), label in zip(ids, coords, labels):
      writer.writerow([track_id, f"{x:.5f}", f"{y:.5f}", int(label)])
  print(f"Wrote {OUTPUT_CSV} ({len(ids)} rows) in {time.time() - t0:.0f}s total")


if __name__ == "__main__":
  sys.exit(main())
