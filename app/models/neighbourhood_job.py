import datetime

from pymongoose.mongo_types import Schema, Types


class NeighbourhoodJob(Schema):
    schema_name = 'neighbourhood_job'

    # Attributes
    id = None
    user_id = None
    request = None
    species = None
    fingerprint = None
    status = None
    hops = None
    seed = None
    node_count = None
    edge_count = None
    truncated = None
    result_path = None
    error = None
    created_at = None
    updated_at = None

    def __init__(self, **kwargs):
        self.schema = {
            "user_id": {"type": Types.String, "required": True, "index": True},
            "request": any,
            "species": {"type": Types.String, "required": True, "default": "human"},
            "fingerprint": {"type": Types.String, "index": True},
            "status": {"type": Types.String, "required": True},
            "hops": any,
            "seed": any,
            "node_count": {"type": Types.Number},
            "edge_count": {"type": Types.Number},
            "truncated": any,
            "result_path": {"type": Types.String},
            "error": {"type": Types.String},
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
