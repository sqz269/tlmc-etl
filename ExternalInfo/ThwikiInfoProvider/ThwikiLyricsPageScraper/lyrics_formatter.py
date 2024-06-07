from dataclasses import dataclass
import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import httpx
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
import ExternalInfo.ThwikiInfoProvider.cache.path_definitions as CachePathDef

import ExternalInfo.ThwikiInfoProvider.output.path_definitions as ThwikiOutput
import mwparserfromhell as mw
from mwparserfromhell.nodes.template import Template
from mwparserfromhell.wikicode import Wikicode
from mwparserfromhell.nodes.text import Text
from mwparserfromhell.nodes.extras.parameter import Parameter
from mwparserfromhell.nodes.tag import Tag
from mwparserfromhell.nodes.comment import Comment
from mwparserfromhell.nodes.html_entity import HTMLEntity
from ExternalInfo.CacheInfoProvider.Cache import cached

@dataclass
class RubyAnnotation:
    text: str
    start: int
    end: int
    ruby: str

    def to_json(self):
        return {
            'type': 'ruby',
            'text': self.text,
            'start': self.start,
            'end': self.end,
            'ruby': self.ruby
        }

@dataclass
class LyricsAnnotatedLine:
    text: str
    annotations: List[RubyAnnotation]

    def to_json(self):
        return {
            'text': self.text,
            'annotations': [annotation.to_json() for annotation in self.annotations]
        }


def parse_line(line: str) -> LyricsAnnotatedLine:
    
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
        
        breakpoint()
        raise ValueError(f"Unexpected parameter type {type(typed_param)}")

    # Returns a tuple, the first element the raw text, the second element the annotations
    def _parse_template(template: Template) -> Tuple[str, Optional[str]]:
        # Handle a very rare case where the they use color templates
        # https://thwiki.cc/%E6%AD%8C%E8%AF%8D:she%27s_purity
        if re.match("colou?r:(?:(?:#(?:[0-9a-fA-F]{2}){1,3})|(?:[a-zA-Z]{1,}))", str(template.name)):
            # Return the first parameter as the raw text
            return _extract_text(template.params[0]), None

        if not re.match("ruby(?:\-[a-z]{2})?", str(template.name)):
            # breakpoint()
            raise ValueError(f"Unexpected template {template.name}")
        
        # Ensure the template has exactly 2 parameters
        if len(template.params) != 2:
            breakpoint()
            raise ValueError(f"Unexpected number of parameters in template {template.name}")

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
    annotations: List[RubyAnnotation] = []
    for nodes in parsed.nodes:
        if isinstance(nodes, Text):
            raw_text += nodes.value
        
        elif isinstance(nodes, Template):
            raw, annotation = _parse_template(nodes)
            ruby = RubyAnnotation(
                text=raw,
                start=len(raw_text),
                end=len(raw_text) + len(raw) - 1,
                ruby=annotation
            )
            annotations.append(ruby)
            raw_text += raw
        elif isinstance(nodes, Tag):
            # only handle : tag
            # Discard ref tags
            excluded_tags = ['ref', 'hr']
            replacement_tags = {':': '\t', '*': '*'}
            if nodes.tag in excluded_tags:
                continue

            if nodes.tag in replacement_tags:
                raw_text += replacement_tags[nodes.tag]
                continue

            breakpoint()
            raise ValueError(f"Unexpected tag {nodes.wiki_markup}")
        elif isinstance(nodes, Comment):
            # Discard comments
            continue
        elif isinstance(nodes, HTMLEntity):
            # Discard HTML entities
            continue
        else:
            breakpoint()
            raise ValueError(f"Unexpected node type: {type(nodes)}")

    return LyricsAnnotatedLine(
        text=raw_text,
        annotations=annotations
    )

def main():
    entry: LyricsInfo
    for entry in LyricsInfo.select().where((LyricsInfo.process_status == LyricsProcessingStatus.PROCESSED)):
        lyrics = entry.lyrics
        if lyrics is None:
            continue

        parsed = json.loads(lyrics)

        try:
            for section_title, section_content in parsed.items():
                for timestamp, lyrics in section_content.items():
                    for lang in lyrics.keys():
                        parsed = parse_line(lyrics[lang])
                        print(parsed)
                        lyrics[lang] = parsed

            entry.lyrics = json.dumps(parsed.to_json(), ensure_ascii=False)
            entry.process_status = LyricsProcessingStatus.PARSE_PROCESSED
            entry.save()
        except Exception as e:
            print(f"Failed to parse lyrics for {entry.track_id}: {e}")
            entry.process_status = LyricsProcessingStatus.PARSE_FAILED_MANUL_REQUIRED
            entry.save()
            continue


if __name__ == '__main__':
    main()
