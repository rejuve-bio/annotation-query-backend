from pymongoose.mongo_types import Types, Schema

class User(Schema):
    schema_name = 'user'

    # Attributes
    id = None
    user_id = None
    data_source = None
    species = None

    def __init__(self, **kwargs):
        self.schema = {
            "user_id": {
                "type": Types.String,
                "required": True,
            },
            "species": {
                "type": Types.String,
                "required": True,
                "default": "human"
            },
            "data_source": any
        }
               
        super().__init__(self.schema_name, self.schema, kwargs)

    def __str__(self):
        return f"""user_id: {self.user_id}, species: {self.species}, data_source: {self.data_source}
        """
