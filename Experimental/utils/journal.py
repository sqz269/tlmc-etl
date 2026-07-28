"""Crash-safe progress tracking for long inference runs.

Ported from the HLS transcode stage, which learned three things over a 164k-track
run that apply here unchanged:

  * Resume must not rescan the output directory. Walking every ``.pt`` on start
    is a stat() storm at catalogue scale, and worse when the output lives on a
    network mount.
  * A track counts as done only once its bytes are on disk under their final
    name -- never at submit time. HLS wrote the media file before the playlist
    for the same reason.
  * Failures need a journal, not a print. The v6 library contains truncated
    sources that no decoder can read (23 of them surfaced during the transcode),
    and you want that list afterwards rather than scrolled off a terminal.

Durability: records are flushed, not fsynced. Losing the tail of the journal to a
machine crash costs a few re-encoded tracks, which is the right trade against an
fsync per track.
"""

import os
import re
import threading

UUID_REGEX = re.compile(
  r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def scan_completed_ids(embedding_dir: str) -> set:
  """Recover the completed set by walking ``embedding_dir`` for ``*.pt``.

  The slow path. Used once to seed the journal from a run that predates it, so
  existing embeddings are not recomputed.
  """
  found = set()
  if not os.path.isdir(embedding_dir):
    return found
  for dirpath, _, files in os.walk(embedding_dir):
    for f in files:
      if f.lower().endswith(".pt"):
        m = UUID_REGEX.search(f)
        if m:
          found.add(m.group(0))
  return found


class RunJournal:
  """Append-only completed list and failure log for one inference run.

  Safe to use from both the publishing thread pool and the DataLoader worker
  *processes*: each record is a single short line written to a handle opened
  ``O_APPEND``, and Linux makes appends below PIPE_BUF (4096 bytes) atomic
  against interleaving. Failure reasons are truncated to keep that guarantee.
  """

  def __init__(self, output_dir: str, name: str = "mert"):
    self.output_dir = output_dir
    self.completed_path = os.path.join(output_dir, f"{name}.completed.txt")
    self.failed_path = os.path.join(output_dir, f"{name}.failed.txt")
    self._lock = threading.Lock()
    self._handles = {}

  # DataLoader workers are spawned, so the journal is pickled into them. File
  # handles and locks are not picklable and must not be shared across processes
  # anyway -- each child reopens its own in append mode.
  def __getstate__(self):
    return {
      "output_dir": self.output_dir,
      "completed_path": self.completed_path,
      "failed_path": self.failed_path,
    }

  def __setstate__(self, state):
    self.__dict__.update(state)
    self._lock = threading.Lock()
    self._handles = {}

  def _handle(self, path: str):
    key = (os.getpid(), path)
    fh = self._handles.get(key)
    if fh is None:
      os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
      fh = open(path, "a", encoding="utf-8")
      self._handles[key] = fh
    return fh

  def _append(self, path: str, line: str) -> None:
    with self._lock:
      fh = self._handle(path)
      fh.write(line)
      fh.flush()

  def load_completed(self, rebuild_from=None) -> set:
    """Read the completed set, seeding it once if the journal does not exist yet.

    ``rebuild_from`` is a zero-argument callable returning a set of ids. It runs
    only when there is no completed list, which makes adopting the journal
    non-destructive: a directory of embeddings from an earlier run is imported
    rather than recomputed.
    """
    if not os.path.exists(self.completed_path) and rebuild_from is not None:
      seeded = rebuild_from()
      if seeded:
        os.makedirs(self.output_dir, exist_ok=True)
        with open(self.completed_path, "w", encoding="utf-8") as f:
          for track_id in sorted(seeded):
            f.write(f"{track_id}\n")
        print(f"Seeded {self.completed_path} with {len(seeded)} ids from an "
              f"existing embeddings directory")
        return seeded

    if not os.path.exists(self.completed_path):
      return set()

    with open(self.completed_path, "r", encoding="utf-8") as f:
      return {line.strip() for line in f if line.strip()}

  def report_completed(self, track_id: str) -> None:
    self._append(self.completed_path, f"{track_id}\n")

  def report_failed(self, track_id: str, path: str, reason) -> None:
    # Collapsed to one line and truncated: ffmpeg failures arrive as multi-line
    # stderr, and both properties are load-bearing for the atomic-append rule.
    reason = " ".join(str(reason).split())[:300]
    self._append(self.failed_path, f"{track_id}\t{path}\t{reason}\n")

  def close(self) -> None:
    with self._lock:
      for fh in self._handles.values():
        try:
          fh.close()
        except Exception:
          pass
      self._handles.clear()
