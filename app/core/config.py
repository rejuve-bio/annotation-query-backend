import os
import secrets
from typing import List, Optional

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Annotation Query Backend"

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = ["*"]

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"
    REDIS_EXPIRATION: int = 3600

    # Mail
    MAIL_SERVER: Optional[str] = None
    MAIL_PORT: Optional[int] = None
    MAIL_USE_TLS: bool = False
    MAIL_USE_SSL: bool = False
    MAIL_USERNAME: Optional[str] = None
    MAIL_PASSWORD: Optional[str] = None
    MAIL_DEFAULT_SENDER: Optional[str] = None

    # Database
    DATABASE_TYPE: dict = {}

    # Elasticsearch
    ES_URL: Optional[str] = None
    ES_API_KEY: Optional[str] = None

    # App
    APP_PORT: int = 8000

    # Auth
    JWT_SECRET: Optional[str] = None
    SECRET_KEY: Optional[str] = None  # Legacy support

    # Mongo
    MONGO_URI: Optional[str] = None

    class Config:
        case_sensitive = True
        env_file = ".env"
        extra = "ignore"  # Allow extra env vars without validation error

    @field_validator("MAIL_PORT", mode="before")
    @classmethod
    def parse_mail_port(cls, v):
        if v == "" or v is None:
            return None
        return v

    @field_validator("DATABASE_TYPE", mode="before")
    @classmethod
    def load_db_type_from_yaml(cls, v):
        db_config = v
        try:
            config_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "config", "config.yaml"
            )
            if os.path.exists(config_path):
                with open(config_path, "r") as file:
                    full_yaml = yaml.safe_load(file)
                    if full_yaml and "database" in full_yaml:
                        # Return the WHOLE database dict so we keep 'human' and 'fly' keys
                        db_config = full_yaml["database"]
        except Exception:
            pass
            
        # Ensure it's a dict and set a default species if missing
        if isinstance(db_config, dict):
            if not db_config.get("species"):
                db_config["species"] = "human"
        elif isinstance(db_config, str):
            db_config = {"type": db_config, "species": "human"}
            
        return db_config

settings = Settings()