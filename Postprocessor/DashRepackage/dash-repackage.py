import json
from typing import Dict, List
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
import os
import m3u8

import Postprocessor.DashRepackage.output.path_definitions as DashRepackagePathDef
from Shared import utils

# Sample path for JSON input
json_input_path = utils.get_output_path(
    DashRepackagePathDef,
    DashRepackagePathDef.DASH_REPACKAGE_FILELIST_OUTPUT_NAME,
)

with open(json_input_path, 'r', encoding='utf-8') as f:
    projects = json.load(f)

def create_mpd(project):
    playlist_segment_durations: Dict[str, List[float]] = {}

    for rep in project["packager_args"]:
        playlist = m3u8.load(rep["playlist"])
        durations = [segment.duration for segment in playlist.segments]
        playlist_segment_durations[rep["bandwidth"]] = durations

    mpd = Element("MPD", xmlns="urn:mpeg:dash:schema:mpd:2011",
                  profiles="urn:mpeg:dash:profile:isoff-on-demand:2011",
                  type="static", minBufferTime="PT1.5S",
                  mediaPresentationDuration="PT60S")  # Placeholder duration

    period = SubElement(mpd, "Period", start="PT0S")
    adaptation_set = SubElement(period, "AdaptationSet", mimeType="audio/mp4",
                                codecs="mp4a.40.2", startWithSAP="1", segmentAlignment="true", lang="en")

    for rep in project["packager_args"]:
        base_path = os.path.dirname(rep["segment_template"])
        init_file = os.path.basename(rep["init_segment"])
        media_template = os.path.basename(rep["segment_template"])
        durations = playlist_segment_durations[rep["bandwidth"]]

        representation = SubElement(adaptation_set, "Representation",
                                    id=str(rep["bandwidth"]),
                                    bandwidth=str(rep["bandwidth"]))
        base_url = SubElement(representation, "BaseURL")
        base_url.text = os.path.relpath(base_path, start=os.path.dirname(project["output_mpd"])) + "/"

        segment_template = SubElement(representation, "SegmentTemplate",
                                      initialization=init_file,
                                      media=media_template,
                                      startNumber="0",
                                      timescale="48000")

        segment_timeline = SubElement(segment_template, "SegmentTimeline")
        for duration_sec in durations:
            d = str(int(round(duration_sec * 48000)))
            SubElement(segment_timeline, "S", d=d)

    xmlstr = minidom.parseString(tostring(mpd)).toprettyxml(indent="  ")
    with open(project["output_mpd"], "w", encoding='utf-8') as f:
        f.write(xmlstr)

for i, proj in enumerate(projects):
    create_mpd(proj)
    print(f"Created {i+1} of {len(projects)}")