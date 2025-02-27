from app import app, socketio
from dotenv import load_dotenv
import os
import logging

load_dotenv()

APP_PORT = int(os.getenv('APP_PORT', 8000))

# Remove all existing handlers
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

# Get the directory of the current script
script_dir = os.path.dirname(os.path.abspath(__file__))

# Construct the full path to the log file dynamically
log_dir = os.path.join(script_dir, 'logs')
os.makedirs(log_dir, exist_ok=True)  # Create 'logs' directory if it doesn’t exist
log_file = os.path.join(log_dir, 'error.log')

# Setup basic logging with the dynamic full path
logging.basicConfig(filename=log_file, level=logging.DEBUG)

if __name__ == '__main__':
    socketio.run(app, debug=False, host='0.0.0.0', port=APP_PORT)
