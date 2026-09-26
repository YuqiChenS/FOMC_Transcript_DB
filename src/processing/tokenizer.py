import re

from .config import CHUNK_SIZE, KEEP_POS, MIN_TOKEN_LENGTH, get_nlp, get_stopwords

_NON_ALPHA = re.compile(r"[^a-z\s]")
_WHITESPACE = re.compile(r"\s+")


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

    Args:
        text (str): Raw text to tokenize

    Return:
        list: Lemmatized nouns, adjectives and verbs, excluding stopwords
            and tokens shorter than MIN_TOKEN_LENGTH characters
    """
    text = normalize(text)
    if not text:
        return []

    nlp = get_nlp()
    stopwords = get_stopwords()

    tokens = []
    for start in range(0, len(text), CHUNK_SIZE):
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

    return tokens

def tokenize_text_new(text):
    return text.split()

