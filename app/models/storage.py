from pymongoose import methods
from pymongoose.mongo_types import Types, Schema, MongoException, MongoError
from bson import json_util
from bson.objectid import ObjectId

class Storage(Schema):
    schema_name = 'storage'

    # Attributes
    id = None
    user_id = None
    result = None
    type = None
    title = None
    summary = None
    def __init__(self, **kwargs):
        self.schema = {
            "user_id": {
                "type": Types.String,
                "required": True,
            },
            "result": {
                "type": Types.String,
                "required": True,
            },
            "type": {
                "type": Types.String,
                "enum": ["graph", "query"]
            },
            "title": {
                "type": Types.String,
            },
            "summary": {
                "type": Types.String,
            }
        }
        
        super().__init__(self.schema_name, self.schema, kwargs)

    def __str__(self):
        return f"user_id: {self.user_id}, result: {self.result}, type: {self.type}"
