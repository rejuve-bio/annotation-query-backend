from app.constants import TaskStatus

class RedisStopEvent:
    """
    Mimics threading.Event but checks a Redis key.
    Used to cancel loops inside Celery tasks.
    """
    def __init__(self, annotation_id, redis_client):
        self.annotation_id = annotation_id
        self.redis = redis_client

    def is_set(self):
        # Check if the status in Redis is 'CANCELLED'
        status = self.redis.hget(f"annotation:{self.annotation_id}", "status")
        
        if status:
            # Decode if bytes (Redis standard)
            if isinstance(status, bytes):
                status = status.decode('utf-8')
            return status == TaskStatus.CANCELLED.value
        return False
    
    def get_status(self):
        status = self.redis.hget(f"annotation:{self.annotation_id}", "status")
        return status

    def set_event(self):
        status = self.redis.hget(f"annotation:{self.annotation_id}", "status")
        if status:
            self.redis.hset(f"annotation:{self.annotation_id}", "status", TaskStatus.CANCELLED.value)