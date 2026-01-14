from json import load
import numpy as np
from cuml.cluster import HDBSCAN
from sklearn.metrics import silhouette_score, davies_bouldin_score
from sklearn.preprocessing import normalize
import torch
from utils import utils
from utils.utils import load_tensor

TENSOR_DIRECTORY = "embeddings/uuid_embeddings/"
tensors = load_tensor(TENSOR_DIRECTORY, num_workers=16)


pool_modes = ["mean", "mean+max"]
for mode in pool_modes:
  print(f"Evaluating embeddings with pooling mode: {mode}")
  all_embeddings = utils.pool_loaded_tensor_dict(
    tensors=tensors, mode=mode
  )

  embeddings_torch = torch.stack(list(all_embeddings.values())).cuda()
  embeddings_norm = torch.nn.functional.normalize(embeddings_torch, p=2, dim=1)

  print("Clustering")
  hdbscan_clusterer = HDBSCAN(min_cluster_size=5, metric="euclidean")
  cluster_labels = hdbscan_clusterer.fit_predict(embeddings_norm)

  labels_np = cluster_labels.get() if hasattr(cluster_labels, 'get') else cluster_labels
  unique_clusters = np.unique(labels_np)
  print("Clusters: ", unique_clusters)

  # Filter out noise (-1) for scoring
  mask = labels_np != -1

  if len(set(labels_np[mask])) > 1:
    # Move masked embeddings to CPU for Sklearn metrics 
    # (Warning: Sklearn silhouette_score is O(N^2) and slow for 138k points)
    embeddings_cpu = embeddings_norm[mask].cpu().numpy()
    filtered_labels = labels_np[mask]

    silhouette_avg = silhouette_score(embeddings_cpu, filtered_labels)
    davies_bouldin_avg = davies_bouldin_score(embeddings_cpu, filtered_labels)

    print(f"Silhouette Score: {silhouette_avg:.4f}")
    print(f"Davies-Bouldin Score: {davies_bouldin_avg:.4f}")