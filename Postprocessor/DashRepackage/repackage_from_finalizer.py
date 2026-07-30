"""Generates DASH manifests for the whole v6 tree, driven by the finalizer manifest.

file-target.py discovers HLS roots by walking the library tree — hours of I/O
that hls.finalized.output.json already paid for. This driver reads that manifest
(track_dir + bitrates per track, single-file layout throughout the v6 tree),
fans create_mpd out over a process pool, and writes has_dash=true back into the
manifest for every track whose manifest.mpd now exists. Re-runs skip tracks
whose .mpd is already on disk, so an interrupted pass just resumes.

The DB update afterwards is a single statement (every media-carrying track is in
the finalizer manifest):
  UPDATE track SET has_dash = true WHERE media_key IS NOT NULL;
run it only when this script reports zero failures, otherwise flip per-key.
"""

import importlib.util
import json
import os
import sys
from multiprocessing import Pool

import Postprocessor.HlsTranscode.output.path_definitions as HlsOutputPathDef
from Shared import utils

# dash-repackage.py has a hyphen in its name; load it by path.
_spec = importlib.util.spec_from_file_location(
    "dash_repackage",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "dash-repackage.py"),
)
_dash_repackage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dash_repackage)
create_mpd = _dash_repackage.create_mpd

finalized_manifest_path = utils.get_output_path(
    HlsOutputPathDef, HlsOutputPathDef.HLS_FINALIZED_FILELIST_OUTPUT_NAME
)

WORKERS = 12


def build_project(entry):
    track_dir = entry["track_dir"]
    packager_args = []
    for bitrate in entry["bitrates"]:
        variant = os.path.join(track_dir, "hls", f"{bitrate}k")
        packager_args.append({
            "path": variant,
            "stream": "audio",
            "playlist": os.path.join(variant, "playlist.m3u8"),
            "bandwidth": bitrate * 1000,
            "layout": "single_file",
            "media_file": os.path.join(variant, "stream.m4s"),
        })
    return {
        "project_path": track_dir,
        "output_mpd": os.path.join(track_dir, "manifest.mpd"),
        "packager_args": packager_args,
    }


def process_one(project):
    try:
        if os.path.exists(project["output_mpd"]):
            return (project["project_path"], "skipped", None)
        create_mpd(project)
        return (project["project_path"], "ok", None)
    except Exception as e:
        return (project["project_path"], "failed", f"{type(e).__name__}: {e}")


def main():
    with open(finalized_manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    projects = [build_project(entry) for entry in manifest.values()]
    print(f"{len(projects)} tracks to package ({WORKERS} workers)")

    ok = skipped = 0
    failures = []
    done_dirs = set()
    with Pool(WORKERS) as pool:
        for i, (track_dir, status, err) in enumerate(
            pool.imap_unordered(process_one, projects, chunksize=64), 1
        ):
            if status == "failed":
                failures.append((track_dir, err))
            else:
                done_dirs.add(track_dir)
                if status == "ok":
                    ok += 1
                else:
                    skipped += 1
            if i % 2000 == 0 or i == len(projects):
                print(f"[{i}/{len(projects)}] ok {ok}, resumed {skipped}, failed {len(failures)}", end="\r")

    print()
    for entry in manifest.values():
        if entry["track_dir"] in done_dirs:
            entry["has_dash"] = True

    with open(finalized_manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    print(f"Done: {ok} written, {skipped} already present, {len(failures)} failed.")
    if failures:
        with open("dash_repackage_failures.txt", "w", encoding="utf-8") as f:
            for track_dir, err in failures:
                f.write(f"{track_dir} :: {err}\n")
        print("See dash_repackage_failures.txt")
        sys.exit(1)


if __name__ == "__main__":
    main()
