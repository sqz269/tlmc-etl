import os
import torch
import umap
import numpy as np
import pandas as pd
import plotly.express as px
from typing import Dict

# 1. This is your provided function
def load_tensor(dir: str) -> Dict[str, torch.Tensor]:
  """Loads all .pt files from a directory into a dictionary."""
  tensors: Dict[str, torch.Tensor] = {}
  for file in os.listdir(dir):
    if file.endswith(".pt"):
      try:
        tensor = torch.load(os.path.join(dir, file))
        tensors[file] = tensor
      except Exception as e:
        print(f"Could not load {file}: {e}")
  return tensors

if __name__ == "__main__":
  # --- 1. Load Tensors ---
  TENSOR_DIRECTORY = "embeddings/mean"  # Update this path as needed
  
  print(f"Loading tensors from {TENSOR_DIRECTORY}...")
  tensors_dict = load_tensor(TENSOR_DIRECTORY)

  if not tensors_dict:
    print("No .pt files found in the directory. Exiting.")
    exit()

  # --- 2. Prepare Data for UMAP (with Genre Parsing) ---
  
  # Get all the original .pt filenames
  original_labels = list(tensors_dict.keys())
  
  genres = []
  cleaned_filenames = []
  
  print("Parsing genres from filenames...")
  for label in original_labels:
    try:
      # Assumes format "[{genre}] - {filename}.pt"
      genre_part, filename_part = label.split('] - ', 1)
      genre = genre_part[1:]  # Remove the leading '['
      
      genres.append(genre)
      cleaned_filenames.append(filename_part)
    except ValueError:
      # File doesn't match the expected format
      genres.append('Unknown')  # Assign a default category
      cleaned_filenames.append(label) # Use the original filename
          
  # Stack tensors into a single (n_samples, n_features) array
  data_tensors = torch.stack(list(tensors_dict.values()))
  print(f"Data stacked into shape: {data_tensors.shape}")
  data_numpy = data_tensors.detach().cpu().numpy()

  # --- 3. Run UMAP ---
  print("Running UMAP dimensionality reduction (to 3D)...")
  reducer = umap.UMAP(n_components=3, random_state=42)
  embedding = reducer.fit_transform(data_numpy)
  print(f"UMAP embedding created with shape: {embedding.shape}")

  # --- 4. Plot Results (with Plotly and Color) ---
  print("Plotting results with Plotly...")
  
  # Create a DataFrame to hold all our data
  df = pd.DataFrame(embedding, columns=['UMAP 1', 'UMAP 2', 'UMAP 3'])
  df['filename'] = cleaned_filenames  # Use the cleaned filename
  df['genre'] = genres               # Add the new genre column
  
  
  # Create the 3D scatter plot
  fig = px.scatter_3d(
    df,
    x='UMAP 1',
    y='UMAP 2',
    z='UMAP 3',
    title="3D UMAP Projection by Genre",
    color='genre',         # <-- This is the magic!
    hover_name='filename', # <-- Show filename on hover
    hover_data=['genre']   # <-- Also show genre in the hover tooltip
  )

  # Optional: Make markers smaller
  fig.update_traces(marker=dict(size=2))
  
  # Show the interactive plot
  # This will open in your browser or notebook
  fig.show()

  fig.write_html("plot.html")
