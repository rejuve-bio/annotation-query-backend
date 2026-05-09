import os
import logging
from pymongo import MongoClient
from pymongoose.methods import set_schemas
from app.models.annotation import Annotation
from app.models.user import User
from app.models.shared_annotation import SharedAnnotation
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

MONGO_URI = os.environ.get("MONGO_URI")

_client = None
_db = None

def mongo_init():
    global _client, _db

    if _client is not None:
        return _db  # already initialized in this process

    if not MONGO_URI:
        logger.error("MONGO_URI is not set in environment variables.")
        raise ValueError("MONGO_URI environment variable is required but was not found.")

    try:
        _client = MongoClient(
            MONGO_URI,
            maxPoolSize=20,
            connectTimeoutMS=5000,
            serverSelectionTimeoutMS=5000 
        )

        # Trigger a call to check if connection is valid immediately
        _client.admin.command('ping')
        
        _db = _client.get_default_database()

        schemas = {
            "annotation": Annotation(empty=True).schema,
            "user": User(empty=True).schema,
            "shared_annotation": SharedAnnotation(empty=True).schema,
        }

        set_schemas(_db, schemas)
        logger.info("MongoDB Connected!")

    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        _client = None
        _db = None
        raise

    return _db

def get_db():
    if _db is None:
        raise RuntimeError("MongoDB not initialized in this process")
    return _db