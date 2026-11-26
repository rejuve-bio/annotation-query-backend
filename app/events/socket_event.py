import logging
from fastapi import HTTPException
from socketio.exceptions import ConnectionRefusedError
from app.api.annotation_id import validate_annotation_id
from app.api.auth import get_current_user
from app.socketio.server import sio
from app.workers.task_handler import get_annotation_redis
from app.persistence import AnnotationStorageService, NeighbourhoodStorageService

logger = logging.getLogger(__name__)

# sid -> authenticated user_id, populated on connect
_authenticated_users = {}

@sio.event
async def connect(sid, environ, auth=None):
    token = (auth or {}).get('token') if isinstance(auth, dict) else None
    try:
        user_id = get_current_user(token)
    except HTTPException:
        logger.warning("Rejected unauthenticated annotation socket")
        raise ConnectionRefusedError("Authentication required") from None

    _authenticated_users[sid] = str(user_id)
    logger.info(f"User connected with SID: {sid}")
    await sio.emit('message', 'Connected to server', to=sid)

@sio.event
async def disconnect(sid):
    _authenticated_users.pop(sid, None)
    logger.info(f"User disconnected: {sid}")

@sio.on('join')
async def on_join(sid, data):
    current_user_id = _authenticated_users.get(sid)
    if not current_user_id:
        logger.warning(f"Rejected join from unauthenticated socket: {sid}")
        return

    try:
        room = validate_annotation_id(data.get("room") if isinstance(data, dict) else None)
    except HTTPException:
        return

    annotation = AnnotationStorageService.get_by_id(room)
    if annotation is not None:
        owner_id = annotation.user_id
        participants = annotation.participant_user_ids or []
        if str(owner_id) != str(current_user_id) and str(current_user_id) not in participants:
            logger.warning(f"User {current_user_id} denied access to room {room}")
            return
    else:
        job = NeighbourhoodStorageService.get_by_id(room)
        # Unknown rooms are refused too: a deleted job's room could otherwise
        # be joined by anyone who knows its id.
        if job is None or str(job.user_id) != str(current_user_id):
            logger.warning(f"User {current_user_id} denied access to room {room}")
            return

    await sio.enter_room(sid, room)
    logger.info(f"User join a room with {room}")
    cache = get_annotation_redis(room)

    if cache is not None:
        status = cache.get('status')
        graph = cache.get('graph')
        graph_status = True if graph is not None else False

        await sio.emit("update", {"status": status, "update": {"graph": graph_status}}, to=sid)
