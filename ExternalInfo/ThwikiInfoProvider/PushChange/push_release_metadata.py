"""Pushes album-level thwiki enrichment to the v6 backend.

Reads album_format_result.output.json (stage 4 matcher output) and calls

  PUT api/internal/release/{id}/source-meta  {catalog_number, website, data_source}

Semantics live server-side: catalog fills only when the local metadata had
none, website/data_source append set-wise. genre and cover_char stay local
for now — they land with the tag projection later, not on release rows.
"""

import json

import ExternalInfo.ThwikiInfoProvider.output.path_definitions as ThwikiOutput
from ExternalInfo.ThwikiInfoProvider.PushChange.api_client import (
    make_session,
    release_typeid,
    send,
)
from Shared import utils

album_formatted_output_path = utils.get_output_path(
    ThwikiOutput, ThwikiOutput.THWIKI_ALBUM_FORMAT_RESULT_OUTPUT
)


def main():
    with open(album_formatted_output_path, "r", encoding="utf-8") as f:
        albums = json.load(f)

    session = make_session()

    total = len(albums)
    pushed = skipped = 0
    failures = []
    for i, (album_id, entry) in enumerate(albums.items(), 1):
        payload = {
            "catalog_number": (entry.get("catalog") or "").strip() or None,
            "website": (entry.get("website") or "").strip() or None,
            "data_source": (entry.get("data_source") or "").strip() or None,
        }
        if not any(payload.values()):
            skipped += 1
            continue

        resp = send(session, "PUT", f"/api/internal/release/{release_typeid(album_id)}/source-meta", payload)
        if resp.status_code == 204:
            pushed += 1
        else:
            failures.append(f"{album_id}: {resp.status_code} {resp.text[:200]}")

        if i % 500 == 0 or i == total:
            print(f"[{i}/{total}] pushed {pushed}, empty {skipped}, failures {len(failures)}", end="\r")

    print()
    print(f"Done: {pushed} releases enriched, {skipped} empty, {len(failures)} failures.")
    if failures:
        with open("push_release_metadata_failures.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(failures) + "\n")
        print("See push_release_metadata_failures.txt")


if __name__ == "__main__":
    main()
