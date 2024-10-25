from pymongoose import methods
from pymongoose.mongo_types import Types, Schema, MongoException, MongoError
from bson import json_util
from bson.objectid import ObjectId

class Storage(Schema):
    schema_name = 'storage'

    # Attributes
    id = None
    user_id = None
    query = None
    title = None
    summary = None

    def __init__(self, **kwargs):
        self.schema = {
            "user_id": {
                "type": Types.String,
                "required": True,
            },
            "query": {
                "type": Types.String,
                "required": True,
            },
            "title": {
                "type": Types.String,
                "required": True,
            },
            "summary": {
                "type": Types.String,
                "required": True,
            }
        }
        
        super().__init__(self.schema_name, self.schema, kwargs)

    def __str__(self):
        return f"user_id: {self.user_id}, query: {self.query}, title: {self.title}, summary: {self.summary}"
