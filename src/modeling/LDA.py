def fit_lda(bigram_docs, num_topics=4):
    """Train an LDA topic model on bigram-enhanced documents and print coherence

    Args:
        bigram_docs (list): List of tokenized documents with bigrams applied
        num_topics (int): Number of topics for the LDA model

    Return:
        tuple: (LdaModel, Dictionary, corpus)
    """
    dictionary = Dictionary(bigram_docs)
    dictionary.filter_extremes(no_below=5, no_above=0.7)
    print(f"Dictionary size: {len(dictionary)} unique tokens")

    corpus = [dictionary.doc2bow(doc) for doc in bigram_docs]

    lda_model = LdaModel(
        corpus=corpus,
        id2word=dictionary,
        num_topics=num_topics,
        passes=50,
        chunksize=10,
        random_state=42
    )

    # Print topics
    for idx, topic in lda_model.print_topics(num_words=10):
        print(f"\nTopic {idx}: {topic}")

    coherence = CoherenceModel(
        model=lda_model,
        texts=bigram_docs,
        dictionary=dictionary,
        coherence='c_v'
    )
    print(f"\n{num_topics} topics, Coherence Score: {coherence.get_coherence():.4f}")

    return lda_model, dictionary, corpus