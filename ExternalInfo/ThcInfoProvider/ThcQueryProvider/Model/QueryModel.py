from peewee import *
import os

QueryDataDb = SqliteDatabase(r'./InfoProviders/ThcInfoProvider/ThcQueryProvider/Data/query_data.db')
# QueryDataDb = SqliteDatabase(None) # Deferring database initialization

class BaseModel(Model):
    class Meta:
        database = QueryDataDb

class QueryStatus:
    PENDING = "PENDING"
    NO_RESULT = "NO_RESULT"

    RESULT_ONE_EXACT = "ONE_EXACT"
    RESULT_ONE_SUS = "ONE_SUS"
    RESULT_ONE_AMBIGUOUS = "ONE_AMBIGUOUS"

    RESULT_MANY_EXACT = "MANY_EXACT"
    RESULT_MANY_AMBIGUOUS = "MANY_AMBIGUOUS"

    RESULT_SUSPICOUS = "SUS"

class QueryData(BaseModel):
    album_id = TextField(primary_key=True, unique=True)
    album_name = TextField()
    query_result = TextField(null=True)
    query_exact_result = TextField(null=True)
    query_status = TextField()

QueryDataDb.connect()
QueryDataDb.create_tables([QueryData])
