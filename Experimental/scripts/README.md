# `scripts/` — Experiment entrypoints

This folder contains **runnable entrypoints** (not library code). Most scripts rely on the repo’s shared utilities in `utils/` and loaders in `utils/loader.py`.

## How to run

From the `Experimental/` directory:

```bash
uv sync
uv run scripts/<script_name>.py
```

Most scripts have configuration at the top of the file (e.g. `DATA_DIRECTORY`, `EMBEDDING_DIRECTORY`, `POOLING_POLICY`).

## Outputs & conventions

- **Embeddings**
  - Chunk-level MERT embeddings: `embeddings/chunks/*.allchunks.pt`
  - UUID-keyed embeddings (test pipeline): `embeddings/test/*.allchunks.pt`
  - Pre-pooled/other artifacts may live under `embeddings/uuid_embeddings/` depending on the pipeline you ran.
- **UMAP outputs**
  - Generated plots and CSVs are written to `results/umap/`

---

## Scripts

### `mert_batched.py`

- **Purpose**: Run the MERT model over audio, chunking each track and writing **chunk embeddings** to disk.
- **Inputs**:
  - Audio tree under `DATA_DIRECTORY` (default: `data/`).
  - Uses `loader.load_flac(...)` and `utils.utils.get_process_list(...)` to enumerate files and chunk them.
- **Outputs**:
  - Writes `*.allchunks.pt` tensors into `embeddings/chunks/`
    - Filename format: `"[{tag}] - {filename}.allchunks.pt"`
- **Notes**:
  - Uses `"m-a-p/MERT-v1-330M"` from HuggingFace.
  - Designed for GPU but can run on CPU (slow).
- **Run**:

```bash
uv run scripts/mert_batched.py
```

### `mert_batched_uuid.py`

- **Purpose**: Similar to `mert_batched.py`, but geared toward **UUID-named `.m4a` inputs** and incremental processing.
- **Inputs**:
  - Scans `DATA_DIRECTORY` (default: `data/`) for `.m4a`.
  - Extracts a UUID from the filename and skips items that already have a `*.pt` in `EMBEDDING_DIRECTORY`.
- **Outputs**:
  - Writes `*.allchunks.pt` into `embeddings/test/` (default).
- **Notes**:
  - Uses `loader.load_m4a(...)` which converts to a temporary FLAC then reuses the FLAC loader.
  - Uses multiprocessing (`spawn`) and a small threadpool for async saving.
- **Run**:

```bash
uv run scripts/mert_batched_uuid.py
```

### `cluster_eval.py`

- **Purpose**: Quick clustering sanity-check for embeddings using **HDBSCAN** and prints cluster metrics.
- **Inputs**:
  - Loads tensors from `embeddings/uuid_embeddings/` via `utils.utils.load_tensor(...)`.
  - Pools embeddings using `utils.pool_loaded_tensor_dict(...)` for modes `mean` and `mean+max`.
- **Outputs**:
  - Console output: cluster IDs + silhouette score and Davies–Bouldin score (when valid).
- **Notes**:
  - Requires GPU for the current implementation (`.cuda()`).
  - Silhouette score can be very expensive on large N (comment warns about \(O(N^2)\)).
- **Run**:

```bash
uv run scripts/cluster_eval.py
```

### `umap-visualization.py`

- **Purpose**: Generate a 3D UMAP visualization over **chunk embeddings** (from `embeddings/chunks/`), colored by dataset tag.
- **Inputs**:
  - Loads `embeddings/chunks/` tensors.
  - Pools using `mean` and `mean+max`.
- **Outputs**:
  - Writes interactive Plotly HTML to `results/umap/`:
    - `umap_viz_mean.html`
    - `umap_viz_mean+max.html`
- **Run**:

```bash
uv run scripts/umap-visualization.py
```

### `umap-viz-v2.py`

- **Purpose**: Generate UMAP + Plotly plots over **UUID embeddings**, joined against metadata.
- **Inputs**:
  - Metadata CSV: `embeddings/id_metadata_arsmagna_test.csv`
  - Tensors: `embeddings/uuid_embeddings/`
- **Outputs** (written to `results/umap/`):
  - Scatter: `umap_<policy>_scatter.html`
  - Density: `umap_<policy>_density.html`
  - Policies currently: `mean`, `mean+max`
- **Run**:

```bash
uv run scripts/umap-viz-v2.py
```

### `umap-viz-v2-vlad.py`

- **Purpose**: Generate UMAP + Plotly plots over **VLAD embeddings**, with PCA dimensionality reduction on GPU.
- **Inputs**:
  - Metadata CSV: `embeddings/id_metadata_arsmagna_test.csv`
  - VLAD tensors: `embeddings/` (loaded via `utils.utils.load_vlad_tensors(...)`)
- **Outputs** (written to `results/umap/`):
  - `umap_vlad_scatter.html`
  - `umap_vlad_density.html`
- **Notes**:
  - Uses RAPIDS cuML `PCA` + `UMAP` and CuPy arrays; needs a working CUDA/RAPIDS stack.
- **Run**:

```bash
uv run scripts/umap-viz-v2-vlad.py
```

---

## Related runnable scripts (in `vector_search/`)

These are also “entrypoint-style” scripts, just grouped by feature rather than by “experiments”.

### `vector_search/umap-preprocessor.py`

- **Purpose**: Build a `umap_data_<policy>.csv` used by the Dash demo in `webdemo/`.
- **Output**:
  - Writes to `results/umap/umap_data_<POOLING_POLICY>.csv`
- **Run**:

```bash
uv run vector_search/umap-preprocessor.py
```

### `vector_search/vector-search-build-index.py`

- **Purpose**: Build Annoy indices for pooled MERT embeddings (`mean`, `mean+max`).
- **Outputs** (under `vector_index/`):
  - `annoy_index_<policy>.ann`
  - `annoy_int_index_to_uuid_<policy>.csv`
- **Run**:

```bash
uv run vector_search/vector-search-build-index.py
```

### `vector_search/vector-search-build-index-vlad.py`

- **Purpose**: Build an Annoy index over PCA-reduced VLAD embeddings.
- **Outputs** (under `vector_index/`):
  - `annoy_index_vlad_pca_<N>.ann`
  - `annoy_int_index_to_uuid_vlad_pca_<N>.csv`
- **Run**:

```bash
uv run vector_search/vector-search-build-index-vlad.py
```

### `vector_search/vector-search.py`

- **Purpose**: Interactive CLI to query nearest neighbors from an existing Annoy index.
- **Run**:

```bash
uv run vector_search/vector-search.py
```


