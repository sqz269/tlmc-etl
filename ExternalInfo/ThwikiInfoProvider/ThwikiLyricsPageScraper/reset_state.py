import json
import re
import time
from typing import Dict, Optional
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
import ExternalInfo.ThwikiInfoProvider.ThwikiLyricsPageScraper.Model.ThwikiLyricsModel as LyricsModel
import ExternalInfo.ThwikiInfoProvider.cache.path_definitions as CachePathDef

import ExternalInfo.ThwikiInfoProvider.output.path_definitions as ThwikiOutput
import mwparserfromhell as mw
from mwparserfromhell.nodes.template import Template
from mwparserfromhell.wikicode import Wikicode
from ExternalInfo.CacheInfoProvider.Cache import cached
from ExternalInfo.ThwikiInfoProvider.Shared import ThwikiUtils

e: LyricsInfo
i = 0
for e in LyricsInfo.select().where(
    LyricsInfo.process_status == LyricsProcessingStatus.PARSE_PROCESSED
):
    i += 1
    print(i)
    e.process_status = LyricsProcessingStatus.PENDING
    e.lyrics_src = None
    e.lyrics = None
    e.save()
