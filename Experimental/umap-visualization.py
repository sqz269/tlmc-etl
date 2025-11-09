import os
import torch
from tqdm import tqdm
import umap
import numpy as np
import pandas as pd
import plotly.express as px
from typing import Dict, List

from utils import utils
from utils.utils import load_tensor

TENSOR_DIRECTORY = f"embeddings/chunks/"
POOLING_POLICY = "mean"

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
  <script>
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
  </script>
  """

def main():
  tensors = load_tensor(TENSOR_DIRECTORY)
  if not tensors:
    print("No .pt files found in the directory. Exiting.")
    return
  
  utils.pool_loaded_tensor_dict(tensors, mode=POOLING_POLICY)

  tags: List[str] = []
  cleaned_filenames: List[str] = []
  for name in tqdm(tensors.keys()):
    tag_part, filename_part = utils.get_tag_and_filename(name)
    tags.append(tag_part)
    cleaned_filenames.append(filename_part)
    
  embeddings = torch.stack(list(tensors.values())).numpy()
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
    title=f'UMAP Tensor Visualization ({POOLING_POLICY})',
    color='Tag',
    color_discrete_map=genre_artist_color_map,
    hover_data=['Filename'],
    custom_data=['Filename']
  )
  
  fig.update_traces(marker=dict(size=2))
  
  # show
  fig.show()
  
  html_file = f"umap_viz_{POOLING_POLICY}.html"
  print(f"Saving visualization to {html_file}...")
  fig.write_html(html_file, include_plotlyjs='cdn', full_html=True)

if __name__ == "__main__":
  main()