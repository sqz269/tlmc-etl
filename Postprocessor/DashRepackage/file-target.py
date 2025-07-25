import os
import re
import json
import Postprocessor.DashRepackage.output.path_definitions as DashRepackagePathDef
from Shared import utils

dash_repackage_filelist_output = utils.get_output_path(
    DashRepackagePathDef,
    DashRepackagePathDef.DASH_REPACKAGE_FILELIST_OUTPUT_NAME,
)

def find_hls_roots(base_dir):
    hls_roots = []
    total_dirs = 0
    for root, dirs, files in os.walk(base_dir):
        total_dirs += 1
        if total_dirs % 50 == 0:
            print(f"📦 Scanned {total_dirs} directories so far...")

        if "hls" in dirs and "playlist.m3u8" in files:
            print(f"✅ Found HLS project: {root}")
            hls_roots.append(root)
    print(f"\n🔍 Finished scanning. Total directories scanned: {total_dirs}")
    return hls_roots

def generate_shaka_command(song_root):
    hls_path = os.path.join(song_root, "hls")
    stream_commands = []

    for bitrate_dir in sorted(os.listdir(hls_path)):
        variant_path = os.path.join(hls_path, bitrate_dir)
        if not os.path.isdir(variant_path):
            continue

        init_path = os.path.join(variant_path, "init.mp4")
        if not os.path.exists(init_path):
            print(f"⚠️  Skipping {variant_path} — no init.mp4")
            continue

        segment_files = sorted([
            f for f in os.listdir(variant_path)
            if re.match(r"segment_\d+\.m4s", f)
        ])
        if not segment_files:
            print(f"⚠️  Skipping {variant_path} — no .m4s segments")
            continue

        bitrate_value = re.sub(r"\D", "", bitrate_dir)
        if not bitrate_value:
            print(f"⚠️  Skipping {variant_path} — invalid bitrate name")
            continue
        
        playlist_path = os.path.join(variant_path, "playlist.m3u8")
        if not os.path.exists(playlist_path):
            print(f"⚠️  Skipping {variant_path} — no playlist.m3u8")
            continue

        stream_cmd = {
            "path": variant_path,
            "stream": "audio",
            "init_segment": init_path,
            "playlist": playlist_path,
            "segment_template": os.path.join(variant_path, "segment_$Number%03d$.m4s"),
            "bandwidth": int(bitrate_value) * 1000
        }
        stream_commands.append(stream_cmd)

    if stream_commands:
        output_mpd = os.path.join(song_root, "manifest.mpd")
        return {
            "project_path": song_root,
            "output_mpd": output_mpd,
            "packager_args": stream_commands
        }
    else:
        print(f"❌ No valid variants in: {song_root}")
        return None

def main(base_dir, output_json=dash_repackage_filelist_output):
    hls_projects = find_hls_roots(base_dir)
    results = []
    total_valid = 0

    for song_root in hls_projects:
        cmd_data = generate_shaka_command(song_root)
        if cmd_data:
            results.append(cmd_data)
            total_valid += 1

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Wrote {total_valid} valid packager command sets to {output_json}")
    print(f"🗂️  Skipped: {len(hls_projects) - total_valid}")

if __name__ == "__main__":
    tlmc_root = input("Enter the root directory: ")
    main(tlmc_root)
