import logging
from datetime import datetime
from pathlib import Path
from gensim.corpora import Dictionary
from gensim.models import LdaModel, CoherenceModel
from pymongo import UpdateOne
from ..visualization.visualization import visualize_lda

logger = logging.getLogger(__name__)

# topic numbers only mean something for the model they came from,
# so labels are kept per model file
TOPIC_LABELS = {
    "lda_2026-10-01_1045.model": {
        0: "Balance_Sheet",
        1: "Currency_Operation",
        2: "Over-expansion",
        3: "Economic Slowdown",
    },
}

RANDOM_STATE = 42
# project root / models, so it's the same folder no matter where you run from
MODEL_DIR = Path(__file__).resolve().parents[2] / "models"

class LDAModel:
    def __init__(self, db, *, num_topics=4, passes=20,
                 no_below=5, no_above=0.8, model_dir=MODEL_DIR, retrain=False):
        """Initialize the LDA model settings

        Args:
            db (MongoDatabase): Connected database wrapper
            num_topics (int): Number of topics
            passes (int): Training passes over the corpus
            no_below (int): Drop words in fewer than this many documents
            no_above (float): Drop words in more than this fraction of documents
            model_dir (Path): Where the model and dictionary get saved
            retrain (bool): Train a new model even if a saved one exists

        Return:
            None
        """
        self.db = db
        self.num_topics = num_topics
        self.passes = passes
        self.no_below = no_below
        self.no_above = no_above
        self.model_dir = Path(model_dir)
        self.retrain = retrain

    def latest_model_path(self):
        """Find the newest saved model, e.g. models/lda_2026-09-30_2055.model

        The date format sorts in time order, so the last one is the newest.

        Return:
            Path or None: Newest .model file, or None if nothing is saved yet
        """
        saved = sorted(self.model_dir.glob("lda_*.model"))
        return saved[-1] if saved else None

    def load_model(self, model_path=None):
        """Load a saved model and its dictionary (the newest one by default)

        Args:
            model_path (Path): A specific .model file to load

        Return:
            tuple or None: (LdaModel, Dictionary), or None if nothing is saved
        """
        model_path = model_path or self.latest_model_path()
        if model_path is None:
            return None
        dict_path = model_path.with_suffix(".dict")
        return LdaModel.load(str(model_path)), Dictionary.load(str(dict_path))

    def fit_lda(self):
        """Train LDA on the bigram tokens, score coherence and save the results

        Also saves a pyLDAvis HTML file next to the model. Mapping topics
        onto each meeting is a separate step, see assign_topics.

        Return:
            list: Topic results (id, coherence, top words), empty if no tokens
        """
        if not self.retrain:
            saved = self.latest_model_path()
            if saved is not None:
                logger.info("found saved model %s", saved.name)
                run = self.db.lda_metadata.find_one({"model_file": saved.name})
                return run["results"] if run else []

        docs = list(self.db.minutes_clean.find(
            {"meeting_end": {"$exists": True}, "tokens": {"$exists": True}}
        ))
        if not docs:
            logger.warning("no cleaned tokens exist")
            return []

        all_tokens = [doc["tokens"] for doc in docs]

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

        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        model_path = self.model_dir / f"lda_{stamp}.model"
        self.model_dir.mkdir(parents=True, exist_ok=True)
        lda_model.save(str(model_path))
        dictionary.save(str(model_path.with_suffix(".dict")))
        logger.info("saved %s and its dictionary", model_path.name)

        for idx, topic in lda_model.print_topics(num_words=10):
            logger.info("topic %s: %s", idx, topic)

        # the visualization is nice to have, so don't lose the run if it fails
        vis_path = model_path.with_name(f"lda_{stamp}_vis.html")
        try:
            visualize_lda(lda_model, corpus, dictionary, vis_path)
        except Exception:
            logger.exception("pyLDAvis failed, continuing without it")
            vis_path = None

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
            "model_file": model_path.name,
            "vis_file": vis_path.name if vis_path else None,
            "bigrams_id": latest["_id"] if latest else None,
            "no_below": int(self.no_below),
            "no_above": float(self.no_above),
            "topic_number": int(self.num_topics),
            "passes": int(self.passes),
            "results": results,
            "average_coherence": round(sum(topic_scores) / len(topic_scores), 4),
            "built_at": datetime.now(),
        })
        logger.info("average coherence: %.4f", sum(topic_scores) / len(topic_scores))
        return results

    def assign_topics(self, model_path=None):
        """Map a saved model's topics onto every meeting, without training

        Uses the model's own saved dictionary, since the word ids have to
        match the ones the model was trained with.

        Args:
            model_path (Path): A specific .model file, defaults to the newest

        Return:
            int: Number of meetings updated
        """
        loaded = self.load_model(model_path)
        if loaded is None:
            logger.warning("no saved model in %s, train one first", self.model_dir)
            return 0
        lda_model, dictionary = loaded
        model_file = Path(model_path).name if model_path else self.latest_model_path().name

        docs = list(self.db.minutes_clean.find(
            {"meeting_end": {"$exists": True}, "tokens": {"$exists": True}}
        ))
        if not docs:
            logger.warning("no cleaned tokens exist")
            return 0

        # docs and corpus are built together so they stay in the same order
        corpus = [dictionary.doc2bow(doc["tokens"]) for doc in docs]
        logger.info("assigning topics from %s to %s meetings", model_file, len(docs))
        return self.store_doc_topics(lda_model, docs, corpus, model_file)

    def store_doc_topics(self, lda_model, docs, corpus, model_file):
        """Save each meeting's topic distribution and dominant topic

        Args:
            lda_model (LdaModel): Trained model
            docs (list): minutes_clean documents
            corpus (list): Bag-of-words vectors, same order as docs
            model_file (str): Model filename, so we know which run the topics came from

        Return:
            int: Number of meetings updated
        """
        labels = TOPIC_LABELS.get(model_file, {})
        if not labels:
            logger.warning("no labels for %s, storing topic numbers only", model_file)

        operations = []
        for doc, bow in zip(docs, corpus):
            topic_dist = lda_model.get_document_topics(bow, minimum_probability=0.0)
            dominant_topic, dominant_weight = max(topic_dist, key=lambda x: x[1])

            operations.append(UpdateOne(
                {"_id": doc["_id"]},
                {"$set": {
                    "topic_distribution": [
                        {"topic_id": int(t), "weight": round(float(w), 4)}
                        for t, w in topic_dist
                    ],
                    "dominant_topic": int(dominant_topic),
                    "dominant_topic_label": labels.get(int(dominant_topic)),
                    "dominant_topic_weight": round(float(dominant_weight), 4),
                    "model_file": model_file,
                }},
            ))

        result = self.db.minutes_clean.bulk_write(operations, ordered=False)
        logger.info("stored topic distributions for %s meetings", result.modified_count)
        return result.modified_count

