import re
import logging
from .config import CHUNK_SIZE, KEEP_POS, MIN_TOKEN_LENGTH, get_nlp, get_stopwords

_NON_ALPHA = re.compile(r"[^a-z\s]")
_WHITESPACE = re.compile(r"\s+")

logger = logging.getLogger(__name__)

def normalize(text):
    """Lowercase text and strip everything that is not a letter or space

    Args:
        text (str): Raw minutes text

    Return:
        str: Normalized text with collapsed whitespace
    """
    text = text.lower()
    text = _NON_ALPHA.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()

def tokenize_text(text):
    """Lemmatize and filter tokens from a text string using spaCy

    Filtering happens here, before phrasing, so the phrase model only ever
    sees content words.

    Args:
        text (str): Raw text to tokenize

    Return:
        list: Lemmatized nouns and verbs, excluding stopwords and tokens
            shorter than MIN_TOKEN_LENGTH characters
    """
    text = normalize(text)
    if not text:
        return []

    nlp = get_nlp()
    stopwords = get_stopwords()

    tokens = []
    chunks = range(0, len(text), CHUNK_SIZE)
    for n, start in enumerate(chunks, start=1):
        chunk = text[start:start + CHUNK_SIZE]
        for token in nlp(chunk):
            lemma = token.lemma_
            if token.pos_ not in KEEP_POS:
                continue
            if lemma in stopwords:
                continue
            if len(lemma) < MIN_TOKEN_LENGTH:
                continue
            if token.is_space:
                continue
            tokens.append(lemma)
        logger.info("%s chunks tokenized", n)

    return tokens

