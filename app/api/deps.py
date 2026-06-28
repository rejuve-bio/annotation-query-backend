
from typing import Optional, Any
import redis
import meilisearch
import jwt
import logging
import os
 
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
 
from app.core.config import settings
from app.services.schema_data import SchemaManager
from app.services.cypher_generator import CypherQueryGenerator
from app.services.metta_generator import MeTTa_Query_Generator
from app.services.mork_generator import MorkQueryGenerator
from app.services.llm_handler import LLMHandler
 
logger = logging.getLogger(__name__)
 
# --- Private Singleton Storage ---
_redis_client: Optional[redis.Redis] = None
_schema_manager: Optional[SchemaManager] = None
_db_instance: Any = None
_llm_handler: Optional[LLMHandler] = None
_meili_client: Optional[meilisearch.Client] = None 
 
# --- Security Setup ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)
 
# --- Dependency Functions ---

def get_redis_client() -> redis.Redis:
    """
    Returns a singleton Redis client. 
    """
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(
                settings.REDIS_URL, 
                decode_responses=True
            )
            logger.info(f"✅ [Deps] Connected to Redis at {settings.REDIS_URL}")
        except Exception as e:
            logger.error(f"❌ [Deps] Failed to connect to Redis: {e}")
            raise e
    return _redis_client

def get_meili_client() -> meilisearch.Client:
    """Returns a singleton Meilisearch client."""
    global _meili_client
    if _meili_client is None:
        url = os.getenv("MEILI_URL", "http://meilisearch:7700")
        key = os.getenv("MEILI_MASTER_KEY", "")
        try:
            _meili_client = meilisearch.Client(url, key)
            # Quick health check
            _meili_client.health()
            logger.info(f"✅ [Deps] Meilisearch connected at {url}")
        except Exception as e:
            logger.error(f"❌ [Deps] Meilisearch connection error: {e}")
            # Return the client anyway — let the endpoint handle the error
            _meili_client = meilisearch.Client(url, key)
    return _meili_client

def get_schema_manager() -> SchemaManager:
    """Returns a singleton SchemaManager instance."""
    global _schema_manager
    if _schema_manager is None:
        _schema_manager = SchemaManager(
            schema_config_path='./config/schema_config.yaml',
            biocypher_config_path='./config/biocypher_config.yaml',
            config_path='./config/schema',
            fly_schema_config_path='./config/fly_base_schema/net_act_essential_schema_config.yaml'
        )
        logger.info("✅ [Deps] SchemaManager initialized")
    return _schema_manager

def _load_mork_cli_generator():
    mork_data_dir = os.environ.get("MORK_DATA_DIR")
    if not mork_data_dir:
        logging.error("MORK_DATA_DIR is not set.")
        raise RuntimeError("MORK_DATA_DIR is not set.")
    module = importlib.import_module("app.services.mork_cli_generator")
    return module.MorkCLIQueryGenerator(mork_data_dir)

def get_db_instance() -> Any:
    """Returns a singleton Database Query Generator instance based on settings."""
    global _db_instance
    if _db_instance is None:
        databases = {
            "metta": lambda: MeTTa_Query_Generator("./Data"),
            "cypher": lambda: CypherQueryGenerator("./cypher_data"),
            "mork": lambda: MorkQueryGenerator("./mork_data"),
            "mork_cli": lambda: _load_mork_cli_generator()
        }
        db_type = settings.DATABASE_TYPE
        if db_type in databases:
            _db_instance = databases[db_type]()
            logger.info(f"✅ [Deps] Database instance ({db_type}) initialized")
        else:
            raise ValueError(f"Unknown database type: {db_type}")
    return _db_instance

def get_llm_handler() -> LLMHandler:
    """Returns a singleton LLMHandler instance."""
    global _llm_handler
    if _llm_handler is None:
        _llm_handler = LLMHandler()
        logger.info("✅ [Deps] LLMHandler initialized")
    return _llm_handler

def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    """
    FastAPI dependency to validate JWT and return the user_id.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token is missing!",
        )
    
    try:
        if not settings.JWT_SECRET:
             raise HTTPException(status_code=500, detail="JWT_SECRET not configured")
             
        data = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        current_user_id = data.get('user_id')
        
        if not current_user_id:
             raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Token is invalid!",
            )
        return str(current_user_id)
    except Exception as e:
        logger.error(f"Error decoding token: {e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token is invalid!",
        )
        
async def get_current_user_test():
    return "9"