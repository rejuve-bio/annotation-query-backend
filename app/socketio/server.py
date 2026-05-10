import socketio
import os


redis_url = os.getenv('REDIS_URL_BROKER', 'redis://redis:6379/1')

# 2. Create the Redis manager
client_manager = socketio.AsyncRedisManager(redis_url)

# 3. Create SocketIO server (Async) and pass the manager in
sio = socketio.AsyncServer(
    async_mode='asgi', 
    cors_allowed_origins='*',
    client_manager=client_manager,
    transports=['websocket']
)