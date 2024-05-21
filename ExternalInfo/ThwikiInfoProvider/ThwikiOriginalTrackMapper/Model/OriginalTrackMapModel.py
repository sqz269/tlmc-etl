from peewee import *

import ExternalInfo.ThwikiInfoProvider.Databases.path_definitions as DatabasesPathDef
from Shared import utils

original_track_map_db_path = utils.get_output_path(
    DatabasesPathDef, DatabasesPathDef.THWIKI_ORIGINAL_TRACK_MAP_DATABASE
)

OriginalTrackDb = SqliteDatabase(
    original_track_map_db_path,
)


class BaseModel(Model):
    class Meta:
        database = OriginalTrackDb


class TrackSource(BaseModel):
    id = TextField(primary_key=True, unique=True)
    query_kw = TextField()
    title_jp = TextField(null=True)
    title_en = TextField(null=True)
    title_zh = TextField(null=True)
    abbriv = TextField(null=True)


class OriginalTrack(BaseModel):
    id = TextField(primary_key=True, unique=True)
    source = ForeignKeyField(TrackSource, backref="songs")
    index = TextField(null=True)
    sp_index = TextField(null=True)
    sp_idx_e = TextField(null=True)
    sp_idx_a = TextField(null=True)
    title_jp = TextField()
    title_en = TextField()
    title_zh = TextField()

    def __str__(self):
        return f"{self.id} {self.index} {self.title_jp} {self.title_en} {self.title_zh}"

    @staticmethod
    def mk_fail(query, default):
        song = OriginalTrack()
        song.id = str("00000000-0000-0000-0000-000000000000")
        song.source = query
        song.index = None
        song.sp_index = None
        song.sp_idx_e = None
        song.sp_idx_a = None
        song.title_jp = default
        song.title_en = default
        song.title_zh = default
        return song

    __repr__ = __str__


OriginalTrackDb.connect()
OriginalTrackDb.create_tables([TrackSource, OriginalTrack])
