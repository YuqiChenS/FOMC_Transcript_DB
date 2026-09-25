import logging
import time
from datetime import datetime

from .scraper_registry import ScraperRegistry

logger = logging.getLogger(__name__)
SCRAPER_SLEEP = 5

class CalendarIngestor:
    '''Drive the calendar scrapers
    '''

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

    def _get_scraper_for(self, dates):
        """Resolve the era scraper covering the meeting's year

        Args:
            dates (list): Date strings in YYYYMMDD format

        Return:
            ScraperBase or None: Scraper for that era, or None if no era claims it
        """
        year = int(dates[0][:4])
        try:
            return self.registry.for_year(year)
        except ValueError:
            logger.warning("no scraper registered for year %s (%s)", year, dates)
            return None

    def _process_one(self, doc):
        dates = self._as_dates(doc["meeting_end"])
        if not dates or self._already_ingested(doc["meeting_end"]):
            return "skipped"

        scraper = self._get_scraper_for(dates)
        if scraper is None:
            return "skipped"

        parsed = self._fetch_first_available(scraper, dates)
        if parsed is None:
            return "failed"

        self._persist(doc, parsed)
        time.sleep(self.sleep_between)
        return "stored"
    
    def _persist(self, doc):
        """Store the raw minutes and mark the metadata record scraped

        Args:
            doc (dict): The metadata record being ingested
    
        Return:
            None
        """

        self.db.metadata.insert_one(doc)