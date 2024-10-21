from app import app
from db import mongo_init

if __name__ == '__main__':
    mongo_init()
    app.run(debug=True, host='0.0.0.0', port=5000)
    
    