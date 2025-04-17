import os
import traceback
import logging
from pymongo import MongoClient
from pymongoose.methods import set_schemas
from app.models.annotation import Annotation
from app.models.user import User

MONGO_URI = os.environ.get("MONGO_URI")

mongo_db = None


def mongo_init():
    global mongo_db

    client = MongoClient(MONGO_URI)
    db = client.test
    try:
        # Define the shcemas

        schemas = {
            "annotation": Annotation(empty=True).schema,
            "user": User(empty=True).schema,
        }

        set_schemas(db, schemas)

        logging.info("MongoDB Connected!")
    except Exception as e:
        traceback.print_exc()
        logging.error(f"Error initializing database {e}")
        exit(1)
