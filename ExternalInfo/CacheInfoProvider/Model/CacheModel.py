import datetime

from peewee import *

import ExternalInfo.ThwikiInfoProvider.Databases.path_definitions as DatabasesPathDef
from Shared import utils

cache_db_path = utils.get_output_path(DatabasesPathDef, DatabasesPathDef.ADVANCED_CACHE_DATABASE)
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
