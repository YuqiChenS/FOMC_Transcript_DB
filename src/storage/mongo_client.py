import os
import logging
from datetime import datetime, timezone

import pymongo
from pymongo.errors import ConnectionFailure, ConfigurationError
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Reads the repo-root .env if present; real environment variables win.
load_dotenv()


class MongoDatabase:
    """Single point of connection + schema setup for the fomc database."""

    def __init__(self):
        uri = os.environ.get("MONGO_URI")
        if not uri:
            raise ConfigurationError("MONGO_URI environment variable is not set")

        self.client = pymongo.MongoClient(
            uri,
            serverSelectionTimeoutMS=5000,   
            maxPoolSize=20,
            retryWrites=True,
        )

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

        self._apply_schema_validation()
        self._ensure_indexes()

    def _apply_schema_validation(self):
        """Enforce document shape at the DB layer, not just in application code."""
        try:
            self.db.create_collection(
                "fomc_minutes_raw",
                validator={
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
                },
                validationLevel="moderate",
            )
        except pymongo.errors.CollectionInvalid:
            pass

    def _ensure_indexes(self):
        """Indexes tied to actual query patterns, not speculative ones."""
        self.metadata.create_index([("meeting_end", pymongo.ASCENDING)], unique=True)
        self.metadata.create_index([("year", pymongo.ASCENDING)])

        self.minutes_raw.create_index([("meeting_end", pymongo.ASCENDING)], unique=True)
        self.minutes_raw.create_index([("raw_text", pymongo.TEXT)])
        self.minutes_raw.create_index([("year", pymongo.ASCENDING)])

        self.minutes_clean.create_index([("meeting_end", pymongo.ASCENDING)], unique=True)
        self.minutes_clean.create_index([("dominant_topic", pymongo.ASCENDING)])

    def integrity_check(self) -> dict:

        return {
            "connected": True,
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