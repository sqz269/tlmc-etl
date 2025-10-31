import numpy as np
import torch
from loader import load_flac
import mert

def main():
    flac, sr = load_flac("data/(01) [二羽凛奈，朔間咲] 明日世界をなくしても.flac")
    # split it into 20 second overlapping chunks
    # with 5 seconds overlap
    chunk_size = sr * 20
    overlap = sr * 5
    step = chunk_size - overlap
    chunks = []
    for start in range(0, len(flac), step):
        end = start + chunk_size
        chunk = flac[start:end]
        if len(chunk) < chunk_size:
            break
        chunks.append(chunk)
    print(f"Total chunks: {len(chunks)}")

    embeddings = []
    for i, chunk in enumerate(chunks):
        emb = mert.embed_waveform(chunk, sr, layer_mix="last4")
        embeddings.append(emb)
        print(f"Chunk {i+1}/{len(chunks)} embedded.")

    embeddings = np.stack(embeddings)
    
    # pooling
    final_mean_embedding = np.mean(embeddings, axis=0)
    final_max_embedding = np.max(embeddings, axis=0)
    final_hybrid_embedding = np.concatenate((final_mean_embedding, final_max_embedding))

    print("Final Mean Embedding Shape:", final_mean_embedding.shape)
    print("Final Max Embedding Shape:", final_max_embedding.shape)
    print("Final Hybrid Embedding Shape:", final_hybrid_embedding.shape)

if __name__ == "__main__":
    main()
