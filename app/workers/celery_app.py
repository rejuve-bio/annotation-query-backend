from celery import Celery, chord
import redis
from dotenv import load_dotenv
from app.constants import TaskStatus
import os 
from db import mongo_init
from celery.signals import worker_process_init, worker_ready
from urllib.parse import urlparse
from app.core.config import settings
load_dotenv()

celery_app = Celery(
    "annotation_service",
    broker=os.getenv('REDIS_URL_BROKER'),
    backend=os.getenv("REDIS_URL")   
)

celery_app.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    result_expires=3600,
)

REDIS_URL = settings.REDIS_URL
parsed = urlparse(REDIS_URL)
host = parsed.hostname or 'localhost'
port = parsed.port or 6379
password = parsed.password

redis_state = redis.Redis(host=host, port=port, password=password, db=2)

def init_request_state(request_id):
    redis_state.hmset(f"annotation:{request_id}", {
        "status": TaskStatus.PENDING.value,
        "graph_done": 0,
        "count_by_label_done": 0,
        "total_count_done": 0,
        "summary_done": 0
    })
    
@worker_process_init.connect
def init_mongo_worker(**kwargs):
    mongo_init()
    if settings.DATABASE_TYPE.get("type") == "mork_cli":
        from app.services.mork_cli_generator import set_keep_containers_on_exit
        set_keep_containers_on_exit(True)


@worker_ready.connect
def queue_mork_neighbourhood_index(**kwargs):
    """Build the MORK neighbourhood index in the background if the ACT changed."""
    if settings.DATABASE_TYPE.get("type") != "mork_cli":
        return
    from app.workers.neighbourhood_task import request_index_build
    for species in ("human", "fly"):
        data_dir = os.environ.get(f"{species.upper()}_MORK_DATA_DIR") or \
            settings.DATABASE_TYPE.get(species, {}).get("data_dir")
        if data_dir and os.path.exists(data_dir):
            request_index_build(species)
