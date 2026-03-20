# Experimental Code for Recommender Systems

This folder contains code for the TLMC music recommendation experiments.

## Blog Entries

1. [Shining Needle in a 4TB Haystack: Recommending Music from the Touhou Lossless Music Collection (Pt. 1)](https://blog.sqz269.me/2025/11/03/tlmc-rec-01.html)
2. [Pt. 2: Evaluating Embedding Quality](https://blog.sqz269.me/2025/11/11/tlmc-rec-02.html)
3. [Pt. 3: Exploring the Embedding Space](https://blog.sqz269.me/2026/01/11/tlmc-rec-03.html)

## Directory Layout

```
Experimental/
├── scripts/                # Runnable entrypoints
│   ├── mert_batched.py         # Batch MERT embedding generation (genre-tagged)
│   ├── mert_batched_uuid.py    # Batch MERT embedding generation (UUID-keyed, 6s chunks)
│   ├── mert_single.py          # Single-file MERT embedding generation
│   ├── colbert_idx_builder.py  # Build ColBERT chunk-level index
│   ├── make_embeddings.py      # Push-ready embedding generation
│   ├── assign_artist_uuids.py  # One-off UUID assignment for artist test sets
│   ├── cluster_eval.py         # Cluster evaluation metrics
│   ├── umap-visualization.py   # UMAP visualization (v1)
│   ├── umap_viz_v2.py          # UMAP visualization (v2, mean/max pooling)
│   └── umap-viz-v2-vlad.py     # UMAP visualization (v2, VLAD pooling)
├── notebooks/              # Jupyter notebooks
│   ├── nb-colbert.ipynb        # ColBERT retrieval experiments
│   ├── nb-ann-faiss-builder.ipynb  # ANN/FAISS index building
│   ├── nb-pool-vlad.ipynb      # VLAD pooling experiments
│   ├── nb-sim-centroid.ipynb   # Centroid similarity analysis
│   ├── nb-sim-eval.ipynb       # Similarity evaluation
│   ├── nb-sim-vari-testset.ipynb   # Variable test set similarity
│   └── nb-sim-vlad.ipynb       # VLAD similarity experiments
├── utils/                  # Shared utilities
│   ├── loader.py               # Audio loading, chunking, SourceFileInfo
│   ├── utils.py                # Tensor I/O, pooling, file helpers
│   └── data_utils.py           # Metadata loading helpers
├── vector_search/          # Vector index building & search
│   ├── vector_search.py            # Annoy-based vector search
│   ├── vector_search_build_index.py        # Build Annoy index (mean pooled)
│   ├── vector_search_build_chunked_index.py  # Build Annoy index (chunked)
│   ├── vector-search-build-index-vlad.py   # Build Annoy index (VLAD)
│   ├── faiss_index_builder.py       # Build FAISS IVF+PQ index
│   ├── faiss_index_search.py        # FAISS search utilities
│   └── umap-preprocessor.py        # UMAP data preprocessing
├── experiments/            # Standalone experiment scripts (untracked)
├── data_transfer/          # Utilities for archiving & uploading data
├── jukeboxmir/             # Vendored Jukebox-MIR dependency
├── webdemo/                # Streamlit web demo (Docker-deployable)
├── fonts/                  # Fonts for visualization
├── notes/                  # Blog post drafts (gitignored)
├── pyproject.toml
└── uv.lock
```

## Usage

### Prerequisites

- [uv](https://docs.astral.sh/uv/) for Python dependency management
- CUDA-capable GPU recommended for MERT inference

### Setup

```bash
cd Experimental/
uv sync
```

### Generate Embeddings

```bash
# Single file
uv run scripts/mert_single.py path/to/track.flac output/

# Batch (UUID-keyed, 6s chunks)
# Edit DATA_DIRECTORY and EMBEDDING_DIRECTORY in the script first
uv run scripts/mert_batched_uuid.py
```

### Visualization

After generating embeddings, run the UMAP visualization:

```bash
uv run scripts/umap_viz_v2.py
```
