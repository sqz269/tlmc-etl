from json import load
import numpy as np
import hdbscan
from sklearn.metrics import silhouette_score, davies_bouldin_score
from utils.utils import load_embeddings

pool_modes = ["mean", "mean+max"]
for mode in pool_modes:
  print(f"Evaluating embeddings with pooling mode: {mode}")
  all_embeddings = load_embeddings(pool_mode=mode) # type: ignore

  hdbscan_clusterer = hdbscan.HDBSCAN(min_cluster_size=5)
  cluster_labels = hdbscan_clusterer.fit_predict(all_embeddings.numpy())

  print("Clusters: ", np.unique(cluster_labels))

  if len(set(cluster_labels)) > 1:
    cluster_stability = hdbscan_clusterer.cluster_persistence_

    mask = cluster_labels != -1
    silhouette_avg = silhouette_score(all_embeddings.numpy()[mask], cluster_labels[mask])

    davies_bouldin_avg = davies_bouldin_score(all_embeddings.numpy()[mask], cluster_labels[mask])

    print(f"Cluster Stability: {cluster_stability}")
    print(f"Silhouette Score: {silhouette_avg}")
    print(f"Davies-Bouldin Score: {davies_bouldin_avg}")
