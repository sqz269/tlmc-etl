"""Tests for the atomic save_tensor in Experimental/utils/utils.py.

utils.utils drags in torch/numpy/tqdm and utils.loader (soundfile, torchaudio,
pydub), none of which are installed on this host and none of which save_tensor
touches. They are stubbed so the rename semantics can be tested directly.
"""
import os, shutil, sys, tempfile, types

for name in ("torch", "tqdm", "numpy", "soundfile", "torchaudio",
             "torchaudio.transforms", "pydub"):
    mod = types.ModuleType(name)
    sys.modules.setdefault(name, mod)

# type annotations are evaluated at def time, so the stubs need the names used
# in utils.utils' signatures to resolve to something
sys.modules["numpy"].ndarray = object
sys.modules["numpy"].float32 = float

saved = []
def fake_save(obj, path):
    saved.append(path)
    if getattr(obj, "explode", False):
        raise RuntimeError("simulated write failure")
    with open(path, "w") as f:
        f.write(obj if isinstance(obj, str) else "tensor")

sys.modules["torch"].save = fake_save
sys.modules["torch"].Tensor = object
sys.modules["torch"].load = lambda *a, **k: None
sys.modules["pydub"].AudioSegment = object
sys.modules["soundfile"].read = lambda *a, **k: None

EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EXP)
sys.modules["utils"] = types.ModuleType("utils")
sys.modules["utils"].__path__ = [os.path.join(EXP, "utils")]
loader_stub = types.ModuleType("utils.loader")
loader_stub.SourceFileInfo = object
sys.modules["utils.loader"] = loader_stub

import importlib.util
spec = importlib.util.spec_from_file_location("utils.utils", os.path.join(EXP, "utils", "utils.py"))
uu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uu)

fails = 0
def check(cond, label):
    global fails
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fails += 1

tmp = tempfile.mkdtemp(prefix="atomic-")

# --- 1. happy path -----------------------------------------------------------
dst = os.path.join(tmp, "a", "track.pt")
uu.save_tensor("payload-1", dst)
check(os.path.isfile(dst), "writes the file")
check(open(dst).read() == "payload-1", "content correct")
check(os.listdir(os.path.dirname(dst)) == ["track.pt"], "no .tmp left behind")
check(saved and saved[-1] != dst, "torch.save targeted a temp path, not the final name")
check(os.path.dirname(saved[-1]) == os.path.dirname(dst),
      "temp file is a sibling (rename stays within one filesystem)")

# --- 2. creates missing directories ------------------------------------------
deep = os.path.join(tmp, "x", "y", "z", "t.pt")
uu.save_tensor("payload-2", deep)
check(os.path.isfile(deep), "creates intermediate directories")

# --- 3. write failure leaves NOTHING -----------------------------------------
class Boom(str):
    explode = True

bad = os.path.join(tmp, "a", "bad.pt")
try:
    uu.save_tensor(Boom("nope"), bad)
    check(False, "failure propagates")
except RuntimeError:
    check(True, "failure propagates to caller")
check(not os.path.exists(bad), "failed save leaves no file at the final name")
check(sorted(os.listdir(os.path.join(tmp, "a"))) == ["track.pt"],
      f"failed save leaves no .tmp: {sorted(os.listdir(os.path.join(tmp, 'a')))}")

# --- 4. overwrite is all-or-nothing ------------------------------------------
uu.save_tensor("v2", dst)
check(open(dst).read() == "v2", "overwrite replaces content")
try:
    uu.save_tensor(Boom("v3"), dst)
except RuntimeError:
    pass
check(open(dst).read() == "v2",
      "a failed overwrite leaves the PREVIOUS file intact, not a truncated one")

shutil.rmtree(tmp, ignore_errors=True)
print("PASS" if not fails else f"{fails} CHECK(S) FAILED")
sys.exit(1 if fails else 0)
