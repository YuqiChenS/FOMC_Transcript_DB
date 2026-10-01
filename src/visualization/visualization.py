import logging
import pyLDAvis
import pyLDAvis.gensim_models as gensimvis

logger = logging.getLogger(__name__)


def visualize_lda(lda_model, corpus, dictionary, html_path):
    """Generate an interactive pyLDAvis visualization and save it as an HTML file

    Args:
        lda_model: Trained LDA model
        corpus (list): List of bag-of-words vectors for the documents
        dictionary (Dictionary): Gensim dictionary used to build the corpus
        html_path (Path): Where to save the HTML file

    Return:
        Path: The saved HTML file
    """
    # sort_topics=False keeps pyLDAvis topic numbers lined up with gensim's
    # (pyLDAvis numbers from 1, so its topic 1 is our topic 0)
    vis_data = gensimvis.prepare(
        lda_model,
        corpus,
        dictionary,
        sort_topics=False,
    )

    pyLDAvis.save_html(vis_data, str(html_path))
    logger.info("saved %s", html_path.name)
    return html_path
