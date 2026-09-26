import logging
from datetime import datetime
from gensim.corpora import Dictionary
from gensim.models import LdaModel, CoherenceModel

logger = logging.getLogger(__name__)


RANDOM_STATE = 42

class LDAModel():
    def __init__(self, db, *, min_count, threshold, num_topics=4, passes=1):
        """Initialize the tokenizer

        Args:
            db (MongoDatabase): Connected database wrapper

        Return:
            None
        """
        self.db = db
        self.min_count = min_count
        self.num_topics = num_topics
        self.passes = passes
        self.threshold = threshold       

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
        logger.info("dictionary: %s unique tokens", len(dictionary))

        corpus = [dictionary.doc2bow(tokens) for tokens in all_tokens]

        lda_model = LdaModel(
            corpus=corpus,
            id2word=dictionary,
            num_topics=self.num_topics,
            passes=self.passes,
            chunksize=10,
            random_state=RANDOM_STATE,
        )

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

        self.db.lda_metadata.insert_one({
            "bigram_min_word_count": int(self.min_count),
            "bigram_threshold": float(self.threshold),
            "topic_number": int(self.num_topics),
            "passes": int(self.passes),
            "results": results,
            "built_at": datetime.now(),
        })

