from pymongoose.mongo_types import Types, Schema
import datetime

class CustomSchema(Schema):
    schema_name = 'custom_schema'

    # Attributes
    id = None
    user_id = None
    folder_id = None
    name = None
    created_at = None
    updated_at = None

    def __init__(self, **kwargs):
        self.schema = {
            "user_id": {
                "type": Types.String,
                "required": True,
            },
            "folder_id": {
                "type": Types.String,
                "required": True,
            },
            "name": {
                "type": Types.String,
                "required": True,
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
        return (
            f"user_id: {self.user_id}, folder_id: {self.folder_id}, "
            f"name: {self.name}, created_at: {self.created_at}, "
            f"updated_at: {self.updated_at}"
        )