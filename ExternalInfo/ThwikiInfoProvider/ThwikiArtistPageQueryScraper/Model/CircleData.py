from peewee import *
import os

import ExternalInfo.ThwikiInfoProvider.Databases.path_definitions as DatabasesPathDef
from Shared import utils

circle_data_db_path = utils.get_output_path(
    DatabasesPathDef, DatabasesPathDef.THWIKI_CIRCLES_INFO_DATABASE
)

CircleDataDb = SqliteDatabase(circle_data_db_path)

class BaseModel(Model):
    class Meta:
        database = CircleDataDb

class CircleStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DISBANDED = "DISBANDED"
    UNKNOWN = "UNKNOWN"

class QueryStatus:
    PENDING = "PENDING"

    # Query result returned a valid result
    SUCCESS = "SUCCESS"

    # Query returned a result but the result is invalid
    INVALID = "INVALID"

    # Query returned no result
    NO_RESULT = "NO_RESULT"

    # Query failed due to network error
    FAILED = "FAILED"

    # Circle data has been scraped 
    SCRAPE_OK = "SCRAPE_OK"

    SCRAPE_FAILED = "SCRAPE_FAILED"

class CircleData(BaseModel):
    circle_remote_id = TextField(primary_key=True, unique=True)
    circle_name = TextField(unique=True)
    circle_wiki_url = TextField(null=True)
    
    circle_status = TextField(null=True)
    circle_est = TextField(null=True)
    circle_country = TextField(null=True)
    # stringified Json field for circle web links
    # In form of { "Presence Type": "Uri", ... }
    circle_web = TextField(null=True)

    # Indicates whether the query was successful
    circle_query_status = TextField(null=True)

CircleDataDb.connect()
CircleDataDb.create_tables([CircleData])
