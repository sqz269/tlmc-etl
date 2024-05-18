from peewee import *
import datetime

CacheDb = SqliteDatabase('./InfoProviders/CacheInfoProvider/Data/Cache.db')

class BaseModel(Model):
    class Meta:
        database = CacheDb

class SourceCacheTable(BaseModel):
    path = TextField(primary_key=True, unique=True)
    cached_source_path = TextField(default="")
    time_cached = DateTimeField(default=datetime.datetime.now)

CacheDb.connect()
CacheDb.create_tables([SourceCacheTable])
