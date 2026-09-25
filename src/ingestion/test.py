import argparse
import logging

from ..storage.mongo_client import MongoDatabase
from .ingest_minutes import MinutesIngestor
from .ingest_calendar import CalendarIngestor

START_YEAR = 1993
END_YEAR = 2026

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=START_YEAR)
    parser.add_argument("--end-year", type=int, default=END_YEAR)
    parser.add_argument("--verbose", action="store_true", help="log per-page scraping detail")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    db = MongoDatabase()

    CalendarIngestor(db).ingest_years(args.start_year, args.end_year)
    MinutesIngestor(db).ingest_unscraped()

    counts = db.integrity_check()["counts"]
    logger.info("database: %s metadata, %s raw minutes",
                counts["metadata"], counts["minutes_raw"])


if __name__ == "__main__":
    main()
