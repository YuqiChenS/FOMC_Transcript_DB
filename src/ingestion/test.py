import logging

from ..storage.mongo_client import MongoDatabase
from .ingest_minutes import MinutesIngestor


def main():
    logging.basicConfig(level=logging.INFO)
    db = MongoDatabase()
    ingestor = MinutesIngestor(db)
    print(ingestor.ingest_unscraped())


if __name__ == "__main__":
    main()
