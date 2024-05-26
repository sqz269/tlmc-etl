from peewee import *

import ExternalInfo.ThwikiInfoProvider.Databases.path_definitions as DatabasesPathDef
from Shared import utils

lyrics_data_db_path = utils.get_output_path(
    DatabasesPathDef, DatabasesPathDef.THWIKI_LYRICS_INFO_DATABASE
)

LyricsDataDb = SqliteDatabase(lyrics_data_db_path)

class BaseModel(Model):
    class Meta:
        database = LyricsDataDb

class LyricsProcessingStatus:
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    NO_LYRICS_FOUND = "NO_LYRICS_FOUND"
    FAILED = "FAILED"

class LyricsInfo(BaseModel):
    track_id = TextField(primary_key=True, unique=True)
    
    remote_track_id = TextField(unique=True)
    
    wiki_page_title_constructed = TextField(null=True)

    # This is the actual page, in case the constructed one leaves a redirect
    # to the actual page
    wiki_page_title_actual = TextField(null=True)

    lyrics = TextField(null=True)

    process_status = TextField(null=True)


LyricsDataDb.connect()
LyricsDataDb.create_tables([LyricsInfo])
