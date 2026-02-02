from celery import Celery, chord
import redis
from dotenv import load_dotenv
from app.constants import TaskStatus
import os 
from db import mongo_init
from celery.signals import worker_process_init

load_dotenv()

celery_app = Celery(
    "annotation_service",
    broker=os.getenv('REDIS_URL_BROKER'),
    backend=os.getenv("REDIS_URL")   
)

redis_state = redis.Redis(host='redis', port=6379, db=2)

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