import logging
from datetime import datetime
from gensim.models import Phrases
from gensim.models.phrases import Phraser
from gensim.utils import simple_preprocess
from pymongo import UpdateOne
from .config import get_nlp, get_stopwords
from .tokenizer import tokenize_text

logger = logging.getLogger(__name__)


class CorpusTokenizer:
    """Build the clean token collection from the raw minutes collection.

    """

    def __init__(self, db, *, min_count=100, threshold=0.4):
        """Initialize the tokenizer.

        Args:
            db: Connected MongoDB database wrapper.
            min_count: Minimum phrase occurrence count.
            threshold: Minimum NPMI score required for a phrase.
        """
        self.db = db
        self.min_count = min_count
        self.threshold = threshold

    def _already_tokenized(self, meeting_end):
        """Report whether a clean document already exists for this meeting

        Args:
            meeting_end (str): Date string in YYYYMMDD format

        Return:
            bool: True if the meeting has already been tokenized
        """
        return self.db.minutes_clean.find_one({"meeting_end": meeting_end}) is not None

    def _persist(self, doc, tokens):
        """Store the token list for one meeting

        Args:
            doc (dict): Source document from minutes_raw
            tokens (list): Lemmatized tokens

        Return:
            None
        """
        self.db.minutes_clean.insert_one({
            "meeting_end": doc["meeting_end"],
            "year": doc.get("year"),
            "chair": doc.get("chair"),
            "tokens": tokens,
            "token_count": len(tokens),
            "tokenized_at": datetime.now(),
        })

    def tokenize_corpus(self, rebuild=False):
        """Tokenize every raw minutes document into the clean collection

        Args:
            rebuild (bool): Drop existing clean documents and regenerate them all

        Return:
            dict: Counts of tokenized, skipped and failed documents
        """
        # Load the NLP resources before the loop. They are an environment
        # concern, not a per-document one: if they are missing, every document
        # fails identically, so surface it once here instead of 269 times
        # through the per-document handler below.
        get_nlp()
        get_stopwords()

        if rebuild:
            removed = self.db.minutes_clean.delete_many({}).deleted_count
            logger.info("rebuild: dropped %s existing clean documents", removed)

        raw_count = self.db.minutes_raw.count_documents({"raw_text": {"$exists": True}})
        logger.info("tokenizing %s raw documents", raw_count)

        tokenized = skipped = failed = 0

        for doc in self.db.minutes_raw.find({"raw_text": {"$exists": True}}):
            meeting_end = doc.get("meeting_end")
            if not meeting_end:
                logger.warning("raw document %s has no meeting_end, skipping", doc.get("_id"))
                skipped += 1
                continue

            if self._already_tokenized(meeting_end):
                skipped += 1
                continue

            try:
                tokens = tokenize_text(doc["raw_text"])
            except Exception:
                logger.exception("%s failed to tokenize, continuing", meeting_end)
                failed += 1
                continue

            if not tokens:
                logger.warning("%s produced no tokens", meeting_end)
                failed += 1
                continue

            self._persist(doc, tokens)
            tokenized += 1
            logger.debug("%s: %s tokens", meeting_end, len(tokens))

        logger.info("tokenize: %s tokenized, %s skipped, %s failed",
                    tokenized, skipped, failed)
        return {"tokenized": tokenized, "skipped": skipped, "failed": failed}

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

        all_tokens = [simple_preprocess(doc["raw_text"], deacc=True, min_len=2) for doc in docs]

        bigram_model = Phrases(all_tokens, min_count=self.min_count, threshold=self.threshold, scoring="npmi")
        bigram = Phraser(bigram_model)
        bigram_docs = [bigram[tokens] for tokens in all_tokens]

        # store cleaned minutes: zip is what puts each minute back in its own
        # place. Upsert on meeting_end rather than insert_many because
        # minutes_clean has a unique index on it and tokenize_corpus may have
        # already written the unphrased tokens.
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
        self.db.bigrams.insert_one({
            "bigrams": phrases,
            "phrase_count": len(phrases),
            "min_count": self.min_count,
            "threshold": self.threshold,
            "document_count": len(docs),
            "built_at": datetime.now(),
        })

        logger.info("bigrams: %s phrases learned, %s meetings updated",
                    len(phrases), updated)
        return {"updated": updated, "phrases": len(phrases)}