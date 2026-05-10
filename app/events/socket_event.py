import logging
from app.socketio.server import sio
from app.workers.task_handler import get_annotation_redis
from app.constants import TaskStatus

logger = logging.getLogger(__name__)

@sio.event
async def connect(sid, environ, auth=None):
    logger.info(f"User connected with SID: {sid}")
    await sio.emit('message', 'Connected to server', to=sid)

@sio.event
async def disconnect(sid):
    logger.info(f"User disconnected: {sid}")

@sio.on('join')
async def on_join(sid, data):
    room = data['room']
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