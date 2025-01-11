from app import app, socketio
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Fetch the application port from environment variables
APP_PORT = os.getenv('APP_PORT', 5000)  # Default to 5000 if APP_PORT is not set

if __name__ == '__main__':
    # Run the Flask application with SocketIO support
    socketio.run(app, debug=True, host='0.0.0.0', port=int(APP_PORT))
