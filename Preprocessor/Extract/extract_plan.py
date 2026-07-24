"""
Builds a reviewable extraction plan for a TLMC release.

Starting with the v6 release the collection is no longer a flat tree of `.rar`
files under a single root. It ships several parallel roots (`TLMC`,
`various album`, `Other album`, ...), the archives are `.7z` (with a handful of
`.zip`/`.rar`), and a small number of them do not follow the usual
"one archive == one album, files at archive root" shape.

This script reads every archive's *header* (no extraction) and works out, for
each one, where its contents should land in the merged output tree. The result
is written to `output/extraction_plan.output.json` for review before
`extract.py` acts on it.

Run order:
    1. python Preprocessor/Extract/extract_plan.py
    2. review output/extraction_plan.review.output.json and correct anything
       wrong in output/extraction_plan.output.json
    3. python Preprocessor/Extract/extract.py
"""

import os
import re
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import Preprocessor.Extract.output.path_definitions as ExtractOutputPaths
from Shared.json_utils import json_dump, json_load
from Shared.utils import get_file_relative, get_output_path

# Which parts of the release are ingested, which are left out, and why. Kept
# outside output/ so it is version controlled and survives replanning; see the
# Description field inside it for the schema.
EXCLUSIONS_PATH = get_file_relative(__file__, "extraction_exclusions.json")

ARCHIVE_EXTENSIONS = (".7z", ".zip", ".rar")

AUDIO_EXTENSIONS = {".flac", ".mp3", ".wav", ".wv", ".m4a"}

# Directories inside an archive that belong to an album rather than being an
# album of their own. Used to tell a multi-disc archive apart from an archive
# that bundles several albums together.
DISC_DIR_PATTERN = re.compile(
    r"^(disc|disk|cd)\s*[_\-]?\s*\d+|^\S+[_\s](a|b)side$|\s\d{2}$", re.IGNORECASE
)
AUXILIARY_DIR_NAMES = {
    "scans",
    "scan",
    "bk",
    "booklet",
    "artworks",
    "artwork",
    "covers",
    "images",
    "tracks",
    "ボイスドラマ",
    "カレンダー",
    "サウンドトラック",
}

# An album directory leads with either a release date or a bracketed
# event/catalog tag. Used to recognise archives that carry whole album
# directories instead of loose track files.
ALBUM_DIR_PATTERN = re.compile(r"^(\d{4}[.\-_]|[\[\({])")

# Layouts. `flat` creates <circle>/<archive name>/ and extracts into it. `nested`
# and `bundle` extract straight into <circle>/ because the archive already
# carries its own album directory (or directories).
LAYOUT_FLAT = "flat"
LAYOUT_NESTED = "nested"
LAYOUT_BUNDLE = "bundle"

EXTRACT_INTO_CIRCLE_DIR = {LAYOUT_NESTED, LAYOUT_BUNDLE}

plan_output_path = get_output_path(
    ExtractOutputPaths, ExtractOutputPaths.EXTRACTION_PLAN_OUTPUT_NAME
)
review_output_path = get_output_path(
    ExtractOutputPaths, ExtractOutputPaths.EXTRACTION_PLAN_REVIEW_OUTPUT_NAME
)


def list_archive(archive_path):
    """
    Reads an archive's index without extracting it.

    Returns (file_paths, dir_paths) as archive-relative paths using forward
    slashes, or None if 7z could not read the archive.
    """
    result = subprocess.run(
        ["7z", "l", "-slt", archive_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        return None

    body = result.stdout.decode("utf-8", errors="replace").split("\n----------\n", 1)
    if len(body) != 2:
        return None

    files = []
    dirs = []
    path = None
    for line in body[1].splitlines():
        if line.startswith("Path = "):
            path = line[len("Path = ") :].replace("\\", "/").rstrip("/")
        elif line.startswith("Attributes = ") and path is not None:
            if "D" in line[len("Attributes = ") :]:
                dirs.append(path)
            else:
                files.append(path)
            path = None

    return (files, dirs)


def top_level_dirs(files, dirs):
    """Returns the set of directory names at the root of the archive."""
    names = {d.split("/", 1)[0] for d in dirs}
    names |= {f.split("/", 1)[0] for f in files if "/" in f}
    return names


def has_audio(files, prefix=None):
    """
    True if any file is an audio track. When `prefix` is given only files
    somewhere beneath that top-level directory are considered.
    """
    for file in files:
        if prefix is not None and not file.startswith(prefix + "/"):
            continue
        if os.path.splitext(file)[1].lower() in AUDIO_EXTENSIONS:
            return True
    return False


def is_part_of_album(dir_name):
    """True for a disc directory or an auxiliary one (scans, artwork, ...)."""
    return bool(
        dir_name.lower() in AUXILIARY_DIR_NAMES or DISC_DIR_PATTERN.match(dir_name)
    )


def is_album_like(dir_name):
    """
    True if a directory name looks like an album directory rather than a disc
    or an auxiliary directory (scans, artwork, ...).
    """
    if is_part_of_album(dir_name):
        return False
    return bool(ALBUM_DIR_PATTERN.match(dir_name))


def classify(archive_path, files, dirs):
    """
    Works out how an archive maps onto the album tree.

    Returns (layout, albums, reasons) where `albums` lists the album directory
    names the archive produces and `reasons` explains any deviation from the
    common case so a human can confirm it.

    - flat:   files sit at the archive root, optionally alongside disc and scan
              subdirectories. One album, named after the archive.
    - nested: no files at the archive root and a single album directory inside.
              One album, named after that directory.
    - bundle: no files at the archive root and several album directories
              inside. One album per directory.
    """
    archive_name = os.path.splitext(os.path.basename(archive_path))[0]
    root_files = [f for f in files if "/" not in f]
    top_dirs = sorted(top_level_dirs(files, dirs))

    # Checked before anything else: an archive with no usable audio produces an
    # album with no tracks wherever its files happen to sit.
    if not files:
        return (LAYOUT_FLAT, [archive_name], ["Archive is empty or unreadable"])
    if not has_audio(files):
        return (LAYOUT_FLAT, [archive_name], ["No audio files in archive"])

    if root_files:
        return (LAYOUT_FLAT, [archive_name], [])

    album_dirs = [d for d in top_dirs if is_album_like(d) and has_audio(files, d)]

    if len(top_dirs) == 1 and album_dirs:
        return (
            LAYOUT_NESTED,
            [top_dirs[0]],
            ["Archive carries its own album directory; one level is stripped"],
        )

    if len(album_dirs) > 1:
        return (
            LAYOUT_BUNDLE,
            sorted(album_dirs),
            [f"Archive bundles {len(album_dirs)} albums; each becomes its own album"],
        )

    reasons = []
    if all(is_part_of_album(d) for d in top_dirs):
        # Nothing at the archive root but every subdirectory is a disc or a
        # scans/artwork folder, so this is an ordinary multi-disc album.
        pass
    elif len(top_dirs) == 1:
        reasons.append(
            f"No files at archive root and the single subdirectory "
            f"'{top_dirs[0]}' does not look like an album directory"
        )
    else:
        reasons.append(
            "No files at archive root and subdirectories are neither all discs "
            "nor all albums; treated as a single multi-disc album"
        )

    return (LAYOUT_FLAT, [archive_name], reasons)


def load_exclusions():
    """
    Loads the tracked exclusion file, filling in any section left out so the
    rest of the script can index it without guarding every lookup.
    """
    exclusions = json_load(EXCLUSIONS_PATH)
    defaults = {
        "SourceRoots": [],
        "ExcludedRoots": {},
        "IncludedSubtrees": {},
        "ArchiveIsCircleDirs": {},
        "ExcludedCircles": {},
        "ExcludedArchives": {},
        "CollisionResolutions": {},
        "CircleAliasOverrides": {},
    }
    for key, empty in defaults.items():
        exclusions.setdefault(key, empty)

    if not exclusions["SourceRoots"]:
        raise ValueError(f"No SourceRoots configured in {EXCLUSIONS_PATH}")

    return exclusions


def audit_roots(release_root, exclusions):
    """
    Returns the top-level directories of the release that are listed neither as
    a source nor as an exclusion. A root added by a future release would
    otherwise be dropped without anyone noticing.
    """
    accounted = set(exclusions["SourceRoots"]) | set(exclusions["ExcludedRoots"])
    accounted |= {subtree.split("/", 1)[0] for subtree in exclusions["IncludedSubtrees"]}

    return sorted(
        name
        for name in os.listdir(release_root)
        if os.path.isdir(os.path.join(release_root, name)) and name not in accounted
    )


def audit_stale(release_root, exclusions):
    """
    Returns exclusion entries whose path no longer exists in the release, so
    entries carried over from an older release can be pruned.
    """
    stale = []

    def check(section, path):
        if not os.path.exists(os.path.join(release_root, path)):
            stale.append({"Section": section, "Path": path})

    for section in ("ExcludedRoots", "IncludedSubtrees", "ArchiveIsCircleDirs",
                    "ExcludedCircles", "ExcludedArchives"):
        for path in exclusions[section]:
            check(section, path)

    for album, resolution in exclusions["CollisionResolutions"].items():
        check("CollisionResolutions", resolution["Keep"])

    return stale


def apply_collision_resolutions(entries, exclusions):
    """
    Drops the losing side of each resolved collision.

    A resolution names the archive to keep for one `<circle>/<album>`. Every
    other archive claiming that album loses it. An archive that bundles several
    albums keeps the ones it did not lose; an archive left with no albums at all
    is dropped entirely.
    """
    resolutions = exclusions["CollisionResolutions"]
    if not resolutions:
        return (entries, [], [])

    dropped = []
    kept_entries = []
    claimed = set()
    honoured = set()

    for entry in entries:
        surviving = []
        for album in entry["Albums"]:
            key = f"{entry['Circle']}/{album}"
            resolution = resolutions.get(key)
            if resolution is None:
                surviving.append(album)
                continue

            claimed.add(key)
            if entry["ReleasePath"] == resolution["Keep"]:
                honoured.add(key)
                surviving.append(album)
            else:
                dropped.append(
                    {
                        "Circle": entry["Circle"],
                        "Album": album,
                        "DroppedFrom": entry["ReleasePath"],
                        "KeptIn": resolution["Keep"],
                        "Reason": resolution.get("Reason", ""),
                    }
                )

        if not surviving:
            continue

        if surviving != entry["Albums"]:
            entry = dict(entry, Albums=surviving)
        kept_entries.append(entry)

    # A resolution whose Keep path never matched an archive claiming that album
    # removes the album from every archive that had it, losing it silently. Most
    # likely a typo, or a Keep pointing at an archive that is also excluded.
    orphaned = [
        {
            "Album": key,
            "Keep": resolutions[key]["Keep"],
            "Reason": "Keep path does not match any archive claiming this album; "
            "the album would be dropped from every source that has it",
        }
        for key in sorted(claimed - honoured)
    ]

    return (kept_entries, dropped, orphaned)


def suggest_collision_resolutions(collisions, root_priority):
    """
    Builds a ready-to-paste CollisionResolutions block for collisions that are
    still unresolved, defaulting to the archive from the highest priority root.
    Prefers a standalone archive over an `!MP3` circle bundle, since the latter
    is a lossy rip of the same release.
    """
    suggestions = {}
    for collision in collisions:
        def rank(release_path):
            root = release_path.split("/", 1)[0]
            return (
                "/!MP3/" in release_path,
                root_priority.get(root, len(root_priority)),
                release_path,
            )

        best = min(collision["ReleasePaths"], key=rank)
        suggestions[f"{collision['Circle']}/{collision['Album']}"] = {
            "Keep": best,
            "Reason": "SUGGESTED, review before use: highest priority source root, "
            "preferring a standalone archive over an !MP3 bundle.",
        }

    return suggestions


def circle_key(circle_dir_name):
    """
    Normalises a circle directory name for equivalence checks. Circle
    directories are written either as `[Name]` or `[Name] Alias`, and casing is
    not consistent between roots, so the bracketed part alone is the identity.
    """
    match = re.match(r"^\[([^\]]+)\]", circle_dir_name)
    name = match.group(1) if match else circle_dir_name
    return name.strip().lower()


def build_circle_aliases(circles_by_root):
    """
    Builds a {directory name: canonical directory name} map so one circle
    spelled differently across roots lands in a single output directory.

    The canonical spelling comes from the highest priority root, preferring the
    longer variant: `[Name] Alias` carries an alias that artist_scanner_ph2 can
    pick up, while `[Name]` does not.
    """
    variants = defaultdict(list)
    for priority, (_, circles) in enumerate(circles_by_root):
        for circle in circles:
            variants[circle_key(circle)].append((priority, circle))

    aliases = {}
    for entries in variants.values():
        names = {name for _, name in entries}
        if len(names) == 1:
            continue

        best_priority = min(priority for priority, _ in entries)
        canonical = sorted(
            {name for priority, name in entries if priority == best_priority},
            key=lambda name: (-len(name), name),
        )[0]

        for name in names:
            if name != canonical:
                aliases[name] = canonical

    return aliases


def collect_sources(release_root, exclusions):
    """
    Returns (sources, strays, excluded) where sources is
    [(root_label, circle_dir_name, circle_abs_path)] for every circle directory
    across the configured roots, strays lists files sitting directly in a root
    rather than inside a circle directory, and excluded records the circles
    skipped because of ExcludedCircles.
    """
    sources = []
    strays = []
    excluded = []

    def scan_root(label, root_path, forced_circle=None):
        if not os.path.isdir(root_path):
            print(f"  WARNING: source root not found, skipping: {root_path}")
            return

        if forced_circle is not None:
            sources.append((label, forced_circle, root_path))
            return

        for name in sorted(os.listdir(root_path)):
            path = os.path.join(root_path, name)
            if not os.path.isdir(path):
                strays.append(f"{label}/{name}")
                continue

            release_path = f"{label}/{name}"
            if release_path in exclusions["ExcludedCircles"]:
                excluded.append(
                    {
                        "ReleasePath": release_path,
                        "Reason": exclusions["ExcludedCircles"][release_path],
                    }
                )
                continue

            sources.append((label, name, path))

    for root in exclusions["SourceRoots"]:
        scan_root(root, os.path.join(release_root, root))

    for subtree, config in exclusions["IncludedSubtrees"].items():
        scan_root(
            subtree,
            os.path.join(release_root, subtree),
            forced_circle=config["Circle"],
        )

    return (sources, strays, excluded)


def collect_archives(release_root, sources, exclusions):
    """
    Returns (work, unreachable, excluded) where work is
    [(root_label, circle, path, release_path)] for every archive to process,
    unreachable lists content the album scanner would silently drop because it
    sits at the wrong depth, and excluded records archives skipped because of
    ExcludedArchives.
    """
    work = []
    unreachable = []
    excluded = []

    for label, circle, circle_path in sources:
        for name in sorted(os.listdir(circle_path)):
            path = os.path.join(circle_path, name)
            release_path = os.path.relpath(path, release_root).replace(os.sep, "/")

            if os.path.isdir(path):
                unreachable.append(
                    {
                        "ReleasePath": release_path,
                        "Reason": "Directory below circle level where an archive was expected",
                    }
                )
                continue

            extension = os.path.splitext(name)[1].lower()
            if extension in ARCHIVE_EXTENSIONS:
                if release_path in exclusions["ExcludedArchives"]:
                    excluded.append(
                        {
                            "ReleasePath": release_path,
                            "Reason": exclusions["ExcludedArchives"][release_path],
                        }
                    )
                    continue
                work.append((label, circle, path, release_path))
            elif extension in AUDIO_EXTENSIONS:
                unreachable.append(
                    {
                        "ReleasePath": release_path,
                        "Reason": "Loose audio file at circle level, not part of any album",
                    }
                )

    return (work, unreachable, excluded)


def resolve_circle(label, circle, archive_path, aliases, exclusions):
    """
    Returns (circle_dir_name, reasons). For the archive-is-a-circle directories
    the circle comes from the archive name rather than its parent directory.
    """
    if f"{label}/{circle}" in exclusions["ArchiveIsCircleDirs"]:
        name = os.path.splitext(os.path.basename(archive_path))[0]
        if not name.startswith("["):
            name = f"[{name}]"
        return (
            aliases.get(name, name),
            [f"Circle taken from the archive name because it sits under {circle}"],
        )

    return (aliases.get(circle, circle), [])


def main():
    release_root = input("Enter TLMC release root (the directory holding TLMC/): ")
    if not os.path.isdir(release_root):
        print("Invalid path")
        exit(1)

    destination = input("Enter destination root for extracted albums: ")

    print(f"Loading exclusions from {EXCLUSIONS_PATH}")
    exclusions = load_exclusions()

    unaccounted_roots = audit_roots(release_root, exclusions)
    if unaccounted_roots:
        print()
        print("The release has top-level directories listed neither as a source")
        print("nor as an exclusion. Add each to SourceRoots or ExcludedRoots:")
        for root in unaccounted_roots:
            print(f"  {root}")
        print()
        exit(1)

    stale = audit_stale(release_root, exclusions)
    for entry in stale:
        print(f"  WARNING: stale {entry['Section']} entry, path not in release: "
              f"{entry['Path']}")

    print("Collecting circle directories...")
    sources, strays, excluded_circles = collect_sources(release_root, exclusions)
    print(f"Found {len(sources)} circle directories")

    labels = list(exclusions["SourceRoots"]) + list(exclusions["IncludedSubtrees"])
    root_priority = {label: index for index, label in enumerate(labels)}
    circles_by_root = [
        (label, [circle for source_label, circle, _ in sources if source_label == label])
        for label in labels
    ]
    aliases = build_circle_aliases(circles_by_root)
    aliases.update(exclusions["CircleAliasOverrides"])
    print(f"Resolved {len(aliases)} circle directory names onto a canonical spelling")

    print("Collecting archives...")
    work, unreachable, excluded_archives = collect_archives(
        release_root, sources, exclusions
    )
    print(f"Found {len(work)} archives, reading indexes...")

    def probe(item):
        archive_path = item[2]
        listing = list_archive(archive_path)
        if listing is None:
            archive_name = os.path.splitext(os.path.basename(archive_path))[0]
            return (LAYOUT_FLAT, [archive_name], ["Could not read archive index"])
        return classify(archive_path, *listing)

    with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
        probed = list(executor.map(probe, work))

    entries = []
    for (label, circle, archive_path, release_path), (layout, albums, reasons) in zip(
        work, probed
    ):
        canonical_circle, circle_reasons = resolve_circle(
            label, circle, archive_path, aliases, exclusions
        )
        reasons = circle_reasons + reasons

        if layout in EXTRACT_INTO_CIRCLE_DIR:
            extract_into = os.path.join(destination, canonical_circle)
        else:
            extract_into = os.path.join(destination, canonical_circle, albums[0])

        entries.append(
            {
                "Archive": archive_path,
                "ReleasePath": release_path,
                "SourceRoot": label,
                "SourceCircle": circle,
                "Circle": canonical_circle,
                "Layout": layout,
                "Albums": albums,
                "ExtractInto": extract_into,
                "NeedsManualReview": bool(reasons),
                "NeedsManualReviewReason": reasons,
            }
        )

    print("Applying collision resolutions...")
    entries, resolved, orphaned = apply_collision_resolutions(entries, exclusions)
    if orphaned:
        print()
        print("These CollisionResolutions name a Keep path that no archive claiming")
        print("the album matches, so the album would be lost entirely:")
        for entry in orphaned:
            print(f"  {entry['Album']}")
            print(f"      Keep = {entry['Keep']}")
        print()
        exit(1)

    print("Checking for remaining album directory collisions...")
    destinations = defaultdict(list)
    for entry in entries:
        for album in entry["Albums"]:
            destinations[(entry["Circle"], album)].append(entry)

    collisions = [
        {
            "Circle": circle,
            "Album": album,
            "Archives": [e["Archive"] for e in claimants],
            "ReleasePaths": [e["ReleasePath"] for e in claimants],
        }
        for (circle, album), claimants in sorted(destinations.items())
        if len(claimants) > 1
    ]

    plan = {
        "ReleaseRoot": release_root,
        "Destination": destination,
        "ExclusionsFile": EXCLUSIONS_PATH,
        "SourceRoots": exclusions["SourceRoots"],
        "IncludedSubtrees": exclusions["IncludedSubtrees"],
        "CircleAliases": aliases,
        "Entries": entries,
    }
    json_dump(plan, plan_output_path)

    review = {
        "Collisions": collisions,
        "SuggestedCollisionResolutions": suggest_collision_resolutions(
            collisions, root_priority
        ),
        "Excluded": {
            "Roots": exclusions["ExcludedRoots"],
            "Circles": excluded_circles,
            "Archives": excluded_archives,
            "AlbumsLostToCollisionResolution": resolved,
        },
        "StaleExclusionEntries": stale,
        "UnreachableContent": unreachable,
        "StrayFilesAtRootLevel": strays,
        "NeedsManualReview": [e for e in entries if e["NeedsManualReview"]],
    }
    json_dump(review, review_output_path)

    layouts = defaultdict(int)
    for entry in entries:
        layouts[entry["Layout"]] += 1

    print()
    print(f"Plan written to {plan_output_path}")
    print(f"Review written to {review_output_path}")
    print()
    print(f"  archives            : {len(entries)}")
    print(f"  albums produced     : {sum(len(e['Albums']) for e in entries)}")
    for layout, count in sorted(layouts.items()):
        print(f"  layout {layout:<13}: {count}")
    print(f"  circle aliases      : {len(aliases)}")
    print()
    print(f"  excluded roots      : {len(exclusions['ExcludedRoots'])}")
    print(f"  excluded circles    : {len(excluded_circles)}")
    print(f"  excluded archives   : {len(excluded_archives)}")
    print(f"  albums dropped by collision resolution: {len(resolved)}")
    if stale:
        print(f"  stale exclusions    : {len(stale)}  <- prune from the exclusions file")
    print()
    print(f"  collisions remaining: {len(collisions)}  <- resolve before extracting")
    print(f"  needs review        : {sum(1 for e in entries if e['NeedsManualReview'])}")
    print(f"  unreachable content : {len(unreachable)}")


if __name__ == "__main__":
    main()
