import pymongo

client = pymongo.MongoClient("mongodb://127.0.0.1:27017")

db = client["fomc"]

metadata = db["fomc_metadata"]
minutes_raw = db["fomc_minutes_raw"]
minutes_clean = db["fomc_minutes_clean"]

data = {"name": "Alex"}
#db["fomc_metadata"].insert_one(data)
#minutes_clean.insert_one(data)

col_list = db.list_collection_names()
print(col_list)
