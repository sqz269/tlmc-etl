import os
import sys
from pathlib import Path
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
from utils.utils import load_tensor

TENSOR_DIRECTORY = str(ROOT_DIR / "embeddings" / "chunks")
POOLING_POLICY: List[Literal["mean", "max", "mean+max"]] = ["mean", "mean+max"]

genre_artist_color_map = {
  "genre_eurobeat": "#FF4500",           # OrangeRed
  "genre_ambient": "#8A2BE2",            # BlueViolet
  "genre_classical": "#3CB371",          # MediumSeaGreen
  "genre_metal": "#B22222",              # FireBrick
  "genre_fantasy": "#DAA520",            # GoldenRod
  "artist_iron_attack": "#4682B4",       # SteelBlue
  "genre_jazz": "#D8BFD8",               # Thistle (lighter purple)
  "artist_foreground_eclipse": "#5F9EA0", # CadetBlue
  "artist_彩音": "#CD5C5C",               # IndianRed
  "genre_bossa_nova": "#6B8E23",         # OliveDrab
  "artist_get_in_the_ring": "#FFD700",   # Gold
  "genre_jpop": "#BA55D3",               # MediumOrchid
  "artist_rd_sounds": "#20B2AA",         # LightSeaGreen
  "artist_zytokine": "#7B68EE",          # MediumSlateBlue
  "artist_arsmagna": "#8B4513"           # SaddleBrown
}

def get_js_click_copy():
  return """
  window.onload = function() {
    // Find the Plotly graph div (there's typically only one)
    var plotDiv = document.getElementsByClassName('plotly-graph-div')[0];
    
    if (plotDiv) {
      // Attach the click event listener
      plotDiv.on('plotly_click', function(data) {
        if (data.points.length > 0) {
          // Get the 'customdata' we added in Python
          // data.points[0].customdata[0] corresponds to the 
          // first item in our list: ['filename']
          var textToCopy = data.points[0].customdata[0];
          
          // Use the modern clipboard API
          navigator.clipboard.writeText(textToCopy).then(function() {
            // Optional: Provide feedback to the user
            console.log('Copied to clipboard: ' + textToCopy);
            // You could create a small "Copied!" popup here if desired
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
  tensors = load_tensor(TENSOR_DIRECTORY)
  if not tensors:
    print("No .pt files found in the directory. Exiting.")
    return
  
  for pooling_policy in POOLING_POLICY:
    print(f"Generating UMAP visualization with pooling policy: {pooling_policy}")
    
    pooled_tensors = utils.pool_loaded_tensor_dict(tensors=tensors, mode=pooling_policy)

    tags: List[str] = []
    cleaned_filenames: List[str] = []
    for name in tqdm(pooled_tensors.keys()):
      tag_part, filename_part = utils.get_tag_and_filename(name)
      tags.append(tag_part)
      cleaned_filenames.append(filename_part)
      
    embeddings = torch.stack(list(pooled_tensors.values())).numpy()
    print("Running UMAP dimensionality reduction...")
    reducer = umap.UMAP(n_components=3, min_dist=0.1, metric='cosine', random_state=42)
    umap_embeddings = reducer.fit_transform(embeddings)
    
    print("Preparing DataFrame for visualization...")
    df = pd.DataFrame(umap_embeddings, columns=['UMAP 1', 'UMAP 2', 'UMAP 3'])
    df['Tag'] = tags
    df['Filename'] = cleaned_filenames
    
    fig = px.scatter_3d(
      df,
      x='UMAP 1',
      y='UMAP 2',
      z='UMAP 3',
      title=f'UMAP Tensor Visualization ({pooling_policy})',
      color='Tag',
      color_discrete_map=genre_artist_color_map,
      hover_data=['Filename'],
      custom_data=['Filename']
    )
    
    fig.update_traces(marker=dict(size=2))
    
    # show
    # fig.show()
    
    html_file = str(RESULTS_DIR / f"umap_viz_{pooling_policy}.html")
    print(f"Saving visualization to {html_file}...")
    fig.write_html(html_file, include_plotlyjs='cdn', full_html=True, post_script=get_js_click_copy())

if __name__ == "__main__":
  main()