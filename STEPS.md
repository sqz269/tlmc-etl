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

### 1. Archive Extraction

This section details the process of extracting .rar files contained in the TLMC (Touhou Lossless Music Collection) directory. Before processing the files, they must be extracted.

#### Prerequisites

- Ensure 7z (7-Zip) is installed and added to your system's PATH. You can verify this by running `7z` in your command line; it should not return an error.
- Your 7z must support large files (HugeFiles). This is typically available in the 64-bit version. Check this by verifying the flag `HugeFiles=on` with the command `7z`.

#### Preparation

- Confirm that the drive where the TLMC files are stored has at least 300GB of free space.
- **Important Warning**: The .rar files will be permanently deleted after extraction. Ensure you have backups if necessary. (Or disable this behavior by editing `extract.py` and remove line `os.unlink(os.path.join(fp, file))`)

#### Execution

1. Navigate to the Preprocessor directory and copy the `extract.py` script to your TLMC root directory, where the `.rar` files are located.
2. Open your command line interface and change the directory to the TLMC root. This is crucial as `extract.py` must be executed in the same directory as the `.rar` files.
3. Execute the script by running `python ./extract.py`. This will start the extraction process.

### 2. Track Audio Normalization

This section explains how to normalize the volume levels of audio tracks. Since web apps and the HLS protocol don't support ReplayGain tags, we'll directly modify the files to normalize their volume. This is a lossy process, so it's advised to back up your files if you wish to retain lossless copies.

The normalization uses the EBU R128 loudness normalization profile, which is the default in ffmpeg.

Detailed Parameter for FFmpeg default loudnorm profile:

- Integrated Loudness Target `I=-24` LUFS
- Loudness range target`LRA=7` LU
- True peak target `tp=-2.0` dBTP

You can edit this profile by navigating to the script and under `mk_ffmpeg_cmd(src, dst)` and uncomment and edit the profile

#### Important Noticies

- **Time Requirement**: This process is time-intensive. To minimize interruptions, consider running it in a detached tmux session.
- **Resource Intensity**: This is a CPU-intensive task. Limited CPU resources can significantly slow down the process. The script is designed to utilize all available CPU cores which may cause system instability. Avoid other CPU intensive jobs when running this script
- **Lossy Conversion**: This process will replace the original file with the normalized version and the conversion is a lossy process.

#### Prerequisites

- Ensure that ffmpeg is installed and added to your system's PATH. You can verify this by running `ffmpeg` in your command line; it should not return an error.

#### Preparation

- N/A

#### Execution

- Run `python ./Preprocessor/AudioNormalizer/normalizer.py` to start the normalization process

### 3. Cue Splitting (WIP)

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

### 1. INITIAL PROBE & EXTRACTION

### 2. DISC IDENTIFICATION

### 3. DATA TRANSFROMATION

## SECTION: POST PROCESSING

### 1. FLAC to HLS Transcoding
