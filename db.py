import os
import logging
from pymongo import MongoClient
from pymongoose.methods import set_schemas
from app.models.annotation import Annotation
from app.models.user import User
from app.models.shared_annotation import SharedAnnotation

MONGO_URI = os.environ.get("MONGO_URI")

_client = None
_db = None

def mongo_init():
    global _client, _db

    if _client is not None:
        return _db  # already initialized in this process

    _client = MongoClient(
        MONGO_URI,
        maxPoolSize=20,
        connectTimeoutMS=5000,
    )

    _db = _client.test

    schemas = {
        "annotation": Annotation(empty=True).schema,
        "user": User(empty=True).schema,
        "shared_annotation": SharedAnnotation(empty=True).schema,
    }

    set_schemas(_db, schemas)
    logging.info("MongoDB Connected!")

    return _db

def get_db():
    if _db is None:
        raise RuntimeError("MongoDB not initialized in this process")
    return _db
