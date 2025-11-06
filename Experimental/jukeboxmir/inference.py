#@title Set up hyperparameters + download model weights
gdrive_cache_dir = "drive/Shareddrives/Jukemir" #@param {type:"string"}
cache_gdrive = False #@param {type:"boolean"}

import os
import shutil
from pathlib import Path
from typing import Dict, List, Set, Tuple

CHUNKING_OVERLAP_SEC = 5

VQVAE_CACHE_PATH = '/home/sqz269/jukbox-cache/models/5b/vqvae.pth.tar'
PRIOR_CACHE_PATH = '/home/sqz269/jukbox-cache/models/5b/prior_level_2.pth.tar'

# imports and set up Jukebox's multi-GPU parallelization
import jukebox
from jukebox.hparams import Hyperparams, setup_hparams
from jukebox.make_models import MODELS, make_prior, make_vqvae
from jukebox.utils.dist_utils import setup_dist_from_mpi
from tqdm import tqdm

from accelerate import init_empty_weights

cache_gdrive = True

# Set up MPI
rank, local_rank, device = setup_dist_from_mpi()

# Set up VQVAE
model = "5b"  # or "1b_lyrics"
hps = Hyperparams()
hps.sr = 44100
hps.n_samples = 3 if model == "5b_lyrics" else 8
hps.name = "samples"
chunk_size = 16 if model == "5b_lyrics" else 32
max_batch_size = 3 if model == "5b_lyrics" else 16
hps.levels = 3
hps.hop_fraction = [0.5, 0.5, 0.125]
vqvae, *priors = MODELS[model]

hparams = setup_hparams(vqvae, dict(sample_length=1048576))

if cache_gdrive:
    hparams.restore_vqvae = VQVAE_CACHE_PATH

# don't actually load any weights in yet,
# leave it for later. memory optimization
with init_empty_weights():
    vqvae = make_vqvae(
        hparams, 'meta'#device
    )

# Set up language model
hparams = setup_hparams(priors[-1], dict())

# IMPORTANT LINE: only include layers UP TO prior_depth
#hparams["prior_depth"] = 72

if cache_gdrive:
    hparams.restore_prior = PRIOR_CACHE_PATH

# don't actually load any weights in yet,
# leave it for later. memory optimization
with init_empty_weights():
    top_prior = make_prior(hparams, vqvae, 'meta')#device)

# flips a bit that tells the model to return activations
# instead of projecting to tokens and getting loss for
# forward pass
top_prior.prior.only_encode = True

##############################################
# actually loading in the model weights now! #
##############################################

import torch
from tqdm import tqdm
import torch.nn as nn

top_prior_weights = torch.load(PRIOR_CACHE_PATH, map_location='cpu')

def set_module_tensor_to_device(
    module: nn.Module, tensor_name: str, device, value=None
):
    """
    A helper function to set a given tensor (parameter of buffer) of a module on a specific device (note that doing
    `param.to(device)` creates a new tensor not linked to the parameter, which is why we need this function).
    Args:
        module (`torch.nn.Module`): The module in which the tensor we want to move lives.
        param_name (`str`): The full name of the parameter/buffer.
        device (`int`, `str` or `torch.device`): The device on which to set the tensor.
        value (`torch.Tensor`, *optional*): The value of the tensor (useful when going from the meta device to any
            other device).
    """
    # Recurse if needed
    if "." in tensor_name:
        splits = tensor_name.split(".")
        for split in splits[:-1]:
            new_module = getattr(module, split)
            if new_module is None:
                raise ValueError(f"{module} has no attribute {split}.")
            module = new_module
        tensor_name = splits[-1]

    if tensor_name not in module._parameters and tensor_name not in module._buffers:
        raise ValueError(f"{module} does not have a parameter or a buffer named {tensor_name}.")
    is_buffer = tensor_name in module._buffers
    old_value = getattr(module, tensor_name)

    if old_value.device == torch.device("meta") and device not in ["meta", torch.device("meta")] and value is None:
        raise ValueError(f"{tensor_name} is on the meta device, we need a `value` to put in on {device}.")

    with torch.no_grad():
        if value is None:
            new_value = old_value.to(device)
        elif isinstance(value, torch.Tensor):
            new_value = value.to(device)
        else:
            new_value = torch.tensor(value, device=device)

        if is_buffer:
            module._buffers[tensor_name] = new_value
        elif value is not None or torch.device(device) != module._parameters[tensor_name].device:
            param_cls = type(module._parameters[tensor_name])
            kwargs = module._parameters[tensor_name].__dict__
            new_value = param_cls(new_value, requires_grad=old_value.requires_grad, **kwargs).to(device)
            module._parameters[tensor_name] = new_value

# load_state_dict, basically
for k in tqdm(top_prior_weights['model'].keys()):
    set_module_tensor_to_device(top_prior, k, 'cuda', value=top_prior_weights['model'][k])

print(next(top_prior.parameters()).device)
print(next(vqvae.parameters()).device)


del top_prior_weights

import gc
gc.collect()

vqvae_weights = torch.load(VQVAE_CACHE_PATH, map_location='cpu')

for k in tqdm(vqvae_weights['model'].keys()):
    set_module_tensor_to_device(vqvae, k, 'cuda', value=vqvae_weights['model'][k])


#@title Jukebox extraction code

###########################
# Jukebox extraction code #
###########################

# Note: this code was written by reverse-engineering the model, which entailed
# combing through https://github.com/openai/jukebox all the way down the stack
# trace together with the readily-executable Colab example https://colab.research.google.com/github/openai/jukebox/blob/master/jukebox/Interacting_with_Jukebox.ipynb
# and modifying values as necessary to get what we needed.

import librosa as lr
import torch
import torch as t
import gc
import numpy as np

JUKEBOX_SAMPLE_RATE = 44100
T = 8192

# 1048576 found in paper, last page
DEFAULT_DURATION = 1048576 / JUKEBOX_SAMPLE_RATE

VQVAE_RATE = T / DEFAULT_DURATION

def empty_cache():
    torch.cuda.empty_cache()
    gc.collect()

def load_audio_from_file(fpath, offset=0.0, duration=None):
    if duration is not None:
        audio, _ = lr.load(fpath,
                           sr=JUKEBOX_SAMPLE_RATE,
                           offset=offset,
                           duration=duration)
    else:
        audio, _ = lr.load(fpath,
                           sr=JUKEBOX_SAMPLE_RATE,
                           offset=offset)

    if audio.ndim == 1:
        audio = audio[np.newaxis]
    audio = audio.mean(axis=0)

    # normalize audio
    norm_factor = np.abs(audio).max()
    if norm_factor > 0:
        audio /= norm_factor

    return audio.flatten()


def get_z(audio):
    # don't compute unnecessary discrete encodings
    audio = audio[: JUKEBOX_SAMPLE_RATE * 25]

    zs = vqvae.encode(torch.cuda.FloatTensor(audio[np.newaxis, :, np.newaxis]))

    z = zs[-1].flatten()[np.newaxis, :]

    return z


def get_cond(hps, top_prior):
    # model only accepts sample length conditioning of
    # >60 seconds
    sample_length_in_seconds = 62

    hps.sample_length = (
        int(sample_length_in_seconds * hps.sr) // top_prior.raw_to_tokens
    ) * top_prior.raw_to_tokens

    # NOTE: the 'lyrics' parameter is required, which is why it is included,
    # but it doesn't actually change anything about the `x_cond`, `y_cond`,
    # nor the `prime` variables. The `prime` variable is supposed to represent
    # the lyrics, but the LM prior we're using does not condition on lyrics,
    # so it's just an empty tensor.
    metas = [
        dict(
            artist="unknown",
            genre="unknown",
            total_length=hps.sample_length,
            offset=0,
            lyrics="""lyrics go here!!!""",
        ),
    ] * hps.n_samples

    labels = [None, None, top_prior.labeller.get_batch_labels(metas, "cuda")]

    x_cond, y_cond, prime = top_prior.get_cond(None, top_prior.get_y(labels[-1], 0))

    x_cond = x_cond[0, :T][np.newaxis, ...]
    y_cond = y_cond[0][np.newaxis, ...]

    return x_cond, y_cond

def downsample(representation,
               target_rate=30,
               method=None):
    if method is None:
        method = 'librosa_fft'

    if method == 'librosa_kaiser':
        resampled_reps = lr.resample(np.asfortranarray(representation.T),
                                     T / DEFAULT_DURATION,
                                     target_rate).T
    elif method in ['librosa_fft', 'librosa_scipy']:
        resampled_reps = lr.resample(np.asfortranarray(representation.T),
                                     T / DEFAULT_DURATION,
                                     target_rate,
                                     res_type='fft').T
    elif method == 'mean':
        raise NotImplementedError

    return resampled_reps

def get_final_activations(z, x_cond, y_cond, top_prior):

    x = z[:, :T]

    input_length = x.shape[1]

    if x.shape[1] < T:
        # arbitrary choices
        min_token = 0
        max_token = 100

        x = torch.cat((x,
                       torch.randint(min_token, max_token, size=(1, T - input_length,), device='cuda')),
                      dim=-1)

    # encoder_kv and fp16 are set to the defaults, but explicitly so
    out = top_prior.prior.forward(
        x, x_cond=x_cond, y_cond=y_cond, encoder_kv=None, fp16=False
    )

    # chop off, in case input was already chopped
    out = out[:,:input_length]

    return out

def roll(x, n):
    return t.cat((x[:, -n:], x[:, :-n]), dim=1)

def get_activations_custom(x,
                           x_cond,
                           y_cond,
                           layers_to_extract=None,
                           fp16=False,
                           fp16_out=False):

    # this function is adapted from:
    # https://github.com/openai/jukebox/blob/08efbbc1d4ed1a3cef96e08a931944c8b4d63bb3/jukebox/prior/autoregressive.py#L116

    # custom jukemir stuff
    if layers_to_extract is None:
        layers_to_extract = [36]

    x = x[:,:T]  # limit to max context window of Jukebox

    input_seq_length = x.shape[1]

    # chop x_cond if input is short
    x_cond = x_cond[:, :input_seq_length]

    # Preprocess.
    with t.no_grad():
        x = top_prior.prior.preprocess(x)

    N, D = x.shape
    assert isinstance(x, t.cuda.LongTensor)
    assert (0 <= x).all() and (x < top_prior.prior.bins).all()

    if top_prior.prior.y_cond:
        assert y_cond is not None
        assert y_cond.shape == (N, 1, top_prior.prior.width)
    else:
        assert y_cond is None

    if top_prior.prior.x_cond:
        assert x_cond is not None
        assert x_cond.shape == (N, D, top_prior.prior.width) or x_cond.shape == (N, 1, top_prior.prior.width), f"{x_cond.shape} != {(N, D, top_prior.prior.width)} nor {(N, 1, top_prior.prior.width)}. Did you pass the correct --sample_length?"
    else:
        assert x_cond is None
        x_cond = t.zeros((N, 1, top_prior.prior.width), device=x.device, dtype=t.float)

    x_t = x # Target
    # self.x_emb is just a straightforward embedding, no trickery here
    x = top_prior.prior.x_emb(x) # X emb
    # this is to be able to fit in a start token/conditioning info: just shift to the right by 1
    x = roll(x, 1) # Shift by 1, and fill in start token
    # self.y_cond == True always, so we just use y_cond here
    if top_prior.prior.y_cond:
        x[:,0] = y_cond.view(N, top_prior.prior.width)
    else:
        x[:,0] = top_prior.prior.start_token

    # for some reason, p=0.0, so the dropout stuff does absolutely nothing
    x = top_prior.prior.x_emb_dropout(x) + top_prior.prior.pos_emb_dropout(top_prior.prior.pos_emb())[:input_seq_length] + x_cond # Pos emb and dropout

    layers = top_prior.prior.transformer._attn_mods

    reps = {}

    if fp16:
        x = x.half()

    for i, l in enumerate(layers):
        # to be able to take in shorter clips, we set sample to True,
        # but as a consequence the forward function becomes stateful
        # and its state changes when we apply a layer (attention layer
        # stores k/v's to cache), so we need to clear its cache religiously
        l.attn.del_cache()

        x = l(x, encoder_kv=None, sample=True)

        l.attn.del_cache()

        if i + 1 in layers_to_extract:
            reps[i + 1] = np.array(x.squeeze().cpu())

            # break if this is the last one we care about
            if layers_to_extract.index(i + 1) == len(layers_to_extract) - 1:
                break

    return reps


# important, gradient info takes up too much space,
# causes CUDA OOM
@torch.no_grad()
def get_acts_from_audio(audio=None,
                        fpath=None,
                        meanpool=False,
                        # pick which layer(s) to extract from
                        layers=None,
                        # pick which part of the clip to load in
                        offset=0.0,
                        duration=None,
                        # downsampling frame-wise reps
                        downsample_target_rate=None,
                        downsample_method=None,
                        # for speed-saving
                        fp16=False,
                        # for space-saving
                        fp16_out=False,
                        # for GPU VRAM. potentially slows it
                        # down but we clean up garbage VRAM.
                        # disable if your GPU has a lot of memory
                        # or if you're extracting from earlier
                        # layers.
                        force_empty_cache=True):

    # main function that runs extraction end-to-end.

    if layers is None:
        layers = [36]  # by default

    if audio is None:
        assert fpath is not None
        audio = load_audio_from_file(fpath, offset=offset, duration=duration)
    elif fpath is None:
        assert audio is not None

    if force_empty_cache: empty_cache()

    # run vq-vae on the audio to get discretized audio
    z = get_z(audio)

    if force_empty_cache: empty_cache()

    # get conditioning info
    x_cond, y_cond = get_cond(hps, top_prior)

    if force_empty_cache: empty_cache()

    # get the activations from the LM
    acts = get_activations_custom(z,
                                  x_cond,
                                  y_cond,
                                  layers_to_extract=layers,
                                  fp16=fp16,
                                  fp16_out=fp16_out)

    if force_empty_cache: empty_cache()

    # postprocessing
    if downsample_target_rate is not None:
        for num in acts.keys():
            acts[num] = downsample(acts[num],
                                   target_rate=downsample_target_rate,
                                   method=downsample_method)

    if meanpool:
        acts = {num: act.mean(axis=0) for num, act in acts.items()}

    if not fp16_out:
        acts = {num: act.astype(np.float32) for num, act in acts.items()}

    return acts
  
JUKEBOX_SAMPLE_RATE = 44100
WINDOW_SEC = 24
WINDOW_SAMPLES = JUKEBOX_SAMPLE_RATE * WINDOW_SEC
T = 8192  # LM token length per 24 s

def frame_audio_24s(audio: np.ndarray):
    n = len(audio)
    for start in range(0, n, WINDOW_SAMPLES - CHUNKING_OVERLAP_SEC * JUKEBOX_SAMPLE_RATE):
        end = min(start + WINDOW_SAMPLES, n)
        chunk = audio[start:end]
        if len(chunk) == 0:
            continue
        if len(chunk) < WINDOW_SAMPLES:
            # zero-pad last partial window to exactly 24 s
            pad = np.zeros(WINDOW_SAMPLES - len(chunk), dtype=chunk.dtype)
            chunk = np.concatenate([chunk, pad], axis=0)
        yield chunk

def get_activations_custom_torch(x,
                                 x_cond,
                                 y_cond,
                                 layers_to_extract=None,
                                 fp16=False):
    if layers_to_extract is None:
        layers_to_extract = [36]

    x = x[:, :T]
    input_seq_length = x.shape[1]
    x_cond = x_cond[:, :input_seq_length]

    with torch.no_grad():
        x = top_prior.prior.preprocess(x)  # int64 tokens -> cuda long

    N, D = x.shape
    if top_prior.prior.y_cond:
        assert y_cond is not None

    if not top_prior.prior.x_cond:
        x_cond = torch.zeros((N, 1, top_prior.prior.width), device=x.device, dtype=torch.float)

    x_t = x
    x = top_prior.prior.x_emb(x)
    x = roll(x, 1)
    if top_prior.prior.y_cond:
        x[:, 0] = y_cond.view(N, top_prior.prior.width)
    else:
        x[:, 0] = top_prior.prior.start_token

    x = top_prior.prior.x_emb_dropout(x) + top_prior.prior.pos_emb_dropout(top_prior.prior.pos_emb())[:input_seq_length] + x_cond

    layers = top_prior.prior.transformer._attn_mods
    reps = {}

    if fp16:
        x = x.half()

    for i, l in enumerate(layers):
        l.attn.del_cache()
        x = l(x, encoder_kv=None, sample=True)
        l.attn.del_cache()

        if (i + 1) in layers_to_extract:
            # x shape: [N=1, seq_len, width]
            reps[i + 1] = x.squeeze(0)  # [seq_len, width]
            if layers_to_extract.index(i + 1) == len(layers_to_extract) - 1:
                break

    return reps

@torch.no_grad()
def meanpool_layers_over_24s_windows(audio=None,
                                     fpath=None,
                                     layers=None,
                                     fp16=False,
                                     force_empty_cache=True):
    if layers is None:
        layers = [36]

    # 1) Load and normalize full audio
    if audio is None:
        assert fpath is not None
        audio = load_audio_from_file(fpath, offset=0.0, duration=None)

    # 2) Prepare conditioning once (we slice per window inside)
    x_cond_full, y_cond = get_cond(hps, top_prior)

    width = top_prior.prior.width  # 4800
    sums = {lyr: torch.zeros(width, device='cuda', dtype=torch.float32) for lyr in layers}
    total_tokens = 0

    for wav_24s in frame_audio_24s(audio):
        if force_empty_cache: empty_cache()

        # 3) VQ-VAE encode this 24 s window → top-level tokens (shape [1, T])
        zs = vqvae.encode(torch.cuda.FloatTensor(wav_24s[np.newaxis, :, np.newaxis]))
        z_top = zs[-1].flatten()[np.newaxis, :]  # [1, T] exactly, due to padding

        # 4) Slice conds to the exact token length (should already be T)
        cur_len = z_top.shape[1]
        x_cond = x_cond_full[:, :cur_len]

        # 5) Run LM and grab chosen layer(s) activations
        reps = get_activations_custom_torch(
            z_top, x_cond, y_cond,
            layers_to_extract=layers,
            fp16=fp16
        )
        # reps[lyr]: [cur_len, width] for each layer

        for lyr, X in reps.items():
            sums[lyr] += X.to(torch.float32).sum(dim=0)
        total_tokens += cur_len

    if force_empty_cache: empty_cache()

    # 6) Global mean over all tokens across all 24 s windows
    means = {lyr: (sums[lyr] / total_tokens).detach().cpu().numpy().astype('float32')
             for lyr in layers}
    return means

def parse_filename_genre_and_title(filename: str) -> Tuple[str, str]:
  try:
    # Assumes format "[{genre}] - {filename}.pt"
    genre_part, filename_part = filename.split('] - ', 1)
    genre = genre_part[1:]  # Remove the leading '['
    title = os.path.splitext(filename_part)[0]  # Remove .pt extension
    return genre, title
  except ValueError:
    return 'Unknown', os.path.splitext(filename)[0]

def get_completed_embeddings(embedding_dir: str) -> Dict[str, Set[str]]:
  completed: Dict[str, Set[str]] = {}
  for fp, _, files in os.walk(embedding_dir):
    for f in files:
      if f.lower().endswith(".pt"):
        genre, title = parse_filename_genre_and_title(f)
        completed.setdefault(genre, set()).add(title)

  return completed

def get_flac_list(dir_path: str) -> Dict[str, List[str]]:
  # genre and list of songs
  flac_files: Dict[str, List[str]] = {}
  # first level dir is genre info
  for item in os.listdir(dir_path):
    path = os.path.join(dir_path, item)
    if not os.path.isdir(path):
      continue

    flac_files[item] = []
    for fp, _, files in os.walk(path):
      for f in files:
        if f.lower().endswith(".flac"):
          full_path = os.path.join(fp, f)
          # if ("[ignore]" in full_path.lower()):
          #   continue
          flac_files[item].append(full_path)

  return flac_files

# fname = '(01) [RD-SOUND] グレートアトラクター (Part ⅰ).flac'

# audio, sr = lr.load(fname,
#                     sr=None,
#                     offset=0)

# print("Computing representations...")

# representations = meanpool_layers_over_24s_windows(audio=audio,
#                                                    layers=[36])

# # audio = load_audio_from_file(fname, offset=0.0, duration=25)
# # representations = get_acts_from_audio(audio=audio,
# #                                       layers=[36],
# #                                       meanpool=True)

# print(f"Got representations {representations}")
# print(f"Its shape is {representations[36].shape}")

POOLING_POLICY = "mean"
EMBEDDING_DIRECTORY = f"embeddings/{POOLING_POLICY}"
flac_list = get_flac_list("data/")
completed_embeddings = get_completed_embeddings(EMBEDDING_DIRECTORY)

for genre, files in flac_list.items():
    for i in files:
        print("Processing track ID:", i)
        
        # get file name
        filename = os.path.splitext(os.path.basename(i))[0]
        if genre in completed_embeddings and filename in completed_embeddings[genre]:
            print(f"Skipping {filename} in genre {genre}, already processed.")
            continue
        
        
        audio = load_audio_from_file(i, offset=0.0, duration=None)
        
        reps = []
        for ci, chunk in enumerate(frame_audio_24s(audio)):
            print(f"Processing chunk {ci} with length {len(chunk)} samples")
            rep = get_acts_from_audio(audio=chunk, layers=[36], fp16=True, meanpool=True)
            reps.append(rep[36])
            
        r = torch.cat(reps, dim=0)
        
        # save representation
        save_path = os.path.join(EMBEDDING_DIRECTORY, f"[{genre}] - {filename}.pt")
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        torch.save(r.mean(dim=0), save_path)
        print(f"Saved representation to {save_path}")
