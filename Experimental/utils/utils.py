import torch


def pool(tensor: torch.Tensor, mode: str = "mean") -> torch.Tensor:
  """
  Pooling function for 2D tensor of shape (time, dim).
  Supported modes: 'mean', 'max', 'mean+max' (concatenation).
  Returns a 1D tensor of shape (dim,) or (2*dim,) for 'mean+max'.
  """
  if mode == "mean":
    return tensor.mean(dim=0)
  elif mode == "max":
    return tensor.max(dim=0).values
  elif mode == "mean+max":
    mean_pool = tensor.mean(dim=0)
    max_pool = tensor.max(dim=0).values
    return torch.cat((mean_pool, max_pool), dim=0)
  else:
    raise ValueError(f"Unsupported pooling mode: {mode}")

def save_tensor(tensor: torch.Tensor, filepath: str) -> None:
  """
  Save a tensor to a file.
  """
  torch.save(tensor, filepath)
