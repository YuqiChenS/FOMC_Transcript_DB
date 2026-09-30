import argparse
import logging
import argparse
from ..storage.mongo_client import MongoDatabase
from ..ingestion.ingest_minutes import MinutesIngestor
from ..ingestion.ingest_calendar import CalendarIngestor
from ..processing.tokenize_corpus import CorpusTokenizer
from ..modeling.LDA import LDAModel

START_YEAR = 1993
END_YEAR = 2026

logger = logging.getLogger(__name__)
STAGES = ("calendar", "minutes", "tokens", "lda")

def main():
    parser = argparse.ArgumentParser()
    # calendar
    parser.add_argument("--stages", nargs="+", choices=STAGES,
                        default=["minutes", "tokens", "lda"])
    parser.add_argument("--start-year", type=int, default=START_YEAR)
    parser.add_argument("--end-year", type=int, default=END_YEAR)
    parser.add_argument("--rebuild", action="store_true")
    # phrasing
    parser.add_argument("--min-count", type=int, default=100)
    parser.add_argument("--threshold", type=float, default=0.4)
    # dictionary
    parser.add_argument("--no-below", type=int, default=5)
    parser.add_argument("--no-above", type=float, default=0.8)
    # lda
    parser.add_argument("--num-topics", type=int, default=4)
    parser.add_argument("--passes", type=int, default=20)

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    db = MongoDatabase()
    if "calendar" in args.stages:
        CalendarIngestor(db).ingest_years(args.start_year, args.end_year,
                                        rebuild=args.rebuild)
    if "minutes" in args.stages:
        MinutesIngestor(db).ingest_unscraped()
        counts = db.integrity_check()["counts"]
        logger.info("database: %s metadata, %s raw minutes",
                    counts["metadata"], counts["minutes_raw"])
    if "tokens" in args.stages:
        CorpusTokenizer(db, min_count=args.min_count,
                        threshold=args.threshold).bigram_filtering()
    if "lda" in args.stages:
        LDAModel(db, num_topics=args.num_topics, passes=args.passes,
                no_below=args.no_below, no_above=args.no_above).fit_lda()

if __name__ == "__main__":
    main()
