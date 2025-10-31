# TODO: Have a lot of edge cases here handling the data
# considering using Chatgpt/Superglue to have a healing layer that automatically
# handle unexpected mediawiki templates and extract useful text from it

from collections import defaultdict
from dataclasses import dataclass
import json
import re
import time
import html
import traceback
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import httpx
from openai import OpenAI
from Shared import utils
from Shared.json_utils import json_load, json_dump
from ExternalInfo.ThwikiInfoProvider.ThwikiAlbumPageScraper.Model.ThcSongInfoModel import (
    Track,
    Album,
)
from ExternalInfo.ThwikiInfoProvider.ThwikiLyricsPageScraper.Model.ThwikiLyricsInfoModel import (
    LyricsInfo,
    LyricsProcessingStatus,
)
import ExternalInfo.CacheInfoProvider.Cache as Cache
from ExternalInfo.CacheInfoProvider.AdvancedCache import (
    advanced_cache,
    adv_cache_hashed_id_generator,
)
import ExternalInfo.ThwikiInfoProvider.cache.path_definitions as CachePathDef
import Shared.openai_utils as OpenaiUtils
import ExternalInfo.ThwikiInfoProvider.output.path_definitions as ThwikiOutput
import mwparserfromhell as mw
from mwparserfromhell.nodes.template import Template
from mwparserfromhell.wikicode import Wikicode
from mwparserfromhell.nodes.text import Text
from mwparserfromhell.nodes.extras.parameter import Parameter
from mwparserfromhell.nodes.tag import Tag
from mwparserfromhell.nodes.comment import Comment
from mwparserfromhell.nodes.html_entity import HTMLEntity
from mwparserfromhell.nodes.wikilink import Wikilink
from ExternalInfo.CacheInfoProvider.Cache import cached

ENABLE_AI_HEALING = True

OPEN_AI_API_CONTEXT: Optional[OpenAI] = None

@dataclass
class RubyAnnotation:
    index: int
    length: int
    text: str

    def to_json(self):
        return {"index": self.index, "length": self.length, "text": self.text}

    @staticmethod
    def from_json(data: Any):
        return RubyAnnotation(
            index=int(data["index"]), length=int(data["length"]), text=data["text"]
        )


@dataclass
class LyricsAnnotatedLine:
    time: Optional[str]
    text: str
    annotations: List[RubyAnnotation]

    def to_json(self):
        return {
            "time": self.time,
            "text": self.text,
            "annotations": [annotation.to_json() for annotation in self.annotations],
        }

    @staticmethod
    def from_json(data: Any):
        return LyricsAnnotatedLine(
            data["time"],
            data["text"],
            [RubyAnnotation.from_json(i) for i in data["annotations"]],
        )

    @staticmethod
    def empty():
        return LyricsAnnotatedLine(time=None, text="", annotations=[])


def validate_timespan(time: str) -> Optional[timedelta]:
    REGEX = re.compile(r"(?:\d{2}:)?\d{2}(?::|\.)\d{2}")
    return REGEX.match(time)


@advanced_cache(
    cache_id="lyrics_line_healing",
    cache_dir=utils.get_output_path(
        CachePathDef, CachePathDef.THWIKI_LYRICS_LLM_LINE_HEAL_CACHE_DIR
    ),
    debug=True,
    cache_save_transformer=lambda x: json.dumps(x, ensure_ascii=False),
    cache_load_transformer=json.loads,
    cache_filename_generator=adv_cache_hashed_id_generator,
)
def llm_heal_line(raw_line: str) -> Optional[Dict[Any, Any]]:
    """
    Uses OpenAI's model to process MediaWiki markup and return a LyricsAnnotatedLine.

    The LLM is prompted to return a JSON object that conforms to:
    {
      "time": <string or null>,
      "text": "<clean extracted text>",
      "annotations": [
        {
          "index": <integer>,
          "length": <integer>,
          "text": "<ruby text>"
        },
        ...
      ]
    }

    Args:
        raw_line (str): A single line of MediaWiki markup to parse.

    Returns:
        Optional[LyricsAnnotatedLine]: Parsed dataclass, or None if there's an error.
    """

    # The user instructions for the LLM:
    # - The LLM must only output valid JSON
    # - "time" can be null if there's no known time
    # - "annotations" is a list of objects with index, length, and text
    # - It's strictly about extracting text & annotations from the markup
    prompt = r"""
    You are an AI that extracts lyrics from a line of MediaWiki markup.

    **Instructions:**
    1. If there are any templates like {{ruby|BaseText|RubyText}} or {{ruby-ja|BaseText|RubyText}}, 
    the BaseText goes into "text" while the RubyText is put into an annotation object.
    - The annotation object is defined as:
        {
            "index": <integer position where BaseText appears in text>,
            "length": <length of BaseText>,
            "text": <RubyText>
        }
    - The RubyText must NOT appear in the "text" itself.
    2. Remove or flatten other templates (e.g. {{color:blue|…}}), leaving only their visible text in "text."
    3. Strip or ignore HTML tags (<br />, <ref>, etc.), discarding the textual content inside them if it’s purely markup, or preserving it if it’s essential text. 
    4. The output must be returned as valid JSON with exactly this structure:

    {
    "time": <string or null>,
    "text": <string containing all base text with any ruby text removed>,
    "annotations": [
        {
        "index": <integer>,
        "length": <integer>,
        "text": <string containing the ruby text>
        },
        ...
    ]
    }

    5. "time" can be null if there is no explicit timestamp in the snippet.
    6. Output only this JSON, with no extra text or explanations.

    **Example:**
    Input:
    {{ruby-ja|{{color:\#EE0000|寒風にかき消され}}|{{color:\#1E90FF|寒さに呑まれて}}}}

    Expected JSON:
    {
    "time": null,
    "text": "寒風にかき消され",
    "annotations": [
        {
        "index": 0,
        "length": 8,
        "text": "寒さに呑まれて"
        }
    ]
    }

    Here is the line to parse:
    ---
    <<<<RAW_LINE>>>>
    ---

    Return only valid JSON according to the specification.
    """.replace(
        "<<<<RAW_LINE>>>>", raw_line
    )

    try:
        parsed_json = OpenaiUtils.get_completion(OPEN_AI_API_CONTEXT, "gpt-5", prompt)
        # Convert JSON to LyricsAnnotatedLine dataclass
        # return LyricsAnnotatedLine.from_json(parsed_json)
        return parsed_json
    except Exception as e:
        print(f"Error while extracting lyrics line from LLM: {e}")
        return None


def parse_line(line: str, need_review: List[Any]) -> LyricsAnnotatedLine:

    def _extract_text(param: Parameter) -> str:
        param_type_narrower: Callable[[Parameter], Union[Template, Text, Any]] = lambda x: x.value.nodes[0]
        typed_param = param_type_narrower(param)
        if isinstance(typed_param, Text):
            return str(param.value)

        if isinstance(typed_param, Template):
            # Ensure we are dealing with the `lang` template, if not, fail
            if not typed_param.name.matches("lang"):
                # breakpoint()
                raise ValueError(f"Unexpected template when recursively parsing ruby parameters {typed_param.name}")

            # Extract the second parameter of the `lang` template
            return _extract_text(typed_param.params[1])

        if isinstance(typed_param, Parameter):
            return _extract_text(typed_param.value)

        # otherwise convert to string directly
        need_review.append(True)
        return str(typed_param)
        # breakpoint()
        # raise ValueError(f"Unexpected parameter type {type(typed_param)}")

    # Returns a tuple, the first element the raw text, the second element the annotations
    def _parse_template(template: Template) -> Tuple[str, Optional[str]]:
        # Handle a very rare case where the they use color templates
        # https://thwiki.cc/%E6%AD%8C%E8%AF%8D:she%27s_purity
        if re.match("colou?r:(?:(?:#(?:[0-9a-fA-F]{2}){1,3})|(?:[a-zA-Z]{1,}))", str(template.name)):
            # Return the first parameter as the raw text
            return _extract_text(template.params[0]), None

        if str(template.name).startswith("lang"):
            if len(template.params) != 2:
                raise ValueError(
                    f"Unexpected number of parameters in template {template.name}"
                )
            return str(template.params[1]), None

        if str(template.name).startswith("强调"):
            if len(template.params) != 1:
                raise ValueError(
                    f"Unexpected number of parameters in template {template.name}"
                )
            return str(template.params[0]), None

        if str(template.name).startswith("cursive"):
            if len(template.params) != 2:
                raise ValueError(
                    f"Unexpected number of parameters in template {template.name}"
                )
            return str(template.params[0]), None

        if str(template.name).startswith("serif"):
            if len(template.params) != 2:
                raise ValueError(
                    f"Unexpected number of parameters in template {template.name}"
                )
            return str(template.params[0]), None

        if str(template.name).startswith("sans"):
            if len(template.params) != 2:
                print("wtf")
            return str(template.params[0]), None

        if not re.match("ruby(?:\\-[a-z]{2})?", str(template.name)):
            # breakpoint()
            # return llm_heal_line(str(template)), None
            raise ValueError(f"Unexpected template {template.name}")

        # Ensure the template has exactly 2 parameters
        if len(template.params) != 2:
            raise ValueError(
                f"Unexpected number of parameters in template {template.name}"
            )
            breakpoint()
            need_review.append(True)
            return _extract_text(template.params[0]), ""

        result = []
        params: Parameter
        for params in template.params:
            result.append(_extract_text(params))

        return result[0], result[1]

    def _parse_node(node: Any) -> Union[str, Tuple[str, RubyAnnotation]]:
        match node:
            case Text():
                return node.value
            case Template():
                return _parse_node(node)
            case Tag() as tag:
                excluded_tags = ['ref', 'hr']
                replacement_tags = {':': '\t', '*': '*'}

                match tag.tag:
                    case tag if tag in excluded_tags:
                        return ""
                    case tag if tag in replacement_tags:
                        return replacement_tags[tag]
                    case _:
                        breakpoint()
                        raise ValueError(f"Unexpected tag {tag.wiki_markup}")
            case Comment() | HTMLEntity():
                # Discard comments and HTML entities
                return ""
            case _:
                breakpoint()
                raise ValueError(f"Unexpected node type: {type(node)}")

    raw_text = ""

    parsed = mw.parse(line)
    try:
        annotations: List[RubyAnnotation] = []
        for nodes in parsed.nodes:
            if isinstance(nodes, Text):
                raw_text += nodes.value
            elif isinstance(nodes, Template):
                raw, annotation = _parse_template(nodes)
                if not annotation:
                    raw_text += raw
                    continue

                index = raw_text.__len__()
                length = len(raw)
                ruby = RubyAnnotation(index=index, length=length, text=annotation)
                annotations.append(ruby)
                raw_text += raw
            elif isinstance(nodes, Tag):
                if nodes.tag == "dd":
                    continue
                # excluded_tags = ['ref', 'hr']
                # replacement_tags = {':': '\t', '*': '*'}
                # if nodes.tag in excluded_tags:
                #     continue

                # if nodes.tag in replacement_tags:
                #     raw_text += replacement_tags[nodes.tag]
                #     continue

                # breakpoint()
                # raise ValueError(f"Unexpected tag {nodes.wiki_markup}")
                raise ValueError(f"Unexpected tag {nodes.tag}")
                raw_text += line
            elif isinstance(nodes, Comment):
                # Discard comments
                continue
            elif isinstance(nodes, Wikilink):
                raw_text += nodes.text
            elif isinstance(nodes, HTMLEntity):
                # Discard HTML entities
                if str(nodes).replace(";", "") == "&nbsp":
                    continue
                if str(nodes).startswith("&"):
                    raw_text += html.unescape(str(nodes))
                    continue
                continue
            else:
                breakpoint()
                raise ValueError(f"Unexpected node type: {type(nodes)}")
    except Exception as e:
        print("Failed to parse line, falling back to AI healing")
        json = llm_heal_line(line)
        if json is None:
            r = LyricsAnnotatedLine.empty()
        else:
            r = LyricsAnnotatedLine.from_json(json)
        print(r)
        return r
    return LyricsAnnotatedLine(time=None, text=raw_text, annotations=annotations)


def main():
    if ENABLE_AI_HEALING:
        global OPEN_AI_API_CONTEXT
        OPEN_AI_API_CONTEXT = OpenaiUtils.get_openai_context()

    entry: LyricsInfo
    i = 0
    for entry in LyricsInfo.select().where(
        (LyricsInfo.process_status == LyricsProcessingStatus.PROCESSED)
    ):
        # if entry.remote_track_id()
        lyrics_src = entry.lyrics_src
        if lyrics_src is None:
            continue
        i += 1
        print(
            f"Processing {i}: {entry.track_id} - {entry.wiki_page_title_constructed} actual: {entry.wiki_page_title_actual}"
        )
        parsed = json.loads(lyrics_src)

        try:
            parsed_lyrics: Dict[str, Dict[str, List[LyricsAnnotatedLine]]] = (
                defaultdict(lambda: defaultdict(list))
            )
            out_need_review = []
            for section_title, section_content in parsed.items():
                for timespan, lyrics_src in section_content.items():
                    is_valid = validate_timespan(timespan)
                    for lang in lyrics_src.keys():
                        try:
                            line_parsed = parse_line(lyrics_src[lang], out_need_review)
                            if is_valid:
                                line_parsed.time = timespan
                            # print(line_parsed)
                            parsed_lyrics[section_title][lang].append(
                                line_parsed.to_json()
                            )
                        except Exception as e:
                            traceback.print_exc()

            parsed_lyrics["need_review"] = not not out_need_review

            entry.lyrics = json.dumps(parsed_lyrics, ensure_ascii=False)
            entry.process_status = LyricsProcessingStatus.PARSE_PROCESSED
            entry.save()
        except Exception as e:
            print(f"Failed to parse lyrics for {entry.track_id}: {e}")
            entry.process_status = LyricsProcessingStatus.PARSE_FAILED_MANUL_REQUIRED
            entry.save()
            continue


if __name__ == '__main__':
    main()
