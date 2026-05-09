import os
import asyncio
import json
import socketio
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.socketio.server import sio
from db import mongo_init
from app.api.api_v1.api import api_router
import app.events.socket_event
from fastapi.staticfiles import StaticFiles
import mimetypes
# Add always on listen for socket events
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"Connecting to Redis at {settings.REDIS_URL}...")
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()
    
    async def listen_to_redis():
        try:
            await pubsub.subscribe('socket_event')
            print("Successfully subscribed to Redis 'socket_event' channel.")
            
            async for message in pubsub.listen():
                if message and message['type'] == 'message':
                    raw_data = message['data']
                    
                    try:
                        
                        payload = json.loads(raw_data) 
                        
                        room = str(payload.get('annotation_id'))
                        print(f"DEBUG: Forwarding to Room {room}: {payload}")
                        
                        await sio.emit('update', payload, room=room)
                        
                    except json.JSONDecodeError:
                        print(f"Error: Redis sent invalid JSON: {raw_data}")
                    except Exception as e:
                        print(f"Error forwarding event: {e}")
                        
        except asyncio.CancelledError:
            print("Redis Listener task cancelling...")
        finally:
            await pubsub.unsubscribe('socket_event')
            await redis_client.aclose()
            print("Redis connection closed.")

    # Start the background task
    listener_task = asyncio.create_task(listen_to_redis())
    
    yield  # The FastAPI app is now "Live" and handles requests
    

    print("Shutting down: Signalling listener to stop...")
    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass

# Initialize FastAPI with Lifespan
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Middleware & Database
mongo_init()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Socket.IO Integration
socket_app = socketio.ASGIApp(sio, app)

# Route integration
app.include_router(api_router)

mimetypes.add_type('application/octet-stream', '.tbi')
mimetypes.add_type('application/gzip', '.gz')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")

os.makedirs(PUBLIC_DIR, exist_ok=True)
app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="static")

