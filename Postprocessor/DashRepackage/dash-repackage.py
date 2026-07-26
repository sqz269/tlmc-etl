import json
from typing import Dict, List
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
import os
import m3u8
import os
from datetime import timedelta
import Postprocessor.DashRepackage.output.path_definitions as DashRepackagePathDef
from Shared import utils

# Sample path for JSON input
json_input_path = utils.get_output_path(
    DashRepackagePathDef,
    DashRepackagePathDef.DASH_REPACKAGE_FILELIST_OUTPUT_NAME,
)

def seconds_to_iso_duration(seconds: float) -> str:
    """Converts seconds to ISO 8601 duration format (e.g., PT60S)."""
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    return f"PT{total_seconds}S"

TIMESCALE = 48000


def parse_hls_byterange(byterange: str, prev_end: int):
    """
    '402196@762' -> (762, 403157) as an inclusive DASH start-end pair.

    HLS writes LENGTH@OFFSET and permits the offset to be omitted, meaning the
    range starts immediately after the previous one. ffmpeg always emits it, but
    both forms are accepted here.
    """
    if "@" in byterange:
        length_s, offset_s = byterange.split("@", 1)
        start = int(offset_s)
    else:
        length_s = byterange
        start = prev_end + 1

    return start, start + int(length_s) - 1


def read_playlist(rep):
    """
    Returns (durations, media_ranges, init_range).

    media_ranges and init_range are None for the per-segment layout, where each
    segment is its own file and no byte ranges appear in the playlist.
    """
    playlist = m3u8.load(rep["playlist"])
    durations = [s.duration for s in playlist.segments if s.duration is not None]

    if rep.get("layout") != "single_file":
        return durations, None, None

    media_ranges = []
    prev_end = -1
    for segment in playlist.segments:
        start, end = parse_hls_byterange(segment.byterange, prev_end)
        media_ranges.append((start, end))
        prev_end = end

    # #EXT-X-MAP:URI="stream.m4s",BYTERANGE="762@0" -- the fMP4 init segment
    # lives at the head of the same file rather than in its own init.mp4.
    init_map = playlist.segment_map[0]
    init_start, init_end = parse_hls_byterange(init_map.byterange, -1)

    return durations, media_ranges, (init_start, init_end)


def create_mpd(project):
    playlist_segment_durations: Dict[str, List[float]] = {}
    playlist_ranges = {}
    max_total_duration = 0.0

    # Load segment durations from each playlist and compute max total duration
    for rep in project["packager_args"]:
        durations, media_ranges, init_range = read_playlist(rep)
        total_duration = sum(durations)
        playlist_segment_durations[rep["bandwidth"]] = durations
        playlist_ranges[rep["bandwidth"]] = (media_ranges, init_range)
        max_total_duration = max(max_total_duration, total_duration)

    # Format total duration as ISO 8601 string
    mpd_duration = seconds_to_iso_duration(max_total_duration)

    mpd = Element("MPD", xmlns="urn:mpeg:dash:schema:mpd:2011",
                  profiles="urn:mpeg:dash:profile:isoff-on-demand:2011",
                  type="static", minBufferTime="PT1.5S",
                  mediaPresentationDuration=mpd_duration)

    period = SubElement(mpd, "Period", start="PT0S")
    adaptation_set = SubElement(period, "AdaptationSet", mimeType="audio/mp4",
                                codecs="mp4a.40.2", startWithSAP="1", segmentAlignment="true", lang="en")

    for rep in project["packager_args"]:
        base_path = rep["path"]
        durations = playlist_segment_durations[rep["bandwidth"]]
        media_ranges, init_range = playlist_ranges[rep["bandwidth"]]

        representation = SubElement(adaptation_set, "Representation",
                                    id=str(rep["bandwidth"]),
                                    bandwidth=str(rep["bandwidth"]))
        base_url = SubElement(representation, "BaseURL")

        base_url_actual = os.path.relpath(base_path, start=os.path.dirname(project["output_mpd"])) + "/"
        base_url.text = base_url_actual.replace("hls/", "")

        if rep.get("layout") == "single_file":
            # SegmentTemplate cannot express byte ranges, so the single-file
            # layout maps onto SegmentList instead: one SegmentURL per segment,
            # all pointing at the same media file with a mediaRange.
            #
            # SegmentBase/indexRange would be more compact but needs an sidx box,
            # and ffmpeg's HLS muxer does not write one.
            #
            # Child order is fixed by the DASH schema: Initialization, then
            # SegmentTimeline, then the SegmentURL list.
            media_file = os.path.basename(rep["media_file"])
            segment_list = SubElement(representation, "SegmentList",
                                      timescale=str(TIMESCALE))
            SubElement(segment_list, "Initialization",
                       sourceURL=media_file,
                       range=f"{init_range[0]}-{init_range[1]}")

            segment_timeline = SubElement(segment_list, "SegmentTimeline")
            for duration_sec in durations:
                SubElement(segment_timeline, "S",
                           d=str(int(round(duration_sec * TIMESCALE))))

            for start, end in media_ranges:
                SubElement(segment_list, "SegmentURL",
                           media=media_file,
                           mediaRange=f"{start}-{end}")
        else:
            init_file = os.path.basename(rep["init_segment"])
            media_template = os.path.basename(rep["segment_template"])

            segment_template = SubElement(representation, "SegmentTemplate",
                                          initialization=init_file,
                                          media=media_template,
                                          startNumber="0",
                                          timescale=str(TIMESCALE))

            segment_timeline = SubElement(segment_template, "SegmentTimeline")
            for duration_sec in durations:
                SubElement(segment_timeline, "S",
                           d=str(int(round(duration_sec * TIMESCALE))))

    xmlstr = minidom.parseString(tostring(mpd)).toprettyxml(indent="  ")
    with open(project["output_mpd"], "w", encoding='utf-8') as f:
        f.write(xmlstr)

def main():
    # Guarded so importing create_mpd does not read the filelist and rebuild
    # every manifest as an import side effect.
    with open(json_input_path, 'r', encoding='utf-8') as f:
        projects = json.load(f)

    for i, proj in enumerate(projects):
        create_mpd(proj)
        print(f"Created {i+1} of {len(projects)}")


if __name__ == "__main__":
    main()