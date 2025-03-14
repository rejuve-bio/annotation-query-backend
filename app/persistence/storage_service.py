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
            summary=annotation.get("summary", None),
            question=annotation.get("question", None),
            answer=annotation.get("answer", None),
            node_count=annotation.get("node_count", None),
            edge_count=annotation.get("edge_count", None),
            node_types=annotation["node_types"],
            node_count_by_label=annotation.get("node_count_by_label", None),
            edge_count_by_label=annotation.get("edge_count_by_label", None),
            status=annotation.get('status', 'PENDING')
        )

        id = data.save()
        return id

    def get(self, user_id):
        data = Storage.find({"user_id": user_id}, one=True)
        return data

    def get_all(self, user_id, page_number):
        data = Storage.find({"user_id": user_id}).sort(
            '_id', -1).skip((page_number - 1) * 10).limit(10)
        return data

    def get_by_id(self, id):
        data = Storage.find_by_id(id)
        return data

    def get_user_query(self, annotation_id, user_id, query):
        data = Storage.find_one(
            {"_id": annotation_id, "user_id": user_id, "query": query})
        return data
    
    def get_user_annotation(self, annotation_id, user_id):
        data = Storage.find_one({"_id": annotation_id, "user_id": user_id})
        return data

    def update(self, id, data):
        data = Storage.update({"_id": id}, {"$set": data}, many=False)

    def delete(self, id):
        data = Storage.delete({"_id": id})
        return data
    
    def delete_many_by_id(self, ids):
        delete_count = 0
        
        for id in ids:
            self.delete(id)
            delete_count += 1
        
        return delete_count