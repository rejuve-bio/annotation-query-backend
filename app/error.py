class ThreadStopException(Exception):
    def __init__(self, message):
        super().__init__(message)
        
class TaskCancelledException(Exception):
    pass


class NeighbourhoodUnavailableError(Exception):
    """The backend cannot run neighbourhood expansion yet (e.g. its index is still being built)."""
