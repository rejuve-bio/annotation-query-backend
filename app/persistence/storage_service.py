from app.models.storage import Storage

class StorageService():
    def __init__(self):
        pass
    
    def save(self, user_id, type, data, title, summary):
        data = Storage(
                user_id=user_id,
                type=type,
                result=data,
                title=title,
                summary=summary
                )

        data.save()

    def get(self, user_id):
        data = Storage.find({"user_id": user_id}, one=True)
        return data
        
