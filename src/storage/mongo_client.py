import os
import logging
from datetime import datetime, timezone

import pymongo
from pymongo.errors import ConnectionFailure, ConfigurationError
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()


class MongoDatabase:
    """Connects to Mongo and sets up the fomc collections"""

    def __init__(self):
        uri = os.environ.get("MONGO_URI")
        if not uri:
            raise ConfigurationError("MONGO_URI environment variable is not set")

        self.client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)

        try:
            self.client.admin.command("ping")
        except ConnectionFailure as e:
            logger.error("Could not connect to MongoDB: %s", e)
            raise

        self.db = self.client["fomc"]

        self.metadata = self.db["fomc_metadata"]
        self.minutes_raw = self.db["fomc_minutes_raw"]
        self.minutes_clean = self.db["fomc_minutes_clean"]
        self.lda_metadata = self.db["fomc_lda_metadata"]
        self.bigrams = self.db["fomc_minutes_bigrams"]
        self._apply_schema_validation()
        self._ensure_indexes()

    MINUTES_RAW_VALIDATOR = {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["meeting_end", "raw_text", "scraped_at"],
            "properties": {
                "meeting_end": {"bsonType": "string"},
                "year": {"bsonType": "int"},
                "raw_text": {"bsonType": "string", "minLength": 20},
                "chair": {"bsonType": ["string", "null"]},
                "scraped_at": {"bsonType": "date"},
            },
        }
    }

    def _apply_schema_validation(self):
        """Add a schema validator to fomc_minutes_raw

        create_collection only works the first time, so if the collection
        already exists use collMod to update the validator instead.
        """
        try:
            self.db.create_collection(
                "fomc_minutes_raw",
                validator=self.MINUTES_RAW_VALIDATOR,
                validationLevel="moderate",
            )
            logger.info("created fomc_minutes_raw with schema validation")
        except pymongo.errors.CollectionInvalid:
            self.db.command(
                "collMod",
                "fomc_minutes_raw",
                validator=self.MINUTES_RAW_VALIDATOR,
                validationLevel="moderate",
            )
            logger.debug("updated fomc_minutes_raw validator")

    def _ensure_indexes(self):
        """meeting_end is the unique key, text index is for keyword search"""
        self.metadata.create_index([("meeting_end", pymongo.ASCENDING)], unique=True)
        self.metadata.create_index([("year", pymongo.ASCENDING)])

        self.minutes_raw.create_index([("meeting_end", pymongo.ASCENDING)], unique=True)
        self.minutes_raw.create_index([("raw_text", pymongo.TEXT)])
        self.minutes_raw.create_index([("year", pymongo.ASCENDING)])

        self.minutes_clean.create_index([("meeting_end", pymongo.ASCENDING)], unique=True)

    def integrity_check(self):
        """Quick summary of what's in the database"""
        return {
            "collections": self.db.list_collection_names(),
            "counts": {
                "metadata": self.metadata.count_documents({}),
                "minutes_raw": self.minutes_raw.count_documents({}),
                "minutes_clean": self.minutes_clean.count_documents({}),
            },
            "checked_at": datetime.now(timezone.utc),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db = MongoDatabase()
    logger.info(db.integrity_check())