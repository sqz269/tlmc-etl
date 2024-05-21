from peewee import *
import datetime
from Shared import utils

import ExternalInfo.ThcInfoProvider.Databases.path_definitions as DatabasesPathDef

cache_db_path = utils.get_output_path(DatabasesPathDef, DatabasesPathDef.CACHE_DATABASE)
CacheDb = SqliteDatabase(cache_db_path)


class BaseModel(Model):
    class Meta:
        database = CacheDb


class SourceCacheTable(BaseModel):
    path = TextField(primary_key=True, unique=True)
    cached_source_path = TextField(default="")
    time_cached = DateTimeField(default=datetime.datetime.now)


CacheDb.connect()
CacheDb.create_tables([SourceCacheTable])
