import importlib
import logging
import os
from typing import Any, Dict, Optional

import jwt
import redis
from elasticsearch import Elasticsearch
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from app.services.cypher_generator import CypherQueryGenerator
from app.services.llm_handler import LLMHandler
from app.services.metta_generator import MeTTa_Query_Generator
from app.services.mork_generator import MorkQueryGenerator
from app.services.schema_data import SchemaManager

logger = logging.getLogger(__name__)

# --- Private Singleton Storage ---
_redis_client: Optional[redis.Redis] = None
_es_client: Optional[Elasticsearch] = None
_schema_manager: Optional[SchemaManager] = None
_db_instance: Any = None
_llm_handler: Optional[LLMHandler] = None

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
            _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
            logger.info(f"✅ [Deps] Connected to Redis at {settings.REDIS_URL}")
        except Exception as e:
            logger.error(f"❌ [Deps] Failed to connect to Redis: {e}")
            raise e
    return _redis_client


def get_es_client() -> Optional[Elasticsearch]:
    """Returns a singleton Elasticsearch client."""
    global _es_client
    if _es_client is None:
        if settings.ES_URL and settings.ES_API_KEY:
            try:
                _es_client = Elasticsearch(settings.ES_URL, api_key=settings.ES_API_KEY)
                if _es_client.ping():
                    logger.info("✅ [Deps] Elasticsearch connected")
                else:
                    logger.warning("⚠️ [Deps] Elasticsearch not reachable")
                    _es_client = None
            except Exception as e:
                logger.error(f"❌ [Deps] Elasticsearch connection error: {e}")
                _es_client = None
    return _es_client


def get_schema_manager() -> SchemaManager:
    """Returns a singleton SchemaManager instance."""
    global _schema_manager
    if _schema_manager is None:
        _schema_manager = SchemaManager(
            schema_config_path="./config/human_schema/human_full_schema_config.yaml",
            biocypher_config_path="./config/biocypher_config.yaml",
            config_path="./config/schema",
            fly_schema_config_path="./config/fly_base_schema/dmel_full_schema_config.yaml",
        )
        logger.info("✅ [Deps] SchemaManager initialized")
    return _schema_manager


def _make_mork_cli_generator(data_dir, act_file="annotation.act", species="human"):
    module = importlib.import_module("app.services.mork_cli_generator")
    return module.MorkCLIQueryGenerator(
        data_dir, act_filename=act_file, species=species
    )

def _load_mork_cli_generators():
    db_config = settings.DATABASE_TYPE
    instances = {}
    
    # Debug: See what settings actually loaded
    logger.info(f"🔍 [MORK Debug] DATABASE_TYPE settings: {db_config}")
    
    for species in ("human", "fly"):
        spec = db_config.get(species, {})
        
        # 1. Resolve Path
        env_key = f"{species.upper()}_MORK_DATA_DIR"
        env_path = os.environ.get(env_key)
        yaml_path = spec.get("data_dir")
        
        # Priority: Env Var > YAML > None
        data_dir = env_path or yaml_path
        act_file = spec.get("act_file", "annotation.act")
        
        logger.info(f"🔍 [MORK Debug] Species: {species} | Path Resolved: {data_dir}")

        if data_dir:
            # 2. Check if path exists inside the container
            if os.path.exists(data_dir):
                try:
                    instances[species] = _make_mork_cli_generator(
                        data_dir, act_file, species
                    )
                    logger.info(f"✅ [MORK] Successfully loaded {species} from {data_dir}")
                except Exception as e:
                    logger.error(f"❌ [MORK] Failed to initialize {species} generator: {e}")
            else:
                logger.error(f"❌ [MORK] Path does NOT exist inside container: {data_dir}")
        else:
            logger.warning(f"⚠️ [MORK] No path configured for {species}")

    if not instances:
        # This will now include the debug info in the crash report
        error_msg = f"No MORK generators loaded. Settings: {db_config} | ENV MORK_DATA_DIR: {os.environ.get('MORK_DATA_DIR')}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)
        
    return instances


# --- Private Singleton Storage ---
_db_instances: dict[str, Any] = {}  # keyed by species


def get_db_instance(species: str = "human") -> Any:
    """Returns a Database Query Generator instance for the given species."""
    global _db_instances

    if species not in _db_instances:
        db_type = settings.DATABASE_TYPE.get("type", "cypher")

        if db_type == "mork_cli":
            instances = _load_mork_cli_generators()
            _db_instances.update(instances)
        else:
            # non-species-aware backends, share same instance for all species
            databases = {
                "metta": lambda: MeTTa_Query_Generator("./Data"),
                "cypher": lambda: CypherQueryGenerator("./cypher_data"),
                "mork": lambda: MorkQueryGenerator("./mork_data"),
            }
            if db_type not in databases:
                raise ValueError(f"Unknown database type: {db_type}")
            instance = databases[db_type]()
            _db_instances["human"] = instance
            _db_instances["fly"] = instance

        if species not in _db_instances:
            raise ValueError(f"No database instance available for species: {species}")

        logger.info(f"✅ [Deps] Database instance ({db_type}/{species}) initialized")

    return _db_instances[species]


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
        current_user_id = data.get("user_id")

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
