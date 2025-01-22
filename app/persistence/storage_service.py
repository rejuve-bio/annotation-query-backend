from app.models.storage import Storage

class StorageService():
    def __init__(self):
        pass
    
    def save(self, annotation):
        data = Storage(
            user_id=annotation["current_user_id"],
            request=annotation["request"],
            query=annotation["query"],
            title=annotation["title"],
            summary=annotation["summary"],
            question=annotation["question"],
            answer=annotation["answer"],
            node_count=annotation["node_count"],
            edge_count=annotation["edge_count"],
            node_types=annotation["node_types"],
            node_count_by_label=annotation["node_count_by_label"],
            edge_count_by_label=annotation["edge_count_by_label"]
            )

        id = data.save()
        return id

    def get(self, user_id):
        data = Storage.find({"user_id": user_id}, one=True)
        return data
    
    def get_all(self, user_id, page_number):
        data = Storage.find({"user_id": user_id}).sort('_id', -1).skip((page_number - 1) * 10).limit(10)
        return data
    
    def get_by_id(self, id):
        data = Storage.find_by_id(id)
        return data

    def get_user_query(self, annotation_id, user_id, query):
        data = Storage.find_one({"_id": annotation_id, "user_id": user_id, "query": query})
        return data
    
    def update(self, id, data):
        data = Storage.update({"_id": id}, {"$set": data}, many=False)

    def delete(self, id):
        data = Storage.delete({"_id": id})
        return data
