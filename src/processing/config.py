import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

SPACY_MODEL = "en_core_web_sm"

CHUNK_SIZE = 900_000

KEEP_POS = ("NOUN")

MIN_TOKEN_LENGTH = 3

FOMC_STOPWORDS = {
    "website", "official", "chairman", "authorize", "paragraph", "subcommittee",
    "dealer", "direct", "authorization", "position", "first", "second", "target",
    "third", "fourth", "adjourn", "division", "staff", "note", "participant",
    "press", "locklocke", "govwebsite", "board", "research", "fomc", "comment",
    "governor", "assistant", "attend", "meeting", "bank", "january", "february",
    "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "though", "system", "united", "states", "amid", "range",
    "quarter", "survey", "desk", "assess", "york", "special", "adviser", "reserve",
    "seem", "indication", "select", "exchange", "purpose", "day", "committee", "goal",
    "price", "run", "regard", "directive", "objective", "equipment", "facility", "reading", 
    "projection", "vice", "secretariat", "member" }


@lru_cache(maxsize=1)
def get_nlp():
    """Load the spaCy pipeline used for lemmatization and POS tagging

    Args:
        None

    Return:
        spacy.Language: Pipeline with NER and parsing disabled
    """
    import spacy

    logger.debug("loading spaCy model %s", SPACY_MODEL)
    try:
        return spacy.load(SPACY_MODEL, disable=["ner", "parser"])
    except OSError:
        raise RuntimeError(
            f"spaCy model '{SPACY_MODEL}' is not installed. Install it with:\n"
            f"    python -m spacy download {SPACY_MODEL}"
        )


@lru_cache(maxsize=1)
def get_stopwords():
    """Build the stopword set: NLTK English plus FOMC boilerplate

    Args:
        None

    Return:
        frozenset: Lowercase stopwords
    """
    from nltk.corpus import stopwords

    try:
        english = set(stopwords.words("english"))
    except LookupError:
        raise RuntimeError(
            "NLTK 'stopwords' corpus is missing. Install it with:\n"
            "    python -m nltk.downloader stopwords"
        )

    logger.debug("loaded %s NLTK stopwords", len(english))
    return frozenset(english | FOMC_STOPWORDS)
