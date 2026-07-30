"""Pushes per-track thwiki metadata to the v6 backend.

Replaces commit_basic_data_to_db_json.py (the v5 json-patch surface is gone).
Reads track_format_result.output.json (stage 4 matcher output) and writes:

  PUT api/internal/track/{id}/originals  {song_external_keys}
  PUT api/internal/track/{id}/credits    {credits: [{role, names}]}

Credits replace only the roles this pass owns (arranger/composer/vocalist/
lyricist); the loader's verbatim staff rows are untouched. Both endpoints are
idempotent, so the script is safe to re-run.
"""

import json

import ExternalInfo.ThwikiInfoProvider.output.path_definitions as ThwikiOutput
from ExternalInfo.ThwikiInfoProvider.PushChange.api_client import (
    make_session,
    send,
    track_typeid,
)
from Shared import utils

track_formatted_output_path = utils.get_output_path(
    ThwikiOutput, ThwikiOutput.THWIKI_TRACK_FORMAT_RESULT_OUTPUT
)

# fmt-key -> wire role (snake_case CreditRole)
ROLE_MAP = {
    "arrangement": "arranger",
    "composer": "composer",
    "vocal": "vocalist",
    "lyricist": "lyricist",
}


def credit_groups(entry):
    groups = []
    for key, role in ROLE_MAP.items():
        names = entry.get(key) or []
        names = [n.strip() for n in names if n and n.strip()]
        if names:
            groups.append({"role": role, "names": names})
    return groups


def main():
    with open(track_formatted_output_path, "r", encoding="utf-8") as f:
        tracks = json.load(f)

    session = make_session()

    total = len(tracks)
    originals_pushed = credits_pushed = skipped = 0
    failures = []
    for i, (track_id, entry) in enumerate(tracks.items(), 1):
        did_something = False
        wire_id = track_typeid(track_id)

        originals = entry.get("original") or []
        if originals:
            resp = send(
                session,
                "PUT",
                f"/api/internal/track/{wire_id}/originals",
                {"song_external_keys": originals},
            )
            if resp.status_code == 204:
                originals_pushed += 1
            else:
                failures.append(f"{track_id} originals: {resp.status_code} {resp.text[:200]}")
            did_something = True

        groups = credit_groups(entry)
        if groups:
            resp = send(
                session,
                "PUT",
                f"/api/internal/track/{wire_id}/credits",
                {"credits": groups},
            )
            if resp.status_code == 204:
                credits_pushed += 1
            else:
                failures.append(f"{track_id} credits: {resp.status_code} {resp.text[:200]}")
            did_something = True

        if not did_something:
            skipped += 1

        if i % 500 == 0 or i == total:
            print(
                f"[{i}/{total}] originals {originals_pushed}, credits {credits_pushed}, "
                f"empty {skipped}, failures {len(failures)}",
                end="\r",
            )

    print()
    print(
        f"Done: {originals_pushed} originals, {credits_pushed} credit sets, "
        f"{skipped} empty entries, {len(failures)} failures."
    )
    if failures:
        with open("push_track_metadata_failures.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(failures) + "\n")
        print("See push_track_metadata_failures.txt")


if __name__ == "__main__":
    main()
