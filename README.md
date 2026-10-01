# FOMC Minutes Topic Modeling

Scrapes every FOMC meeting's minutes from federalreserve.gov (1993 to now), stores them in MongoDB, and uses LDA topic modeling to see what the Fed talked about over time. Results are shown in a Streamlit dashboard.

## How it works

1. **Calendar** - scrape meeting dates and minutes links. The Fed's site has used a few different layouts over the years, so there's a scraper per era (1993-1995, 1996-2007, 2008-present).
2. **Minutes** - download the text of each meeting's minutes.
3. **Tokens** - lowercase, lemmatize with spaCy, keep nouns, drop stopwords (NLTK plus FOMC boilerplate like "committee" and month names), then join common word pairs into bigrams with gensim (`balance_sheet`, `swap_arrangement`).
4. **LDA** - train a gensim LDA model, score it with c_v coherence, and save each meeting's topic mix back to Mongo. The model and a pyLDAvis map are saved in `models/` with the date in the filename, so a new run doesn't overwrite an old one.

## Topics

4 topics, `no_above=0.8`, `no_below=5`, 20 passes. I compared a few settings and picked this one because the topics were easier to tell apart and name, even though its coherence wasn't the highest.

| Topic | Top words | What it's about |
|---|---|---|
| Balance Sheet | loan, stability, stance_policy, balance_sheet, asset, spread | The Fed's asset holdings, credit markets and financial stability, mostly after 2008 |
| Currency Operation | currency_operation, government_security, swap_arrangement, swap_drawing | Reports and votes on the Fed's trading in Treasuries and foreign currencies |
| Over-expansion | productivity, strength, stock_market, tightening, surge, moderation | A strong economy and the Fed raising rates to cool it down |
| Economic Slowdown | inventory, aggregate, weakness, pickup, easing, part_country | A weak economy, rate cuts and waiting for a recovery |

Each meeting is a mix of all four, so "main topic" just means the biggest share.

## Data (MongoDB `fomc` database)

- `fomc_metadata` - one record per meeting: date, minutes URL, scraped or not
- `fomc_minutes_raw` - minutes text and chair
- `fomc_minutes_clean` - tokens, topic mix and main topic per meeting
- `fomc_minutes_bigrams` - learned bigrams and their scores
- `fomc_lda_metadata` - one record per trained model: settings, top words, coherence

## Running it

```
python -m venv FOMC_venv && source FOMC_venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
python -m nltk.downloader stopwords
echo "MONGO_URI=mongodb://127.0.0.1:27017" > .env

python -m src.pipeline.driver --stages calendar minutes tokens lda
streamlit run app.py
```

If a model is already saved, the `lda` stage skips training. Use `--retrain` to train a new one. Topic labels live in `TOPIC_LABELS` in `src/modeling/LDA.py`, keyed by model filename.

## Dashboard

Pick a year to see the topic share across all years, that year's meetings with their main topic, and a link to each meeting's minutes. Clicking a meeting shows its topic mix and opens the pyLDAvis map on its main topic.

## Code

```
app.py                      Streamlit dashboard
src/pipeline/driver.py      runs the stages (CLI)
src/ingestion/              scrapers and ingestion into Mongo
src/processing/             tokenizing, stopwords, bigrams
src/modeling/LDA.py         training, topic labels, per-meeting topics
src/visualization/          pyLDAvis export
src/storage/mongo_client.py Mongo connection, indexes, schema validation
```

Built with Python, MongoDB, requests/BeautifulSoup, spaCy, NLTK, gensim, pyLDAvis and Streamlit.
