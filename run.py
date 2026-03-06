from app import app, socketio
from dotenv import load_dotenv
from db import mongo_init
import os

load_dotenv()

APP_PORT = int(os.getenv('APP_PORT', 8000))

mongo_init()

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=APP_PORT)
