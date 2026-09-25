import logging
import time
from datetime import datetime

from .scraper_registry import ScraperRegistry

logger = logging.getLogger(__name__)

SCRAPER_SLEEP = 5

class MinutesIngestor:
    """Drive the era scrapers over every unscraped metadata record.

    """

    def __init__(self, db, registry=None, sleep_between=SCRAPER_SLEEP):
        """Initialize the ingestor

        Args:
            db (MongoDatabase): Connected database wrapper
            registry (ScraperRegistry): Year to scraper dispatch, defaults to the standard registry
            sleep_between (int): Seconds to wait between meetings

        Return:
            None
        """
        self.db = db
        self.registry = registry or ScraperRegistry()
        self.sleep_between = sleep_between

    def ingest_unscraped(self):
        stored = skipped = failed = 0
        for doc in self.db.metadata.find({"scraped": False}):
            result = self._process_one(doc)
            if result == "stored":
                stored += 1
            elif result == "skipped":
                skipped += 1
            else:
                failed += 1
        logger.info("minutes: %s stored, %s skipped, %s failed", stored, skipped, failed)
        return {"stored": stored, "skipped": skipped, "failed": failed}

    def _process_one(self, doc):
        meeting_end = doc["meeting_end"]
        if not meeting_end or self._already_ingested(meeting_end):
            return "skipped"

        scraper = self._get_scraper_for(meeting_end)
        if scraper is None:
            return "skipped"

        parsed = self._fetch_minutes(scraper, meeting_end)
        if parsed is None:
            return "failed"

        self._persist(doc, parsed)
        time.sleep(self.sleep_between)
        return "stored"

    def _already_ingested(self, meeting_end):
        """Report whether raw minutes for this meeting are already stored

        Queries on the same key _persist writes, so the check actually matches
        and the unique index on minutes_raw.meeting_end is never tripped.

        Args:
            meeting_end (str): Date string in YYYYMMDD format

        Return:
            bool: True if a raw document already exists for this meeting
        """
        return self.db.minutes_raw.find_one({"meeting_end": meeting_end}) is not None

    def _get_scraper_for(self, meeting_end):
        """Resolve the era scraper covering the meeting's year

        Args:
            meeting_end (str): Date string in YYYYMMDD format

        Return:
            ScraperBase or None: Scraper for that era, or None if no era claims it
        """
        year = int(meeting_end[:4])
        try:
            return self.registry.for_year(year)
        except ValueError:
            logger.warning("no scraper registered for year %s (%s)", year, meeting_end)
            return None

    def _fetch_minutes(self, scraper, meeting_end):
        """Fetch and parse the minutes page for a meeting

        Args:
            scraper (ScraperBase): Scraper covering this meeting's era
            meeting_end (str): Date string in YYYYMMDD format

        Return:
            dict or None: {"raw_text", "chair"}, or None if the page yielded no text
        """
        parsed = scraper.get_minutes_text(scraper.build_url(meeting_end))
        if parsed and parsed.get("raw_text"):
            return parsed

        logger.warning("no minutes text found for %s", meeting_end)
        return None

    def _persist(self, doc, parsed):
        """Store the raw minutes and mark the metadata record scraped

        Args:
            doc (dict): The metadata record being ingested
            parsed (dict): {"raw_text", "chair"} returned by the scraper

        Return:
            None
        """
        self.db.minutes_raw.insert_one({
            "meeting_end": doc["meeting_end"],
            "year": int(doc["meeting_end"][:4]),
            "raw_text": parsed["raw_text"],
            "chair": parsed["chair"],
            "scraped_at": datetime.now(),
        })
        self.db.metadata.update_one(
            {"_id": doc["_id"]},
            {"$set": {"scraped": True, "scraped_at": datetime.now()}},
        )
