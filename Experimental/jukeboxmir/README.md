Setup instructions:

1. Install miniconda: https://www.anaconda.com/docs/getting-started/miniconda/install

Run commands from Jukebox readme

```
conda install mpi4py=3.0.3 # if this fails, try: pip install mpi4py==3.0.3
conda install pytorch=1.4 torchvision=0.5 cudatoolkit=10.0 -c pytorch

cd jukebox
pip install -r requirements.txt
pip install -e .
```

Install additional packages:

```
pip install wget
pip install accelerate
pip install importlib-metadata
```
