"""The optional chat `thread_id` a query was started from (Threads API v1)."""
import uuid


def parse_thread_id(value):
    """Return the thread id as a lowercase UUIDv4 string, or None when absent.

    Raises ValueError for anything that is not a UUIDv4.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("thread_id must be a UUIDv4 string")
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise ValueError("thread_id must be a UUIDv4 string")
    if parsed.version != 4 or str(parsed) != value.lower():
        raise ValueError("thread_id must be a UUIDv4 string")
    return str(parsed)
