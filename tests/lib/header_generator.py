import jwt
from app.lib.auth import JWT_SECRET

def generate_headers():       
    token = jwt.encode({"user_id": "some_id"}, JWT_SECRET, algorithm="HS256")

    headers = {
            'Authorization': f'Bearer {token}'         
    }
    return headers
