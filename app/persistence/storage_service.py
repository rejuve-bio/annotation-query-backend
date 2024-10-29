from app.models.storage import Storage

class StorageService():
    def __init__(self):
        pass
    
    def save(self, user_id, data, title, summary):
        data = Storage(
                user_id=user_id,
                query=data,
                title=title,
                summary=summary
                )

        data.save()

    def get(self, user_id):
        data = Storage.find({"user_id": user_id}, one=True)
        return data
    
    def get_all(self, user_id, page_number):
        data = Storage.find({"user_id": user_id}).sort('_id', -1).skip((page_number - 1) * 10).limit(10)
        return data
    
    def get_by_id(self, id):
        data = Storage.find_by_id(id)
        return data
    
    def get_user_query(self, user_id, query):
        data = Storage.find_one({"user_id": user_id, "query": query})
        return data
    
    def update(self, id, data):
        data = Storage.update({"_id": id}, {"$set": data}, many=False)

        
