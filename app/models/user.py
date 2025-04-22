from pymongoose.mongo_types import Types, Schema

class User(Schema):
    schema_name = 'user'

    # Attributes
    id = None
    user_id = None
    data_source = None

    def __init__(self, **kwargs):
        self.schema = {
            "user_id": {
                "type": Types.String,
                "required": True,
            },
            "data_source": any
        }
               
        super().__init__(self.schema_name, self.schema, kwargs)

    def __str__(self):
        return f"""user_id: {self.user_id}, data_source: {self.data_source}
        """
