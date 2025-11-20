# Music Vector Web Demo

This is a Dash application for exploring music embeddings. It is containerized for easy deployment to Google Cloud Run.

## Prerequisites

- [Docker](https://www.docker.com/) installed.
- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) installed (for deployment).
- `gunicorn` is used as the production WSGI server.

## Local Development & Testing

1.  **Prepare Data**:
    Run the helper script to copy necessary data files (embeddings, vector index, UMAP data) from the parent directory into `webdemo/`:
    ```powershell
    cd webdemo
    .\prepare_deploy.ps1
    ```

2.  **Build Docker Image**:
    ```bash
    docker build -t music-vector-app .
    ```

3.  **Run Container**:
    ```bash
    docker run -p 8080:8080 -e PORT=8080 music-vector-app
    ```
    Access the app at [http://localhost:8080](http://localhost:8080).

## Deployment to Google Cloud Run

1.  **Prepare Data** (if not already done):
    ```powershell
    .\prepare_deploy.ps1
    ```

2.  **Deploy**:
    This command builds the image in the cloud and deploys it directly. Replace `[YOUR_PROJECT_ID]` with your Google Cloud project ID.
    ```bash
    gcloud run deploy music-vector-app --source . --project [YOUR_PROJECT_ID] --allow-unauthenticated
    ```

    *Alternatively, if you want to build locally and push:*
    ```bash
    gcloud builds submit --tag gcr.io/[YOUR_PROJECT_ID]/music-vector-app
    gcloud run deploy music-vector-app --image gcr.io/[YOUR_PROJECT_ID]/music-vector-app --platform managed
    ```

