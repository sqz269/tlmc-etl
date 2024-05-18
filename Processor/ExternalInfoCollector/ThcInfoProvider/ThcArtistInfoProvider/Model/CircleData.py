from peewee import *
import os

QueryDataDb = SqliteDatabase(r'./InfoProviders/ThcInfoProvider/ThcArtistInfoProvider/Data/query_data.db')
# QueryDataDb = SqliteDatabase(None) # Deferring database initialization

class BaseModel(Model):
    class Meta:
        database = QueryDataDb

class CircleStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DISBANDED = "DISBANDED"
    UNKNOWN = "UNKNOWN"

class QueryStatus:
    SCRAPE_OK = "SCRAPE_OK"

    SCRAPE_FAILED = "SCRAPE_FAILED"

    # Query result returned a valid result
    SUCCESS = "SUCCESS"

    # Query returned a result but the result is invalid
    INVALID = "INVALID"

    # Query returned no result
    NO_RESULT = "NO_RESULT"

    # Query failed due to network error
    FAILED = "FAILED"

class CircleData(BaseModel):
    circle_name = TextField(primary_key=True, unique=True)
    circle_query_url = TextField(null=True)
    circle_status = TextField(null=True)
    circle_est = TextField(null=True)
    circle_country = TextField(null=True)
    # stringified Json field for circle web links
    # In form of { "Presence Type": "Uri", ... }
    circle_web = TextField(null=True)

    # Indicates whether the circle has been scraped
    circle_scraped = BooleanField(default=False)

    # Indicates whether the query was successful
    circle_query_status = TextField(null=True)

QueryDataDb.connect()
QueryDataDb.create_tables([CircleData])
