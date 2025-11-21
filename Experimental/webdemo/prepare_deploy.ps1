Write-Host "Preparing webdemo directory for Docker build..."

# Define source paths (relative to webdemo/)
$SourceEmbeddingsCsv = "../embeddings/id_metadata.csv"
$SourceVectorIndex = "../vector_index"
$SourceUmap = "../umap_data_mean.csv"
$SourceUmapMax = "../umap_data_mean+max.csv"

# Check if sources exist
if (-not (Test-Path $SourceEmbeddingsCsv)) { Write-Error "Embeddings CSV not found at $SourceEmbeddingsCsv"; exit 1 }
if (-not (Test-Path $SourceVectorIndex)) { Write-Error "Vector index folder not found at $SourceVectorIndex"; exit 1 }
if (-not (Test-Path $SourceUmap)) { Write-Error "UMAP CSV not found at $SourceUmap"; exit 1 }

# Copy items
Write-Host "Copying embeddings/id_metadata.csv..."
if (Test-Path "embeddings") { Remove-Item -Recurse -Force "embeddings" }
New-Item -ItemType Directory -Force -Path "embeddings" | Out-Null
Copy-Item -Force -Path $SourceEmbeddingsCsv -Destination "embeddings/"

Write-Host "Copying vector_index..."
if (Test-Path "vector_index") { Remove-Item -Recurse -Force "vector_index" }
Copy-Item -Recurse -Force -Path $SourceVectorIndex -Destination .

Write-Host "Copying umap_data_mean.csv..."
Copy-Item -Force -Path $SourceUmap -Destination .

Write-Host "Copying umap_data_mean+max.csv..."
Copy-Item -Force -Path $SourceUmapMax -Destination .

Write-Host "Ready to build! Run: docker build -t music-vector-app ."
