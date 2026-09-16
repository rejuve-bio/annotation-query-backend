import logging
import jwt
from app.socketio.server import sio
from app.workers.task_handler import get_annotation_redis
from app.constants import TaskStatus
from app.core.config import settings
from app.persistence import AnnotationStorageService

logger = logging.getLogger(__name__)

# sid -> authenticated user_id, populated on connect
_authenticated_users = {}

@sio.event
async def connect(sid, environ, auth=None):
    token = (auth or {}).get('token') if isinstance(auth, dict) else None
    if not token or not settings.JWT_SECRET:
        logger.warning(f"Rejected unauthenticated socket connection: {sid}")
        raise ConnectionRefusedError("Authentication required")

    try:
        data = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        user_id = data.get("user_id")
        if not user_id:
            raise ValueError("Token missing user_id")
    except Exception as e:
        logger.warning(f"Rejected socket connection with invalid token: {e}")
        raise ConnectionRefusedError("Invalid or expired token")

    _authenticated_users[sid] = str(user_id)
    logger.info(f"User connected with SID: {sid}")
    await sio.emit('message', 'Connected to server', to=sid)

@sio.event
async def disconnect(sid):
    _authenticated_users.pop(sid, None)
    logger.info(f"User disconnected: {sid}")

@sio.on('join')
async def on_join(sid, data):
    room = data['room']

    current_user_id = _authenticated_users.get(sid)
    if not current_user_id:
        logger.warning(f"Rejected join from unauthenticated socket: {sid}")
        return

    annotation = AnnotationStorageService.get_by_id(room)
    if annotation is not None:
        owner_id = annotation.user_id
        participants = annotation.participant_user_ids or []
        if str(owner_id) != str(current_user_id) and str(current_user_id) not in participants:
            logger.warning(f"User {current_user_id} denied access to room {room}")
            return

    await sio.enter_room(sid, room)
    logger.info(f"User join a room with {room}")
    cache = get_annotation_redis(room)

    if cache is not None:
        status = cache.get('status')
        graph = cache.get('graph')
        graph_status = True if graph is not None else False

        if status == TaskStatus.COMPLETE.value:
            await sio.emit('update', {'status': status, 'update': {'graph': graph_status}},
                  to=str(room))
        else:
            await sio.emit('update', {'status': status, 'update': {'graph': graph_status}}, to=str(room))