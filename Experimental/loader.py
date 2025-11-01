import subprocess
from typing import List
from dataclasses import dataclass
from typing import Tuple
import numpy as np
import soundfile as sf
from torchaudio.io import StreamReader
import torch  # needed because StreamReader yields torch tensors
import torchaudio.transforms as T  # <-- ADDED for resampling


@dataclass
class ChunkingConfig:
    target_sample_rate: int  # target sample rate after resampling
    chunk_size: int  # in seconds at the target_sample_rate
    overlap_size: int  # in seconds


@dataclass
class AudioChunks:
    chunks: List[np.ndarray]
    sample_rate: int  # This will be the target_sample_rate
    chunking_config: ChunkingConfig


def chunk_audio(wav: np.ndarray, sr: int, config: ChunkingConfig) -> AudioChunks:
    """
    Chunks the given waveform based on the config.
    Assumes wav is already at the config.target_sample_rate.
    """
    target_sr = config.target_sample_rate

    # Check if the provided sample rate matches the target
    if sr != target_sr:
        # This should not happen if upstream functions resample correctly
        raise ValueError(
            f"chunk_audio received SR {sr} but expected {target_sr}. "
            "Audio must be resampled before chunking."
        )

    # Calculate chunk/overlap in samples AT THE TARGET SAMPLE RATE
    chunk_size_samples = int(config.chunk_size * target_sr)
    overlap_size_samples = int(config.overlap_size * target_sr)
    step = chunk_size_samples - overlap_size_samples

    if chunk_size_samples <= 0:
        raise ValueError(
            f"chunk_size ({config.chunk_size}s) results in 0 samples at {target_sr}Hz. Check config."
        )
    if step <= 0:
        raise ValueError(
            "chunk_size and overlap_size result in zero or negative step. "
            "Overlap must be smaller than chunk size."
        )

    chunks = []
    for start in range(0, len(wav), step):
        end = start + chunk_size_samples
        if end > len(wav):
            # Original logic: skip the last partial chunk
            break
        chunks.append(wav[start:end])

    return AudioChunks(chunks=chunks, sample_rate=sr, chunking_config=config)


def load_flac(fp: str, chunking_config: ChunkingConfig) -> AudioChunks:
    wav_np, sr = sf.read(fp, always_2d=False)
    target_sr = chunking_config.target_sample_rate

    if wav_np.ndim == 2:  # (T, C) -> mono
        wav_np = wav_np.mean(axis=1)

    # ensure float32 in [-1, 1]
    wav_np = wav_np.astype(np.float32, copy=False)

    # --- ADDED: Resample if necessary ---
    if sr != target_sr:
        print(f"Resampling from {sr} Hz to {target_sr} Hz")
        # Convert to torch tensor for torchaudio transforms
        # T.Resample handles mono (T,) tensors directly
        wav_tensor = torch.from_numpy(wav_np)

        resampler = T.Resample(orig_freq=sr, new_freq=target_sr)
        wav_tensor_resampled = resampler(wav_tensor)

        wav_np = wav_tensor_resampled.numpy()
        sr = target_sr  # Update sample rate to new rate
    # --- End of added section ---

    # Pass the resampled audio and the target SR to chunk_audio
    return chunk_audio(wav_np, sr, chunking_config)

def read_hls_via_ffmpeg(url: str, target_sr: int, mono: bool = True) -> np.ndarray:
    # Build ffmpeg command that decodes + resamples to float32 PCM on stdout
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", url,
        "-vn",
        "-acodec", "pcm_f32le",
        "-f", "f32le",
        "-ar", str(object=target_sr),
        "-ac", "1" if mono else "2",
        "pipe:1",
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    pcm = p.stdout.read()  # read all
    p.wait()
    if p.returncode != 0 or not pcm:
        raise RuntimeError("ffmpeg failed to decode HLS")
    # Convert bytes -> float32 numpy
    wav = np.frombuffer(pcm, dtype=np.float32)
    return wav


def _load_hls_common(
    src: str, chunking_config: ChunkingConfig
) -> AudioChunks:
    # Build reader
    reader = StreamReader(src=src)
    target_sr = chunking_config.target_sample_rate  # <-- Get target SR

    # Discover source audio stream’s native sample rate
    try:
        sinfo = reader.get_src_stream_info(0)  # first (and usually only) stream
        src_sr = int(getattr(sinfo, "sample_rate", 44100) or 44100)
    except Exception:
        src_sr = 44100

    # Use ~1–5 seconds per internal decode chunk; based on *source* SR
    seconds_per_internal_chunk = 5.0
    frames_per_chunk = max(1, int(src_sr * seconds_per_internal_chunk))

    # --- MODIFIED: Ask FFmpeg to decode *and resample* to the target_sr ---
    reader.add_audio_stream(
        frames_per_chunk=frames_per_chunk,
        decoder=None,
        sample_rate=target_sr,  # <-- Tell FFmpeg to resample
    )

    pcs = []
    for (pcm_chunk,) in reader.stream():
        if (pcm_chunk is None) or (pcm_chunk.numel() == 0):
            continue
        # pcm_chunk: [frames, channels], float32 in [-1, 1]
        # This chunk is now *already* at the `target_sr`
        if pcm_chunk.numel() == 0:
            continue
        # to mono
        if pcm_chunk.size(1) > 1:
            pcm_chunk = pcm_chunk.mean(dim=1, keepdim=True)
        pcs.append(pcm_chunk)

    if not pcs:
        raise RuntimeError("No audio decoded from HLS stream.")

    # Concatenate and squeeze channel dim -> [T]
    wav = torch.cat(pcs, dim=0).squeeze(1).contiguous()
    wav_np = wav.numpy().astype(np.float32, copy=False)

    # --- MODIFIED: Pass the target_sr to chunk_audio ---
    return chunk_audio(wav_np, target_sr, chunking_config)


def load_m3u8_playlist_local(fp: str, chunking_config: ChunkingConfig) -> AudioChunks:
    """
    Load a local HLS playlist (e.g., a folder with init.mp4 + *.m4s + playlist.m3u8).
    """
    return _load_hls_common(
        src=fp, chunking_config=chunking_config
    )


def load_m3u8_playlist_remote(url: str, chunking_config: ChunkingConfig) -> AudioChunks:
    target_sr = chunking_config.target_sample_rate
    wav_np = read_hls_via_ffmpeg(url, target_sr, mono=True)
    return chunk_audio(wav_np, target_sr, chunking_config)
