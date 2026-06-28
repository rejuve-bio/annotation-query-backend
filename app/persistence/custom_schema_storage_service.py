import logging
import datetime
from app.models.custom_schema import CustomSchema

logger = logging.getLogger(__name__)

class CustomSchemaStorageService:

    @staticmethod
    def get_by_user_id(user_id: str):
        try:
            result = CustomSchema.find({"user_id": user_id})
            return list(result)
        except Exception as e:
            logger.error(f"Error fetching custom schemas for user {user_id}: {e}")
            return []

    @staticmethod
    def get_by_folder_id(user_id: str, folder_id: str):
        try:
            result = CustomSchema.find_one({
                "user_id": user_id,
                "folder_id": folder_id
            })
            return result
        except Exception as e:
            logger.error(f"Error fetching custom schema {folder_id} for user {user_id}: {e}")
            return None

    @staticmethod
    def upsert(user_id: str, folder_id: str, name: str):
        try:
            existing = CustomSchema.find_one({
                "user_id": user_id,
                "folder_id": folder_id
            })

            if existing:
                CustomSchema.find_one_and_update(
                    {"user_id": user_id, "folder_id": folder_id},
                    {"$set": {
                        "name": name,
                        "updated_at": datetime.datetime.now()
                    }}
                )
                return CustomSchema.find_one({
                    "user_id": user_id,
                    "folder_id": folder_id
                })
            else:
                new_schema = CustomSchema(
                    user_id=user_id,
                    folder_id=folder_id,
                    name=name,
                    created_at=datetime.datetime.now(),
                    updated_at=datetime.datetime.now()
                )
                new_schema.save()
                return new_schema

        except Exception as e:
            logger.error(f"Error upserting custom schema {folder_id} for user {user_id}: {e}")
            return None