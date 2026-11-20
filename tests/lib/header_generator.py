import jwt
from app.core.config import settings

def generate_headers():
    token = jwt.encode({"user_id": "some_id"}, settings.JWT_SECRET, algorithm="HS256")

    headers = {
            'Authorization': f'Bearer {token}'
    }
    return headers
