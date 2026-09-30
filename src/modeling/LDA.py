import logging
from datetime import datetime
from pathlib import Path
from gensim.corpora import Dictionary
from gensim.models import LdaModel, CoherenceModel

logger = logging.getLogger(__name__)


RANDOM_STATE = 42
MODEL_DIR = Path("models")

class LDAModel():
    def __init__(self, db, *, num_topics=10, passes=20,
                 no_below=5, no_above=0.8, model_dir=MODEL_DIR):
        """Initialize the tokenizer

        Args:
            db (MongoDatabase): Connected database wrapper
            model_dir (Path): Directory the fitted model and dictionary are
                written to, so a run can be reloaded instead of refitted

        Return:
            None
        """
        self.db = db
        self.num_topics = num_topics
        self.passes = passes
        self.no_below = no_below
        self.no_above = no_above
        self.model_dir = Path(model_dir)

    def fit_lda(self):
        """Train an LDA topic model on bigram-enhanced documents

        """
        docs = list(self.db.minutes_clean.find(
            {"meeting_end": {"$exists": True}, "tokens": {"$exists": True}}
        ))
        if not docs:
            logger.warning("no cleaned tokens exist")
            return {"updated": 0, "phrases": 0}

        all_tokens = [doc["tokens"]for doc in docs]

        dictionary = Dictionary(all_tokens)
        before = len(dictionary)
        dictionary.filter_extremes(no_below=self.no_below, no_above=self.no_above)
        logger.info("dictionary: %s -> %s unique tokens (no_below=%s, no_above=%s)",
                    before, len(dictionary), self.no_below, self.no_above)

        corpus = [dictionary.doc2bow(tokens) for tokens in all_tokens]

        lda_model = LdaModel(
            corpus=corpus,
            id2word=dictionary,
            num_topics=self.num_topics,
            passes=self.passes,
            chunksize=10,
            random_state=RANDOM_STATE,
        )

        # Save before scoring: coherence is the slow part, and a crash there
        # should not cost the fit.
        self.model_dir.mkdir(parents=True, exist_ok=True)
        lda_model.save(str(self.model_dir / "lda.model"))
        dictionary.save(str(self.model_dir / "lda.dict"))
        logger.info("saved model and dictionary to %s/", self.model_dir)

        for idx, topic in lda_model.print_topics(num_words=10):
            logger.info("topic %s: %s", idx, topic)

        coherence = CoherenceModel(
            model=lda_model,
            texts=all_tokens,
            dictionary=dictionary,
            coherence="c_v",
        )

        topic_scores = coherence.get_coherence_per_topic()
        topics = lda_model.show_topics(
            num_topics=-1,
            num_words=10,
            formatted=False,
        )

        results = [
            {
                "topic_id": int(topic_id),
                "coherence": float(score),
                "terms": [
                    {
                        "word": str(word),
                        "weight": float(weight),
                    }
                    for word, weight in terms
                ],
            }
            for (topic_id, terms), score in zip(topics, topic_scores)
        ]

        latest = self.db.bigrams.find_one(sort=[("_id", -1)])

        self.db.lda_metadata.insert_one({
            "bigrams_id": latest["_id"] if latest else None,
            "no_below": int(self.no_below),
            "no_above": float(self.no_above),
            "topic_number": int(self.num_topics),
            "passes": int(self.passes),
            "results": results,
            "built_at": datetime.now(),
        })

