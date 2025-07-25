# Info Providers Run Order and Instructions

## Tutorial: Detaching & Keeping Long Running Command Alive

For some scripts that needed to process track files they will take a long time to run (ranging from hours to days depending on your computer spec). And if you are running the script from a SSH session, the script will be terminated when a SSH session terminates. But we need a way to keep the script running even without an active SSH session, which is achieved though TMUX

### 0.1 Installing tmux

- Run `sudo apt install tmux`

### 0.2 Opening a new session

- Run `tmux`
- Note if you receive the following error: `tmux: missing or unsuitable terminal:`
  - Run `export TERM=xterm` (or replace xterm with your terminal)
  - Then run `tmux`

### 0.3 Run your command after opening a new session

### 0.4 Detaching a session

- Press `Ctrl + b` then `d`

### 0.5 Reattaching a session

- Run `tmux at` to reattach the last session
- Run `tmux at -t <session-name>` to reattach a specific session
  - Hint: you can find the session name by running `tmux ls`

### 0.6 Terminating a session

- Run `tmux kill-session -t <session-name>`
- Or press `Ctrl + b` then `x` to kill the current session

## SECTION: ENVIRONMENT SETUP

This section guides you through setting up the necessary software for processing. Custom versions of FFmpeg and installations of .NET and Python are required.

### FFmpeg

We require a custom-compiled version of FFmpeg with libfdk-aac, which isn't included in standard binary distributions. The instructions provided are for Ubuntu; adjustments may be needed for other Linux distributions.

#### Compiling FFmpeg

##### Install Dependencies

Run the following command to install the basic dependencies:

```sh
sudo apt-get update -qq && sudo apt-get -y install \
autoconf \
automake \
build-essential \
cmake \
git-core \
libass-dev \
libfreetype6-dev \
libgnutls28-dev \
libmp3lame-dev \
libsdl2-dev \
libtool \
libva-dev \
libvdpau-dev \
libvorbis-dev \
libxcb1-dev \
libxcb-shm0-dev \
libxcb-xfixes0-dev \
meson \
ninja-build \
pkg-config \
texinfo \
wget \
yasm \
zlib1g-dev
```

##### Install Additional Dependencies for `libfdk-aac`

Install further dependencies required for `libfdk-aac`:

```sh
sudo apt-get install nasm, libx264-dev, libx265-dev libnuma-dev, libfdk-aac-dev, libopus-dev, 
```

##### Compile and Install FFmpeg with `libfdk-aac` Enabled

Follow these steps to compile and install FFmpeg with `libfdk-aac`:

```sh
cd ~/ffmpeg_sources && \
wget -O ffmpeg-snapshot.tar.bz2 https://ffmpeg.org/releases/ffmpeg-snapshot.tar.bz2 && \
tar xjvf ffmpeg-snapshot.tar.bz2 && \
cd ffmpeg && \
PATH="$HOME/bin:$PATH" PKG_CONFIG_PATH="$HOME/ffmpeg_build/lib/pkgconfig" ./configure \
--prefix="$HOME/ffmpeg_build" \
--pkg-config-flags="--static" \
--extra-libs="-lpthread -lm" \
--ld="g++" \
--bindir="$HOME/bin" \
--enable-gpl \
--enable-gnutls \
--enable-libass \
--enable-libfdk-aac \
--enable-libfreetype \
--enable-libmp3lame \
--enable-libopus \
--enable-libvorbis \
--enable-libvpx \
--enable-libx264 \
--enable-libx265 \
--enable-shared \
--enable-nonfree && \
PATH="$HOME/bin:$PATH" make -j 8 && \
make install && \
hash -r
```

### .NET 6+

Install the .NET SDK (version 6 or above) as per your operating system's instructions.

### Python Environment

**Note: Python 3.10 or above is required**

1. Navigate to the repository's directory: `cd TlmcInfoProviderV2`.
2. Create a virtual environment: `python -m venv .`
3. Adding project root to python execution context
    - For Linux users, navigate to `bin/activate` and add `export PYTHONPATH="$(pwd):$PYTHONPATH"` to the activation script
    - For Windows users, navigate to `bin/Activate.ps1` and add `set PYTHONPATH=%CD%;%PYTHONPATH%` to the activation script
4. Activating the environment
    - Linux: `source bin/activate`
    - Windows: `./bin/Activate.ps1`
5. Install the required packages `pip install -r requirements.txt`

### 7 Zip

Install 7-zip 64 bit as per your operating system's instructions

## SECTION: PREPROCESSING

### 0. RAR File Snapshot

This section details the process of snapshotting the downloaded collection files for their hash and size. This step is needed to ensure we can correctly and efficiently identify added albums from new versions of the collection and retroactively apply updates instead of the need to go through the process again with every new release.

### Prerequisites

- N/A

### Preparation

- Ensure that you have moved `!Misc` in the TLMC release to the root folder so that it's properly merged with the rest of the directory.
  - Can be achieved via `cp * .. -r` in the `!Misc` directory or `cp !Misc/* . -r` in TLMC root directory then with `rm -r !Misc`

### Execution

- Execute the snapshot script by running `python Preprocessor/Extract/unextracted_snapshot.py`
- Ensure you keep/backup the output located at `Preprocessor/Extract/output/unextracted_rar_snapshot.output.json` for the time when upgrading releases.

### 1. Archive Extraction

This section details the process of extracting .rar files contained in the TLMC (Touhou Lossless Music Collection) directory. Before processing the files, they must be extracted.

#### Prerequisites

- Ensure 7z (7-Zip) is installed and added to your system's PATH. You can verify this by running `7z` in your command line; it should not return an error.
- Your 7z must support large files (HugeFiles). This is typically available in the 64-bit version. Check this by verifying the flag `HugeFiles=on` with the command `7z`.

#### Preparation

- Confirm that the drive where the TLMC files are stored has at least 300GB of free space.
- **Important Warning**: The .rar files will be permanently deleted after extraction. Ensure you have backups if necessary. (Or disable this behavior by editing `extract.py` and remove line `os.unlink(file)`)

#### Execution

1. Execute the script by running `python ./extract.py`. This will start the extraction process.

### 2. Extracted Filesystem Snapshot

This section details the process of snapshotting the extracted files for their hash and size. Although there isn't any plans to use this file, the process and script is documented in case extracted files hashes are needed to upgrade.

#### Prerequisites

- All `.rar` files has been extracted and the `.rar` files has been moved/deleted from the TLMC root

### Preparation

- N/A

### Execution

- Execute the snapshot script by running `python Preprocessor/Extract/extracted_snapshot.py`
- Ensure you keep/backup the output located at `Preprocessor/Extract/output/extracted_filesystem_snapshot.output.json` for the time when upgrading releases.

### 3. Track Audio Normalization

This section explains how to normalize the volume levels of audio tracks. Since web apps and the HLS protocol don't support ReplayGain tags, we'll directly modify the files to normalize their volume. This is a lossy process, so it's advised to back up your files if you wish to retain lossless copies.

The normalization uses the EBU R128 loudness normalization profile.

Detailed Parameter:

- Integrated Loudness Target `I=-24` LUFS
- Loudness range target`LRA=7` LU
- True peak target `tp=-2.0` dBTP

You can edit this profile by editing the file `Preprocessor/AudioNormalizer/normalizer.py` and under the variable `NORMALIZATION_TARGET`.

This normalization process will be a two pass process, with the first pass detecting the file's loudness levels and the second pass applying the gains to the file to achieve the targeted profile.

More details about the dual pass and loudnorm filter can be found here: <https://k.ylo.ph/2016/04/04/loudnorm.html>

#### Important Noticies

- **Time Requirement**: This process is time-intensive. To minimize interruptions, consider running it in a detached tmux session.
- **Resource Intensity**: This is a CPU-intensive task. Limited CPU resources can significantly slow down the process. The script is designed to utilize all available CPU cores which may cause system instability. Avoid other CPU intensive jobs when running this script
- **Lossy Conversion**: This process will replace the original file with the normalized version and the conversion is a lossy process.

#### Prerequisites

- Ensure that ffmpeg is installed and added to your system's PATH. You can verify this by running `ffmpeg` in your command line; it should not return an error.

#### Preparation

- N/A

#### Execution

- Run `python ./Preprocessor/AudioNormalizer/normalizer_pass1.py` to detect the file's loudness and generate normalization parameters for pass 2.
- Run `python ./Preprocessor/AudioNormalizer/normalizer_pass2.py` to apply the loudnorm parameters by modifying the file.

### 4. Cue Splitting

This section details the procedure for splitting a single, aggregated album track (segmented by a .cue file) into separate files for each individual track. This step is necessary because the backend cannot parse cue files to serve individual tracks, and separate track files are required for proper functionality.

#### Important Noticies

- **Manual Intervention**: The automatic process for identifying files that need splitting is not foolproof and might incorrectly mark already split files as needing splitting. It is crucial to manually check the accuracy of the split files.
- **Time Requirement**: This process is time-intensive. To minimize interruptions, consider running it in a detached tmux session.
- **Resource Intensity**: This is a CPU-intensive task. Limited CPU resources can significantly slow down the process. The script is designed to utilize all available CPU cores which may cause system instability. Avoid other CPU intensive jobs when running this script

#### Prerequisites

- Ensure that .NET 6 SDK or above is installed and added to your system's PATH and is set as your default .NET SDK. You can verify this by running `dotnet --list-sdks` and observe the output.
- Ensure that ffprobe (this should come with your ffmpeg installation) is installed and added to your system's PATH. You can verify this by running `ffprobe` in your command line; it should not return an error.

#### Preparation

- Build the Cue file parser project located under `Preprocessor/CueSplitter/CueSplitInfoProvider`
    1. Change working directory into `Preprocessor/CueSplitter/CueSplitInfoProvider`
    2. Restore and collect packages using `dotnet restore`
    3. Sometimes for some reason UtfUnknown is not installed with `restore` command. Run this command to install it `dotnet add package UTF.Unknown --version 2.5.1`
    4. Build project using `dotnet publish -c Release`

#### Execution

1. **Run the Cue Scanner Script**:
   - Execute `Preprocessor/CueSplitter/cue_scanner.py` to generate a list of albums that may require splitting.
   - This script produces a JSON file `Preprocessor/CueSplitter/potential.json`. The file contains a list of JSON objects with metrics and a confidence score indicating the likelihood of needing splitting (0 = least likely, 1 = most likely).

2. **Review and Edit the Generated File**:
   - Examine the `potential.json` file to identify and remove entries for albums that don't require splitting.
   - For albums with multiple discs, indicated by multiple cue files, reorganize both the cue and corresponding FLAC files into separate directories per disc.  
    **Example JSON Entry With Multiple Discs**:

      ```json
        {
          "root": "/external_data/staging/TLMC v4/[まらしぃ]/2021.12.14 [MRCD-038~9] 幻想遊戯 Piano Collection",
          "cue": [
            "/external_data/staging/TLMC v4/[まらしぃ]/2021.12.14 [MRCD-038~9] 幻想遊戯 Piano Collection/まらしぃ - 幻想遊戯 Piano Collection ～ Museum of Marasy CD2.cue",
            "/external_data/staging/TLMC v4/[まらしぃ]/2021.12.14 [MRCD-038~9] 幻想遊戯 Piano Collection/まらしぃ - 幻想遊戯 Piano Collection ～ Museum of Marasy CD1.cue"
          ],
          "audio": [
            "/external_data/staging/TLMC v4/[まらしぃ]/2021.12.14 [MRCD-038~9] 幻想遊戯 Piano Collection/まらしぃ - 幻想遊戯 Piano Collection ～ Museum of Marasy CD1.flac",
            "/external_data/staging/TLMC v4/[まらしぃ]/2021.12.14 [MRCD-038~9] 幻想遊戯 Piano Collection/まらしぃ - 幻想遊戯 Piano Collection ～ Museum of Marasy CD2.flac"
          ],
          "total_flac_count": 2,
          "flag_reason": "Cue file found",
          "confidence": 0.9
        }
        ```

    - You need to move both the cue and the associated flac files for each disc into their own directory.
    - **Example Directory Structure After Reorganization**:
      - `/external_data/staging/TLMC v4/[まらしぃ]/2021.12.14 [MRCD-038~9] 幻想遊戯 Piano Collection/CD1`
        - `まらしぃ - 幻想遊戯 Piano Collection ～ Museum of Marasy CD1.cue`
        - `まらしぃ - 幻想遊戯 Piano Collection ～ Museum of Marasy CD1.flac`
      - `/external_data/staging/TLMC v4/[まらしぃ]/2021.12.14 [MRCD-038~9] 幻想遊戯 Piano Collection/CD2`
        - `まらしぃ - 幻想遊戯 Piano Collection ～ Museum of Marasy CD2.cue`
        - `まらしぃ - 幻想遊戯 Piano Collection ～ Museum of Marasy CD2.flac`
    - **Notes**:
      - Correct file organization is essential for accurate disc tagging later in the process.
      - There's no need to manually update `potential.json` after reorganizing the directories.

3. After removing splitted albums from `potential.json`, run `Preprocessor\CueSplitter\cue_designate.py` to set up the targeted albums for processing.
   - This script uses `potential.json` as input.
   - It generates a complete data set from `potential.json` for the cue splitter script to use.

4. Execute `Preprocessor\CueSplitter\cue_splitter.py` to start the splitting process.  
    - **Important Notices:**
      - _**Irreversible Operation**_: This process permanently deletes the original, unsplit FLAC files. Ensure you have backups if there's any possibility you'll need to revert the changes.
      - **Time-Consuming**: The operation takes a significant amount of time. Avoid interrupting the process once it has started.
      - **Resource Intensity**: This is a CPU-intensive task. Limited CPU resources can significantly slow down the process. The script is designed to utilize all available CPU cores which may cause system instability. Avoid other CPU intensive jobs when running this script

## SECTION: METADATA EXTRACTION

### 1. DISC IDENTIFICATION

To structure tracks and extract metadata accurately, it's essential to identify, tag, and separate multi-disc albums. The process varies in complexity:

- In some cases, discs are neatly organized into separate directories (e.g., one for Disc 1, another for Disc 2), allowing for straightforward automated identification.
- In other instances, all tracks may be in a single directory with the disc number indicated in the file name (e.g., `01.03 track.flac` for Disc 1, `02.05 track.flac` for Disc 2). Such scenarios are less conducive to automation and may require more manual oversight.

#### Important Notices

- _**Manual Intervention**_: The automatic process for identifying discs is not foolproof and might incorrectly mark directories and files as discs. It is crucial to manually check the accuracy of the split files. The manual processing may be extensive.

#### Prerequisites

- N/A

#### Preparation

- N/A

#### Exectuion

1. **Generating Potential Disc List**
    - Run `InfoCollector/AlbumInfo/disc_scanner.py` to compile a list of albums potentially containing multiple discs.

2. **Manual Disc Verification**
    - Run `InfoCollector/AlbumInfo/disc_man_checker.py` for an interactive session to manually verify and designate discs. This script focuses on albums with lower confidence scores, skipping over those with clear indications of multiple discs. Durign this session:
        - Manually assess and categorize ambiguous albums into disc-specific directories (If they do indeed contain discs).
        - After addressing all ambiguities, the script will organize tracks into their designated directories and create a comprehensive list of disc directories.
    - Upon completion, the script outputs a file named `InfoCollecto/AlbumInfo/output/disc_manual_checker.output.json`. Review this file to:
        - Correct any instances of `disc_numbers: -1` to the appropriate disc number. The script defaults to -1 when it can't determine the number from the file name.
        - Optionally, add descriptive names to each disc, based off it's directory name

2. **Sequence Checking**
    - Run `Processor/InfoCollector/AlbumInfo/disc_auto_assign.py` to automatically check if disc assignment forms an sequence, and automatically assign numbers if they are not in a sequence.

### 2. Information Extraction Phase 1

This process transforms an unstructured directory of album tracks into a structured JSON format. The goal is to organize and identify tracks, discs, and associated assets for easier access during information extraction.

#### Important Notices

- _**Manual Intervention**_: The automated processes may not accurately organize all tracks due to non-standard file naming or missing files. Refer to the Execution section for detailed instructions on manual review.

#### Prerequisites

- N/A

#### Preparation

- N/A

#### Exectuion

1. Run `InfoCollector\AlbumInfo\info_scanner_ph1.py` to initiate the first phase of information extraction. This script scans the album directory, categorizes content, and generates a preliminary JSON structure for each album.
2. Review all documents that is flagged with `"NeedsManualReview": true` in file `InfoCollector/AlbumInfo/output/info_scanner.phase1.output.json`. Correct any issues with file or directory structures as needed. See field `"NeedsManualReviewReason": []` for potential issues. Do not edit the file directly, rather correct any mistakes from disc tagging and file organization level instead. (If Unidentified tracks are left unresolved, these tracks will be added as an asset and the album marked as containing asset of interest during Section 7)
3. If certain albums are incomplete or missing files that can't be fixed, you may skip these files.
4. After making corrections, rerun the `info_scanner_ph1.py` script. Repeat this process as many times as necessary.

### 2. Information Extraction Phase 2

In the second phase of transforming an unstructured directory of album tracks into a structured JSON format, the focus is on extracting and compiling metadata for albums and tracks from various sources such as file properties and naming conventions.

#### Prerequisites

- N/A

#### Preparation

- N/A

#### Exectuion

1. **Metadata Extraction**: Run `InfoCollector\AlbumInfo\info_scanner_ph2.py`. This script aggregates metadata from file properties and names, populating album and track details into a structured JSON.
2. **Review Generated Files**
    - Inspect the output JSON files `InfoCollector/AlbumInfo/output/info_scanner.phase2.albuminfo.output.json` and `InfoCollector/AlbumInfo/output/info_scanner.phase2.trackinfo.output.json`. Address any entries flagged with `"NeedsManualReview": true`. Pay special attention to:
        - **Empty Track Titles or Album Names**: Ensure all tracks and albums have appropriate titles. Empty fields often indicate missing or unreadable metadata and empty album names **_must_** be manually corrected. While empty track names will be automatically filled in with the file name (excluding extensions) during phase 3.
        - **Track Numbering**: While fixing empty track numbers is **_optional_**, any track with an index of -1 will be uniquely indexed in Phase 3. However, correctly numbering tracks here can aid in organizing and understanding the album's structure.

### 3. Information Extraction Phase 3

Phase 3 will aggregate all collected info from the previous two phases and organize them into one single file with the complete metadata for each track and album. The script will automatically assign any unassigned track index with a sequential number and unassigned track name from the basename. However, this script **_WILL NOT_** handle empty album names, so it is necessary to assign a proper name to ALL albums in the output of phase 2.

#### Prerequisites

- N/A

#### Preparation

- N/A

#### Exectuion

1. Run `Processor/InfoCollector/AlbumInfo/info_scanner_ph3.py`

### 4. Artist Identification Phase 1 (OPTIONAL)

This step is only nessarily if the files will be added to an existing database

#### Prerequisites

- N/A

#### Preparation

- N/A

#### Execution

1. Run the following sql query on your existing music data database

    ```sql
    drop materialized view if exists albumcirclemergeassertpath;
    create materialized view albumcirclemergeassertpath as
        select distinct string_agg("Circles"."Id"::text, ',') as "CircleIds", split_part("HlsPlaylistPath", '/', 5) as "CirclePathNames"
        from "Albums" as alb
        join "Tracks" on "Tracks"."Id" = (
            select "Tracks"."Id"
            from "Tracks"
            where alb."Id" = "Tracks"."AlbumId"
            order by "Id" -- ensure the returned track is deterministic
            limit 1
        )
        join "HlsPlaylist" HP on "Tracks"."Id" = HP."TrackId"
        join "AlbumCircle" on alb."Id" = "AlbumCircle"."AlbumsId"
        join "Circles" on "AlbumCircle"."AlbumArtistId" = "Circles"."Id"
        where HP."Type" = 'Master'
        group by "AlbumId", "HlsPlaylistPath";

    select jsonb_object_agg(key, value) as aggregated_json
    from (
        select
            acm."CirclePathNames" as key,
            to_jsonb(array_agg(ci.id)) as value  -- Cast the aggregated array directly to JSON
        from albumcirclemergeassertpath acm
        cross join lateral unnest(string_to_array(acm."CircleIds", ',')) as ci(id)
        group by acm."CirclePathNames"
    ) as sub;
    ```

2. Copy paste the query output (json) into `InfoCollector/ArtistInfo/output/artist_scanner.existing.name_dump.output.json`

### 5. Artist Identification Phase 2

#### Prerequisites

- N/A

#### Preparation

- N/A

#### Execution

1. Run `InfoCollector/ArtistInfo/artist_scanner_ph2.py`
2. Review the generated file at `InfoCollector/ArtistInfo/output/artist_scanner.discovery.new_artists.output.json` for
    - **Collaborative Entries**
        - Look for entries representing collaborative works (e.g., `[TUMENECO & RED  FOREST]`). Ensure that each artist or group is correctly identified and listed. For collaborations, separate individual artists or groups into the `"linked"` field while preserving the original formatting.
        - Verify that each artist listed in the `"linked"` section has a corresponding standalone entry elsewhere in the file. If an artist appears exclusively in collaborations (meaning, no standalone entry), encapsulate their name in brackets (e.g., [Artist Name]) and include it in the "linked" list. This ensures all participants are accounted for, even if their only contributions are collaborative.
        - Example: Notice here `TUMENECO` has it's original form as it appeared in a standalone entry `"[冷猫] TUMENECO"`

            ```json
            "[tumeneco & red forest]": {
                "raw": "[TUMENECO & RED FOREST]",
                "name": "TUMENECO & RED FOREST",
                "alias": [],
                "linked": [
                    "[冷猫] TUMENECO",
                    "[RED FOREST METAL ORCHESTRA]"
                ],
                "known_id": []
            }
            ```

        - Example 2: In this case, observe how `AbsoЯute Zero` is stylized as `AbsoRute Zero` in some instances. Despite the stylistic difference, it refers to the same entity as the standalone entry. Apply careful judgment to accurately link variant names to the correct artist, especially when they involve stylistic or language differences. The example below demonstrates how to handle such variations while ensuring all artists are correctly disentangled and linked:

            ```json
            "[イノライ×少女理論観測所×absorute zero]": {
                "raw": "[イノライ×少女理論観測所×AbsoRute Zero]",
                "name": "イノライ×少女理論観測所×AbsoRute Zero",
                "alias": [],
                "linked": [
                    "[イノライ]",
                    "[少女理論観測所]",
                    "[AbsoЯute Zero]"
                ],
                "known_id": []
            }
            ```

        - Example 3: This is a special case where one of the artist in collaberative entries have no standalong entry. Here the circle `5884組` never appeared as an standalone circle in the list, but appears in the collab entry. Notice we still put a linked entry but with brackets wrapped around the name as if it appears as an standalone entry. In this case, the phase 3 processing will take care of the unlisted circles in collab and create standalone entry for them.

            ```json
            "[cool＆create／5884組]": {
                "raw": "[COOL＆CREATE／5884組]",
                "name": "COOL＆CREATE／5884組",
                "alias": [],
                "linked": [
                    "[COOL&CREATE]",
                    "[5884組]"
                ]
            }
            ```

### 6. Artist Identification Phase 2

This script will assign an unique identifier for all circles and reference the linked circles in a collab via unique identifiers. It will also create a new circle based of non standalone linked entry.

In addition, this script will also attempt to identify any potential duplicated circles in the list. If any of the circles have been identified as duplicates, it will prompt the user to

#### Prerequisites

- N/A

#### Preparation

- N/A

#### Execution

1. Run `python Processor/InfoCollector/ArtistInfo/artist_scanner_ph3.py`

### 7. Unique Identifier Assignment and Artist & Ablum Metadata Merge

This script will assign an Universally Unique Identifier (UUID) to all albums, discs, tracks, and assets. This script will assign any unidentified/uncategorized tracks into the album's asset. This process will assign the proper circle id for each album from section 6. In addition, it will also mark albums as `Containing Asset of Interest` if the assets may have other media files that are not music. Note that both Album ID and Disc ID may be assigned for albums with only one disc, which in that case the pushing to db operation will prioritize the album ID over the disc ID for the created Album row. However, if there are multiple discs, then the album ID will be used for the Master Disc for the schema while Disc ID are for the actual Discs for proper normalization.

#### Prerequisites

- N/A

#### Preparation

- N/A

## SECTION: HLS TRANSCODING

flac is a lossless format meaning that the file prioritizes quality over compression, but it's large file size make it undesireable in mobile streaming which have constrainted bandwidth. This section details the process to transcode flac files into HLS (fMP4 format) which is optimized for streaming and allows for adaptive bitrate switching. However, do note that the HLS transcoding may SIGNIFICANTLY alter the original file's audio quality which depends on the bitrate of the conversion. It is advised to backup the original flac files if needed.

### 1. Distribute

Transcoding media files is often computationally expensive. In the case of video file transcoding, GPU drivers usually provide hardware accerlation for such tasks to reduce transcoding file. However, as of 2024, there is no dedicated support for hardware accerlated flac to fMP4 conversion. Meaning that this process will take a significant amount of time to run (ranging from days to weeks, depending on the machine's CPU speed). To reduce the length of the process, multiple devices may be used to distribute this task and reduce the computation time.

### 2. Transcode

**WARNING: THIS PROCESS IS EXTREMELY COMPUTATIONALLY INTENSIVE. ENSURE YOU HAVE ENOUGH COMPUTATION POWER AND UPTIME BEFORE PROCEEDING**

#### Prerequisites

- Ensure that `ffmpeg` with `libfdk-aac` support enabled is installed and available via command `ffmpeg`
- Ensure that the CPU is powerful enough to complete the process in the forseeable future. Recommend to use a CPU at least 8 cores.

#### Preparation

- N/A

#### Execution

1. Run `Postprocessor/HlsTranscode/hls_assignment.py` to generate a target list
2. Run `Postprocessor/HlsTranscode/hls_runner.py` to transcode the targeted files
3. Run `Postprocessor/HlsTranscode/hls_finalizer.py` to finalize hls transcoding and generate master playlists.

## SECTION: MPEG DASH REPACKAGING

Although HLS is somewhat of a well known format for adaptive bitrate straming. But it appears that MPEG DASH are more widely supported for non-apple platforms, which is more compatible with web streaming (MSE). 

To enable MPEG DASH support, we simply needs to repackage the playlist into DASH's `mpd` format. This process is purely for restructuring the metadata, no transcoding will be done since fMP4 is fully compatible with DASH.

### Prepration

### Execution

1. Identify list of existing HLS directories
    - Run `Postprocessor/DashRepackage/file-target.py`
2. Repackage HLS into DASH Manifest
    - Run `Postprocessor/DashRepackage/dash-repackage.py`

## Miscellaneous Scripts Documentation

### `Processor/InfoCollector/Aggregator/existing_id_metadata_update.py`
- Used to keep existing assigned Album/Track ids generated by aggregator but update album/track metadata from a `info_scanner_ph3.py` run. Mainly used for maintain IDs while updating metadata if the algorithm for extracting data from filename changes from `info_scanner_ph2.py`


# EXTERNAL DATA SOURCE RUN INSTRUCTIONS

Ensure all steps in above sections are completed before proceeding

## Adding Album/Track Metadata from Thwiki.cc

### 1. Link Albums with Thwiki Articles By Search

Run `ExternalInfo\ThwikiInfoProvider\ThwikiAlbumPageQueryScraper\song_page_scraper.py`

### 2. Scrape Album/Track Metadata from Thwiki

Run `ExternalInfo\ThwikiInfoProvider\ThwikiAlbumPageScraper\song_page_scraper.py`

### 3. Map Original Tracks Templates

Run `ExternalInfo\ThwikiInfoProvider\ThwikiOriginalTrackDiscovery\original_track_discovery.py`

### 4. Match Thwiki Album & Tracks with Local Album & Tracks

Run `ExternalInfo\ThwikiInfoProvider\ThwikiAlbumInfoMatcher\song_info_matcher.py`
