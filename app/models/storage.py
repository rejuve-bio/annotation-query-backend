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
    node_count = None
    edge_count = None
    node_types = None
    node_count_by_lable = None
    edge_count_by_label = None
    status = None

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
            },
            "edge_count": {
                "type": Types.Number,
            },
            "node_types": [{
                "type": Types.String,
                "required": True,
            }],
            "node_count_by_label": any,
            "edge_count_by_label": any,
            "title": {
                "type": Types.String,
                "required": True,
            },
            "summary": {
                "type": Types.String,
            },
            "question": {
                "type": Types.String
            },
            "answer": {
                "type": Types.String
            },
            "status": {
                "type": Types.String,
                "required": True
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
        return f"""user_id: {self.user_id}, query: {self.query},
        title: {self.title}, summary: {self.summary},
        question: {self.question}, answer: {self.answer},
        node_count: {self.node_count}, edge_count: {self.edge_count},
        node_count_by_label: {self.node_count_by_lable},
        edge_count_by_label: {self.edge_count_by_label},
        status: {self.status}
        """
