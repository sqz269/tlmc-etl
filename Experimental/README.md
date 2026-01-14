# Experimental Code for Recommender Systems

This folder contains code for recommender experiments

## Blog Entries
### [Shining Needle in a 4TB Haystack: Recommending Music from the Touhou Lossless Music Collection (Pt. 1)](https://blog.sqz269.me/2025/11/03/tlmc-rec-01.html)

## Usage

To get started, ensure you have uv and conda installed

### MERT

1. To run MERT experiments, change your directory into `Experimental/` and run `uv sync`.
2. Edit `mert_batched.py`, `DATA_DIRECTORY` variable to set a dictory of flac files.
3. Run `uv run mert_batched.py` to generate embeddings


### Visualization

1. After generating embeddings
