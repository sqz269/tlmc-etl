# Setup instructions (WSL/Linux Needed):

1. Install miniconda: https://www.anaconda.com/docs/getting-started/miniconda/install


2. Run commands from Jukebox readme

  ```
  conda create --name jukebox python=3.7.5
  conda activate jukebox
  conda install mpi4py=3.0.3 # if this fails, try: pip install mpi4py==3.0.3
  conda install pytorch=1.4 torchvision=0.5 cudatoolkit=10.0 -c pytorch

  cd jukebox
  pip install -r requirements.txt
  pip install -e .
  ```

3. Install additional packages:

  ```
  pip install wget
  pip install accelerate
  pip install importlib-metadata
  ```
4. Download weights from and store it in a folder
   1. https://openaipublic.azureedge.net/jukebox/models/5b/vqvae.pth.tar
   2. https://openaipublic.azureedge.net/jukebox/models/5b/prior_level_2.pth.tar
5. Update `infernece.py`'s `VQVAE_CACHE_PATH` and `PRIOR_CACHE_PATH`