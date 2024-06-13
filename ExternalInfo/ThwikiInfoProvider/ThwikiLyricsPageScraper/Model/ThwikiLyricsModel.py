from dataclasses import dataclass
from typing import Dict, List

@dataclass
class ThwikiLyricsLineLang:
    lang: str
    text: str

    def to_json(self):
        return {self.lang: self.text}
    
    @staticmethod
    def from_json(json_data):
        lang = list(json_data.keys())[0]
        text = json_data[lang]
        return ThwikiLyricsLineLang(lang, text)

@dataclass
class ThwikiLyricsTimeInstant:
    timestamp: str
    lines: List[ThwikiLyricsLineLang]

    def to_json(self):
        lines = {}
        for line in self.lines:
            lines.update(line.to_json())
        return {
            self.timestamp: lines
        }
    
    @staticmethod
    def from_json(json_data):
        timestamp = list(json_data.keys())[0]
        lines = []
        for line in json_data[timestamp]:
            lines.append(ThwikiLyricsLineLang.from_json(line))
        return ThwikiLyricsTimeInstant(timestamp, lines)

@dataclass
class ThwikiLyricsSection:
    section_title: str
    time_instants: Dict[str, ThwikiLyricsTimeInstant]

    def to_json(self):
        time_instants = {}
        for time_instant in self.time_instants.values():
            time_instants.update(time_instant.to_json())
        return {
            self.section_title: time_instants
        }

@dataclass
class ThwikiLyrics:
    sections: List[ThwikiLyricsSection]

    def to_json(self):
        sections = {}
        for section in self.sections:
            sections.update(section.to_json())
        return sections
    
