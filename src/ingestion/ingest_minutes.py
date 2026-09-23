import time
from datetime import datetime

from .scraper_registry import ScraperRegistry

SCRAPER_SLEEP = 5


class MinutesIngestor:
    """Drive the era scrapers over every unscraped metadata record.

    This is the orchestration half of the old DB_Manager.get_minute_docs: it
    owns the Mongo reads and writes, and delegates every URL and every byte of
    HTML parsing to the scraper that covers the meeting's year.
    """

    def __init__(self, db, registry=None, sleep_between=SCRAPER_SLEEP):
        """Initialize the ingestor

        Args:
            db (MongoDatabase): Connected database wrapper exposing metadata and minutes_raw
            registry (ScraperRegistry): Year to scraper dispatch, defaults to the standard registry
            sleep_between (int): Seconds to wait between meetings, to stay polite to the Fed

        Return:
            None
        """
        self.db = db
        self.registry = registry or ScraperRegistry()
        self.sleep_between = sleep_between

    @staticmethod
    def _as_dates(meeting_date):
        """Normalize a metadata meeting_date into a list of YYYYMMDD strings

        Args:
            meeting_date (str or list): Value stored on the metadata record

        Return:
            list: Date strings for the meeting
        """
        return meeting_date if isinstance(meeting_date, list) else [meeting_date]

    def ingest_unscraped(self):
        """Fetch and store raw minutes for every metadata record not yet scraped

        Args:
            None

        Return:
            dict: Counts of stored, skipped and failed meetings
        """
        unscraped_count = self.db.metadata.count_documents({"scraped": False})
        print(f"unscraped count: {unscraped_count}")

        stored = skipped = failed = 0

        for doc in self.db.metadata.find({"scraped": False}):
            dates = self._as_dates(doc["meeting_date"])
            if not dates:
                skipped += 1
                continue

            # Matches the key actually written below, and the unique index on it.
            if self.db.minutes_raw.find_one({"meeting_date": doc["meeting_date"]}):
                skipped += 1
                continue

            year = int(dates[0][:4])
            try:
                scraper = self.registry.for_year(year)
            except ValueError as e:
                print(f"skipping {dates}: {e}")
                skipped += 1
                continue

            # A meeting can span two days; the minutes live under one of them.
            # Take the first date that yields usable text rather than the last.
            parsed = None
            for d in dates:
                candidate = scraper.get_minutes_text(scraper.build_url(d))
                if candidate and candidate.get("raw_text"):
                    parsed = candidate
                    break

            if parsed is None:
                print(f"no minutes text found for {dates}")
                failed += 1
                time.sleep(self.sleep_between)
                continue

            self.db.minutes_raw.insert_one({
                "meeting_date": doc["meeting_date"],
                "year": year,
                "raw_text": parsed["raw_text"],
                "chair": parsed["chair"],
                "scraped_at": datetime.now(),
            })
            self.db.metadata.update_one(
                {"_id": doc["_id"]},
                {"$set": {"scraped": True, "scraped_at": datetime.now()}},
            )

            stored += 1
            unscraped_count -= 1
            print(f"unscraped count: {unscraped_count}")

            time.sleep(self.sleep_between)

        return {"stored": stored, "skipped": skipped, "failed": failed}
