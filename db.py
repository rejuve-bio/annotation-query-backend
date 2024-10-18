import os, traceback
from pymongo import MongoClient
from pymongoose.methods import set_schemas
from app.models.storage import Storage

MONGO_URI = os.environ.get("MONGO_URI")

mongo_db = None

def mongo_init():
    global mongo_db

    client = MongoClient(MONGO_URI)
    db = client.test
    try:
        # Define the shcemas
            
        schemas = {
            "storage": Storage(empty=True).schema
        }

        set_schemas(db, schemas)

        print("MongoDB Connected!")
    except:
        traceback.print_exc()
        print("Error initializing database")
        exit(1)
