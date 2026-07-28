"""Tests for utils/journal.py -- resume, seeding, and the concurrency claims."""
import os, pickle, shutil, sys, tempfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.journal import RunJournal, scan_completed_ids

fails = 0
def check(cond, label):
    global fails
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fails += 1

tmp = tempfile.mkdtemp(prefix="journal-test-")
emb = os.path.join(tmp, "embeddings")
os.makedirs(emb)

U = [f"{i:08x}-1111-2222-3333-444444444444" for i in range(6)]

# --- 1. fresh journal, nothing done -----------------------------------------
j = RunJournal(emb, name="t")
check(j.load_completed() == set(), "fresh journal reports nothing completed")

# --- 2. seeding from an existing embeddings directory ------------------------
shutil.rmtree(tmp); os.makedirs(emb)
for u in U[:3]:
    open(os.path.join(emb, f"{u}.allchunks.pt"), "wb").write(b"x")
j = RunJournal(emb, name="t")
seeded = j.load_completed(rebuild_from=lambda: scan_completed_ids(emb))
check(seeded == set(U[:3]), f"seeds from existing .pt files (got {len(seeded)})")
check(os.path.exists(j.completed_path), "seeding wrote the completed list")

# a second load must NOT rescan -- prove it by deleting the .pt files
for u in U[:3]:
    os.unlink(os.path.join(emb, f"{u}.allchunks.pt"))
j2 = RunJournal(emb, name="t")
called = []
again = j2.load_completed(rebuild_from=lambda: called.append(1) or set())
check(again == set(U[:3]) and not called,
      "second load reads the list, does not rescan the directory")

# --- 3. append then reload ---------------------------------------------------
j2.report_completed(U[3])
j2.report_completed(U[4])
j2.close()
check(RunJournal(emb, name="t").load_completed() == set(U[:5]),
      "appended ids survive a reopen")

# --- 4. failure journal ------------------------------------------------------
j3 = RunJournal(emb, name="t")
j3.report_failed(U[5], "/lib/x.m3u8", "ffmpeg blew up\nline two\n  line three")
j3.close()
lines = open(j3.failed_path, encoding="utf-8").read().splitlines()
check(len(lines) == 1, f"multi-line reason collapsed to one record (got {len(lines)})")
check(lines[0].split("\t")[2] == "ffmpeg blew up line two line three",
      "newlines flattened, fields tab-separated")
j4 = RunJournal(emb, name="t")
j4.report_failed("x", "/p", "z" * 5000)
j4.close()
longest = max(len(l) for l in open(j4.failed_path, encoding="utf-8"))
check(longest < 4096, f"records stay under PIPE_BUF for atomic append ({longest} B)")

# --- 5. pickles across a process boundary (DataLoader spawn) -----------------
j5 = RunJournal(emb, name="pick")
j5.report_completed("warm-the-handle")
revived = pickle.loads(pickle.dumps(j5))
check(revived.completed_path == j5.completed_path, "survives pickle round-trip")
revived.report_completed("from-the-copy")
check("from-the-copy" in RunJournal(emb, name="pick").load_completed(),
      "unpickled copy reopens its own handle and writes")

# --- 6. concurrent appends: threads and processes ----------------------------
def wr_proc(args):
    path, name, lo, hi = args
    jj = RunJournal(path, name=name)
    for i in range(lo, hi):
        jj.report_completed(f"{i:08x}-aaaa-bbbb-cccc-dddddddddddd")
    jj.close()

conc = os.path.join(tmp, "conc"); os.makedirs(conc)
with ProcessPoolExecutor(max_workers=8) as ex:
    list(ex.map(wr_proc, [(conc, "c", i * 500, (i + 1) * 500) for i in range(8)]))
got = RunJournal(conc, name="c").load_completed()
raw = open(os.path.join(conc, "c.completed.txt"), encoding="utf-8").read().splitlines()
check(len(got) == 4000, f"8 processes x 500 appends -> 4000 distinct ids (got {len(got)})")
check(len(raw) == 4000 and all(len(l) == 36 for l in raw),
      "no interleaved or torn lines across processes")

jt = RunJournal(os.path.join(tmp, "thr"), name="t")
with ThreadPoolExecutor(max_workers=16) as ex:
    list(ex.map(lambda i: jt.report_completed(f"{i:08x}-eeee-ffff-0000-111111111111"),
                range(2000)))
jt.close()
check(len(RunJournal(os.path.join(tmp, "thr"), name="t").load_completed()) == 2000,
      "16 threads x appends -> no lost records")

shutil.rmtree(tmp, ignore_errors=True)
print("PASS" if not fails else f"{fails} CHECK(S) FAILED")
sys.exit(1 if fails else 0)
