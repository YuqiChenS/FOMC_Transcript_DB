import logging
from datetime import datetime
from pathlib import Path
from gensim.models import Phrases
from gensim.models.phrases import Phraser
from pymongo import UpdateOne
from .tokenizer import tokenize_text

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parents[2] / "models"


class CorpusTokenizer:
    """Tokenizes the raw minutes, learns bigrams and saves to fomc_minutes_clean"""

    def __init__(self, db, *, min_count=100, threshold=0.4, model_dir=MODEL_DIR):
        """Initialize the tokenizer.

        Args:
            db (MongoDatabase): Connected database wrapper
            min_count (int): Minimum times a bigram has to show up
            threshold (float): Minimum NPMI score for a bigram (-1 to 1)
            model_dir (Path): Where the phraser gets saved
        """
        self.db = db
        self.min_count = min_count
        self.threshold = threshold
        self.model_dir = Path(model_dir)

    def bigram_filtering(self):
        """Learn bigrams across the whole corpus and write them back per meeting

        Return:
            dict: Counts of meetings updated and phrases learned
        """
        docs = list(self.db.minutes_raw.find(
            {"meeting_end": {"$exists": True}, "raw_text": {"$exists": True}}
        ))
        if not docs:
            logger.warning("no raw documents with text, nothing to phrase")
            return {"updated": 0, "phrases": 0}

        all_tokens = [tokenize_text(doc["raw_text"]) for doc in docs]

        bigram_model = Phrases(all_tokens, min_count=self.min_count,
                               threshold=self.threshold, scoring="npmi")
        bigram = Phraser(bigram_model)
        bigram_docs = [bigram[tokens] for tokens in all_tokens]

        self.model_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        phraser_file = f"bigram_{stamp}.phraser"
        bigram.save(str(self.model_dir / phraser_file))
        logger.info("saved %s", phraser_file)

        operations = [
            UpdateOne(
                {"meeting_end": doc["meeting_end"]},
                {"$set": {
                    "year": doc.get("year"),
                    "tokens": tokens,
                    "token_count": len(tokens),
                    "tokenized_at": datetime.now(),
                }},
                upsert=True,
            )
            for doc, tokens in zip(docs, bigram_docs)
        ]
        result = self.db.minutes_clean.bulk_write(operations, ordered=False)
        updated = result.modified_count + result.upserted_count

        phrases = {phrase: float(score) for phrase, score in bigram.phrasegrams.items()}
        self.db.bigrams.replace_one(
            {},
            {
                "bigrams": phrases,
                "phrase_count": len(phrases),
                "phraser_file": phraser_file,
                "min_count": self.min_count,
                "threshold": self.threshold,
                "document_count": len(docs),
                "built_at": datetime.now(),
            },
            upsert=True,
        )

        logger.info("bigrams: %s phrases learned, %s meetings updated",
                    len(phrases), updated)
        return {"updated": updated, "phrases": len(phrases)}