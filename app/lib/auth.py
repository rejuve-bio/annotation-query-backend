from flask import request, jsonify
from flask_socketio import disconnect
import jwt
from functools import wraps
from dotenv import load_dotenv
import logging
import os
# Load environment variables from .env file
load_dotenv()

# JWT Secret Key
JWT_SECRET = os.getenv("JWT_SECRET")

def token_required(f) -> any:
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 403

        try:
            # Remove 'Bearer' prefix if present
            if 'Bearer' in token:
                token = token.split()[1]

            data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            current_user_id = data['user_id']
        except Exception as e:
            logging.error(f"Error docodcing token: {e}")
            return {'message': 'Token is invalid!'}, 403

        # Pass current_user_id and maintain other args
        return f(current_user_id, *args, **kwargs)
    return decorated


def socket_token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        logging.info(f"Checking token for {f.__name__}")
        try:
            # Get auth token from connection args
            auth_header = None
            # Try to get from handshake auth
            if hasattr(request, 'args'):
                auth_header = request.args.get('token')
                logging.info(
                    f"Token from args: {auth_header[:10] if auth_header else None}")

            # Try to get from headers
            if not auth_header and hasattr(request, 'headers'):
                auth_header = request.headers.get('Authorization')
                logging.info(
                    f"Token from headers: {auth_header[:10] if auth_header else None}")

            # Try to get from socket environment
            if not auth_header and hasattr(self, 'server'):
                client_sid = args[0] if args else None
                logging.info(f"Client SID: {client_sid}")
                if client_sid:
                    environ = self.server.get_client(client_sid).environ
                    auth_header = environ.get('HTTP_AUTHORIZATION')
                    logging.info(
                        f"Token from environ: {auth_header[:10] if auth_header else None}")

            if not auth_header:
                logging.error("No token found in any location")
                disconnect()
                return False

            if 'Bearer' in auth_header:
                token = auth_header.split()[1]
            else:
                token = auth_header

            try:
                data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
                current_user_id = data['user_id']
                logging.info(
                    f"Token decoded successfully for user: {current_user_id}")
            except Exception as e:
                logging.error(f"Token decode error: {e}")
                disconnect()
                return False

            # Pass current_user_id and maintain other args
            return f(current_user_id, *args, **kwargs)
        except Exception as e:
            logging.error(f"Socket auth error in {f.__name__}: {str(e)}")
            disconnect()
            return False
    return decorated
