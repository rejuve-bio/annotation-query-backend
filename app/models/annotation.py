import datetime

from pymongoose.mongo_types import Schema, Types

class Annotation(Schema):
    schema_name = 'annotation'

    # Attributes
    id = None
    user_id = None
    request = None
    query = None
    title = None
    summary = None
    question = None
    answer = None
    node_count = None
    edge_count = None
    node_types = None
    node_count_by_label = None
    edge_count_by_label = None
    status = None
    created_at = None
    updated_at = None
    data_source = None
    files = None
    species = None
    path_url = None
    retrieval_duration = None
    processing_duration = None
    total_duration = None

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
            "node_types": [
                {
                    "type": Types.String,
                    "required": True,
                }
            ],
            "node_count_by_label": any,
            "edge_count_by_label": any,
            "title": {
                "type": Types.String,
                "required": True,
            },
            "summary": {
                "type": Types.String,
            },
            "question": {"type": Types.String},
            "answer": {"type": Types.String},
            "status": {"type": Types.String, "required": True},
            "path_url": Types.String,
            "retrieval_duration": Types.String,
            "processing_duration": Types.String,
            "total_duration": Types.String,
            "species": {"type": Types.String, "required": True, "default": "human"},
            "data_source": any,
            "files": any,
            "created_at": {
                "type": Types.Date,
                "required": True,
                "default": datetime.datetime.now(),
            },
            "updated_at": {
                "type": Types.Date,
                "required": True,
                "default": datetime.datetime.now(),
            },
        }

        super().__init__(self.schema_name, self.schema, kwargs)

    def __str__(self):
        return f"""user_id: {self.user_id}, request: {self.request},
        query: {self.query},
        title: {self.title}, summary: {self.summary},
        question: {self.question}, answer: {self.answer},
        node_count: {self.node_count}, edge_count: {self.edge_count},
        node_count_by_label: {self.node_count_by_label},
        edge_count_by_label: {self.edge_count_by_label},
        status: {self.status}, species: {self.species}, data_source: {self.data_source}
        path_url: {self.path_url}, created_at: {self.created_at}, updated_at: {self.updated_at}
        """
