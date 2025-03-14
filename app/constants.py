from enum import Enum

class TaskStatus(Enum):
    PENDING = 'PENDING'
    CANCELLED = 'CANCELLED'
    COMPLETE = 'COMPLETE'
    FAILED = 'FAILED'