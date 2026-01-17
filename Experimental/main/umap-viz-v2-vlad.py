import os
import sys
from pathlib import Path
from cuml.decomposition import PCA
import torch
from tqdm import tqdm
import umap
import numpy as np
import pandas as pd
import plotly.express as px
from typing import Dict, List, Literal

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
RESULTS_DIR = ROOT_DIR / "results" / "umap"

from utils import utils
from utils.utils import load_vlad_tensors
from cuml.manifold import UMAP
import cupy as cp

METADATA_CSV_FILE = str(ROOT_DIR / "embeddings" / "id_metadata_arsmagna_test.csv")
VLAD_TENSOR_DIRECTORY = str(ROOT_DIR / "embeddings")

# Output scatter will downsample if > N points to stay responsive
MAX_SCATTER_POINTS = 140_000

def get_js_click_copy():
  return """
  window.onload = function() {
    var plotDiv = document.getElementsByClassName('plotly-graph-div')[0];
    if (plotDiv) {
    plotDiv.on('plotly_click', function(data) {
      if (data.points.length > 0) {
      var textToCopy = data.points[0].customdata[0];
      navigator.clipboard.writeText(textToCopy).then(function() {
        console.log('Copied to clipboard: ' + textToCopy);
      }, function(err) {
        console.error('Could not copy text: ', err);
      });
      }
    });
    console.log("Plotly click-to-copy listener attached.");
    } else {
    console.error('Could not find Plotly graph div to attach click listener.');
    }
  };
  """


def main():

  RESULTS_DIR.mkdir(parents=True, exist_ok=True)

  # -------------------------------------
  # Load CSV metadata
  # -------------------------------------
  # CSV columns: AlbumID,AlbumName,TrackID,TrackName,ArtistName
  metadata_df = pd.read_csv(METADATA_CSV_FILE)
  print(f"Loaded metadata for {len(metadata_df)} items.")

  # Build fast lookup by TrackID
  metadata_df["TrackID"] = metadata_df["TrackID"].astype(str)
  metadata_lookup = metadata_df.set_index("TrackID")

  # -------------------------------------
  # Load vlad embeddings (.npy)
  # -------------------------------------
  vlad_tensors = load_vlad_tensors(VLAD_TENSOR_DIRECTORY, max_workers=16)

  # Extract Track IDs from filenames
  track_ids: List[str] = []
  for name in tqdm(vlad_tensors.keys()):
    track_ids.append(utils.get_uuid_from_filename(name))

  embeddings = np.stack(list(vlad_tensors.values()))

  del vlad_tensors

  # move embeddings to GPU
  embeddings = cp.asarray(embeddings)

  # PCA dim reduction
  pca = PCA(n_components=50, whiten=False)
  pca.fit(embeddings)
  reduced_embeddings = pca.transform(embeddings)

  # -------------------------------------
  # Run UMAP in **2D**
  # -------------------------------------
  print("Running UMAP...")
  reducer = UMAP(
    n_components=4,
    n_neighbors=10,
    min_dist=0.3,
    metric='euclidean',
  )
  umap_embeddings = reducer.fit_transform(reduced_embeddings)

  # -------------------------------------
  # Build DataFrame with metadata merged in
  # -------------------------------------
  print("Building DataFrame...")
  df = pd.DataFrame(umap_embeddings.get(), columns=["UMAP 1", "UMAP 2", "UMAP 3", "UMAP 4"])
  df["TrackID"] = track_ids

  # Join metadata: left join on TrackID
  df = df.join(metadata_lookup, on="TrackID", how="left")

  # -------------------------------------
  # Downsample for the interactive scatter
  # -------------------------------------
  if len(df) > MAX_SCATTER_POINTS:
    print(
      f"Downsampling from {len(df)} → {MAX_SCATTER_POINTS} points "
      "for interactive scatter."
    )
    df_scatter = df.sample(MAX_SCATTER_POINTS, random_state=42)
  else:
    df_scatter = df

  # -------------------------------------
  # Interactive WebGL scatter (2D)
  # -------------------------------------
  print("Rendering scatter plot...")
  # Create a new column to identify ArsMagna artists
  df_scatter["Artist_Group"] = df_scatter["ArtistName"].apply(
    lambda x: "ArsMagna" if pd.notna(x) and "arsmagna" in str(x).lower() else "Other"
  )
  
  fig_scatter = px.scatter_3d(
    df_scatter,
    x="UMAP 1",
    y="UMAP 2",
    z="UMAP 3",
    title=f"UMAP Visualization (VLAD)",
    hover_data=[
      "TrackID",
      "TrackName",
      "ArtistName",
      "AlbumName",
    ],
    custom_data=["TrackID"],
    color="Artist_Group",  # Only color ArsMagna vs Other
    color_discrete_map={"ArsMagna": "#FF0000", "Other": "#CCCCCC"},
    category_orders={"Artist_Group": ["ArsMagna", "Other"]},
  )

  # Set different opacity for ArsMagna vs Other
  for trace in fig_scatter.data:
    if trace.name == "ArsMagna":
      trace.marker.opacity = 0.9
      trace.marker.size = 2
    else:  # Other
      trace.marker.opacity = 0.3
      trace.marker.size = 2
  fig_scatter.update_layout(
    xaxis=dict(visible=False),
    yaxis=dict(visible=False),
  )
  
  fig_scatter.update_layout(
    sliders=[
      dict(
        active=3,
        currentvalue={"prefix": "Marker size: "},
        pad={"t": 30},
        steps=[
          {"label": str(s), "method": "restyle", "args": [{"marker.size": s}]}
          for s in [1,2,3,4,5,6,8,10,12]
        ]
      )
    ]
  )


  scatter_file = str(RESULTS_DIR / "umap_vlad_scatter.html")
  print(f"Saving scatter → {scatter_file}")
  fig_scatter.write_html(
    scatter_file,
    include_plotlyjs="cdn",
    full_html=True,
    post_script=get_js_click_copy(),
  )

  # -------------------------------------
  # Density heatmap for the entire dataset
  # -------------------------------------
  print("Rendering density heatmap...")
  fig_density = px.density_heatmap(
    df,
    x="UMAP 1",
    y="UMAP 2",
    nbinsx=300,
    nbinsy=300,
    title=f"UMAP Density (VLAD)",
    color_continuous_scale="Viridis",
  )
  fig_density.update_layout(
    xaxis=dict(visible=False),
    yaxis=dict(visible=False),
  )

  density_file = str(RESULTS_DIR / "umap_vlad_density.html")
  print(f"Saving density → {density_file}")
  fig_density.write_html(
    density_file,
    include_plotlyjs="cdn",
    full_html=True,
  )


if __name__ == "__main__":
  main()
