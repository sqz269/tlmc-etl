import os
import torch
import umap
import numpy as np
import pandas as pd
import plotly.express as px
from typing import Dict

from utils.utils import load_tensor

# 1. This is your provided function

if __name__ == "__main__":
  # --- 1. Load Tensors ---
  POOLING_POLICY = "mean"
  TENSOR_DIRECTORY = f"embeddings/{POOLING_POLICY}"  # Update this path as needed
  
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
  df['genre'] = genres              # Add the new genre column
  
  
  # Create the 3D scatter plot
  fig = px.scatter_3d(
    df,
    x='UMAP 1',
    y='UMAP 2',
    z='UMAP 3',
    title=f"MERT Tensor UMAP Projection ({POOLING_POLICY})", # Updated title
    color='genre',           
    hover_name='filename', 
    hover_data=['genre'],
    custom_data=['filename']  # <-- **THIS IS THE KEY ADDITION**
  )

  # Optional: Make markers smaller
  fig.update_traces(marker=dict(size=2))
  
  # --- 5. Save HTML and Inject Click-to-Copy JavaScript ---
  
  HTML_FILE = f"plt-{POOLING_POLICY}.html"
  print(f"Writing base HTML to {HTML_FILE}...")
  # Use 'cdn' to keep the HTML file smaller (loads plotly.js from web)
  fig.write_html(HTML_FILE, include_plotlyjs='cdn')

  # Define the JavaScript to inject
  # This script waits for the plot to load, then adds a click listener
  js_script = """
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

  print(f"Injecting click-to-copy JavaScript into {HTML_FILE}...")
  
  # Read the generated HTML file
  with open(HTML_FILE, 'r', encoding='utf-8') as f:
    html_content = f.read()

  # Inject the JavaScript right before the closing </body> tag
  # This ensures the rest of the page/scripts are loaded first
  html_content = html_content.replace('</body>', js_script + '\\n</body>')

  # Write the modified HTML back to the file
  with open(HTML_FILE, 'w', encoding='utf-8') as f:
    f.write(html_content)

  print(f"Done! Open {HTML_FILE} in your browser to test.")

  # We comment this out, as it will open the *original* plot
  # without our new JavaScript.
  # fig.show()