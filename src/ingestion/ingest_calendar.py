import logging
import time
from .scraper_registry import ScraperRegistry

logger = logging.getLogger(__name__)
SCRAPER_SLEEP = 5

class CalendarIngestor:
    """Scrapes the meeting calendar for each year and stores it in fomc_metadata"""

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

    def _get_scraper_for(self, year):
        """Resolve the era scraper covering a calendar year

        Args:
            year (int): Four digit year

        Return:
            ScraperBase or None: Scraper for that era, or None if no era claims it
        """
        try:
            return self.registry.for_year(year)
        except ValueError:
            logger.warning("no scraper registered for year %s", year)
            return None

    def _persist(self, doc):
        """Insert one meeting record into the metadata collection

        Args:
            doc (dict): The metadata record being ingested

        Return:
            None
        """
        self.db.metadata.insert_one(doc)

    def _already_ingested(self, meeting_end):
        """Check if this meeting is already in the metadata collection

        Args:
            meeting_end (str): Date string in YYYYMMDD format

        Return:
            bool: True if the meeting is already stored
        """
        return self.db.metadata.find_one({"meeting_end": meeting_end}) is not None

    def ingest_calendar(self, year):
        """Scrape and store every meeting record for one calendar year

        Args:
            year (int): Four digit year

        Return:
            int: Number of new metadata records stored
        """
        scraper = self._get_scraper_for(year)
        if scraper is None:
            return 0

        records = scraper.get_meeting_dates(year)

        stored = 0
        for record in records:
            if self._already_ingested(record["meeting_end"]):
                continue
            self._persist(record)
            stored += 1

        logger.info("%s: %s new of %s meetings", year, stored, len(records))
        return stored

    def ingest_years(self, start_year, end_year, rebuild=False):
        """Scrape and store meeting records across an inclusive year range

        Args:
            start_year (int): First year to scrape
            end_year (int): Last year to scrape, inclusive
            rebuild (bool): Delete the existing records in the range first
                (use this if the date parsing changes)

        Return:
            int: Total number of new metadata records stored
        """
        if rebuild:
            removed = self.db.metadata.delete_many(
                {"year": {"$gte": start_year, "$lte": end_year}}).deleted_count
            logger.info("rebuild: dropped %s metadata records for %s-%s",
                        removed, start_year, end_year)

        total = 0
        for year in range(start_year, end_year + 1):
            try:
                total += self.ingest_calendar(year)
            except Exception:
                logger.exception("%s failed, continuing", year)
            time.sleep(self.sleep_between)

        logger.info("calendar: %s new records across %s-%s",
                    total, start_year, end_year)
        return total

