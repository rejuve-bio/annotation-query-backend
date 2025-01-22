from pymongoose import methods
from pymongoose.mongo_types import Types, Schema, MongoException, MongoError
from bson import json_util
from bson.objectid import ObjectId
import datetime

class Storage(Schema):
    schema_name = 'storage'

    # Attributes
    id = None
    user_id = None
    query = None
    title = None
    summary = None
    answer = None

    def __init__(self, **kwargs):
        self.schema = {
            "user_id": {
                "type": Types.String,
                "required": True,
            },
            "request": any,
            "query": {
                "type": Types.String,
                "required": True,
            },
            "node_count": {
                "type": Types.Number,
                "required": True
            },
            "edge_count": {
                "type": Types.Number,
                "required": True
            },
            "node_types": [{
                "type": Types.String,
            }],
            "node_count_by_label": any,
            "edge_count_by_label": any,
            "title": {
                "type": Types.String,
                "required": True,
            },
            "summary": {
                "type": Types.String,
                "required": True,
            },
            "question": {
                "type": Types.String
            },
            "answer": {
                "type": Types.String
            },
            "created_at": {
                "type": Types.Date,
                "required": True,
                "default": datetime.datetime.now()
            },
            "updated_at": {
                "type": Types.Date,
                "required": True,
                "default": datetime.datetime.now()
            }
        }
        
        super().__init__(self.schema_name, self.schema, kwargs)

    def __str__(self):
        return f"user_id: {self.user_id}, query: {self.query}, title: {self.title}, summary: {self.summary}, question: {self.question}, answer: {self.answer}"
