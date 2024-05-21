from operator import truediv
from peewee import *
from Shared import utils

import ExternalInfo.ThcInfoProvider.Databases.path_definitions as DatabasesPathDef

query_data_db_path = utils.get_output_path(
    DatabasesPathDef, DatabasesPathDef.THWIKI_FORMATTED_DATABASE
)
InfoProviderDb = SqliteDatabase(query_data_db_path)


class BaseModel(Model):
    class Meta:
        database = InfoProviderDb


class ProcessStatusFormatted:
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    TRACK_COUNT_MISMATCH = "TRACK_COUNT_MISMATCH"
    PUSHED = "PUSHED"


class AlbumFormatted(BaseModel):
    album_id = TextField(primary_key=True, unique=True)

    album_name = TextField(null=True)

    release_date = TextField(null=True)
    # convention = TextField(null=True)
    catalogno = TextField(null=True)

    number_of_disc = IntegerField(null=True)

    website = TextField(null=True)

    album_artist = TextField(null=True)

    data_source = TextField(null=True)

    process_status = TextField(null=True)


class TrackFormatted(BaseModel):
    track_id = TextField(primary_key=True, unique=True)
    title = TextField(null=True)
    disc_no = IntegerField(null=True)
    index = IntegerField(null=True)

    arrangement = TextField(null=True)
    circle = TextField(null=True)
    vocal = TextField(null=True)
    lyricist = TextField(null=True)

    original = TextField(null=True)

    original_non_touhou = BooleanField(null=False)

    album = ForeignKeyField(AlbumFormatted, backref="tracks")

    process_status = TextField(null=True)


InfoProviderDb.connect()
InfoProviderDb.create_tables([TrackFormatted, AlbumFormatted])
