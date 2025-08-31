from app.models.user import User


class UserStorageService():
    def __init__(self):
        pass

    @staticmethod
    def save(user):
        data = User(
            user_id=user["current_user_id"],
            data_source=user["data_source"],
            species=user["species"],
        )

        id = data.save()
        return id

    @staticmethod
    def get(user_id):
        data = User.find({"user_id": user_id}, one=True)
        return data

    @staticmethod
    def upsert_by_user_id(id, data):
        print(User.find_one({"user_id": id}))
        if User.find_one({"user_id": id}):
            User.update({"user_id": id}, {"$set": data}, many=False)
        else:
            print(data)
            print("trying to save")
            User(user_id=id, **data).save()

    @staticmethod
    def delete(id):
        data = User.delete({"_id": id})
        return data
