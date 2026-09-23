import time
from datetime import datetime
import re
# NLP
import nltk
import spacy
from gensim.models import Phrases
from gensim.models.phrases import Phraser
from gensim.corpora import Dictionary
from gensim.models import LdaModel, CoherenceModel
import pyLDAvis
import pyLDAvis.gensim_models as gensimvis
# Web Scraping
import requests
from bs4 import BeautifulSoup
import pymongo

BASE_HISTORIC_URL = "https://www.federalreserve.gov/fomc/MINUTES/{year}/{date}min.htm"
BASE_URL = "https://www.federalreserve.gov/monetarypolicy/fomcminutes{date}.htm"
scraper_sleep = 5
DATES_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
DATES_HISTORIC_URL = "https://federalreserve.gov/monetarypolicy/fomc_historical_year.htm"

MONTH_TO_NUM = {"january": "01", "feburary": "02", "march": "03", "april": "04",\
                "may": "05", "june": "06", "july": "07", "august": "08",\
                "september": "09", "october": "10", "november": "11", "december": "12"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (academic research scraper)"
    )
}

FOMC_STOPWORDS = {
    "website", "official", "chairman", "authorize", "paragraph", "subcommittee", 
    "dealer", "direct", "authorization", "position", "third", "fourth", "adjourn",
    "website", "press", "locklocke", "committee", "govwebsite"
}

nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])
STOPWORDS = set(nltk.data.find('corpora/stopwords'))
STOPWORDS = STOPWORDS | FOMC_STOPWORDS

topic_num_TO_words = {3: "Quantitative Easing", 2: "Operational", 1:"Economic Downturn", 0:"Economic Growth"}

def parse_meeting_end(raw_date, current_year, month_num):
    """Parse a raw date string into a datetime for the last day of a meeting

    Args:
        raw_date (str): Raw date string, may be a single day or a dash-separated range
        current_year (int): The year of the meeting
        month_num (int): The month number (1-12) of the meeting

    Return:
        datetime or None: datetime for the last day of the meeting, or None if the date is unusable
    """
    if not raw_date or raw_date in ("TBD", "—"):
        return None
    if "-" in raw_date:
        first_day, last_day = raw_date.split("-")
        first_day, last_day = int(first_day), int(last_day)

        if last_day < first_day:
            next_month = month_num % 12 + 1
            year = current_year + 1 if next_month == 1 else current_year
            return datetime(year, next_month, last_day)
        else:
            return datetime(current_year, month_num, last_day)
    else:
        return datetime(current_year, month_num, int(raw_date))

def build_url(date_str: str):
    """Build the FOMC minutes URL for a given date string

    Args:
        date_str (str): Date string in YYYYMMDD format

    Return:
        str: URL to the FOMC minutes page for the given date
    """
    year = int(date_str[:4])
    if year <= 1995:
        return f"https://www.federalreserve.gov/fomc/MINUTES/{year}/{date_str}min.htm"
    elif year <= 2007:
        return f"https://www.federalreserve.gov/fomc/minutes/{date_str}.htm"
    else:
        return f"https://www.federalreserve.gov/monetarypolicy/fomcminutes{date_str}.htm"

def build_dates_url(year:int):
    """Build the URL for the FOMC calendar or historical meeting dates page for a given year

    Args:
        year (int): The year to retrieve meeting dates for

    Return:
        str: URL for the FOMC meeting calendar page for that year
    """
    if year < 2021:
        sub_url = "https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm"
        return sub_url.format(year=year)
    else:
        return DATES_URL
    
def parse_month_date(month_text, date, current_year, date1 = None):
    """Parse a month label and day into a list of YYYYMMDD date strings

    Args:
        month_text (str): Month label, possibly a slash-separated pair
        date (str): First day of the meeting as a string
        current_year (int): The year of the meeting
        date1 (str): Last day of the meeting if it spans multiple days

    Return:
        list: List of date strings in YYYYMMDD format for the meeting day(s)
    """
    day_range = []
    for sep in ['/', '⁄', '∕']:
        if sep in month_text:
            month_str = month_text[-3:]
        else:
            month_str = month_text

        try:
            month_num = datetime.strptime(month_str, "%b").month
        except ValueError:
            month_num = datetime.strptime(month_str, "%B").month

        if date1:
            raw_date = "-".join([date, date1])
        else:
            raw_date = date

        meeting_end = parse_meeting_end(raw_date, current_year, month_num)
        date_str = meeting_end.strftime("%Y%m%d")
        day_range.append(date_str)

        if date1:
            meeting_end1 = parse_meeting_end(raw_date, current_year, month_num)
            date_str1 = meeting_end1.strftime("%Y%m%d")
            day_range.append(date_str1)
        
        return day_range

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


class DB_Manager():
    def __init__(self):
        """Initialize the DB_Manager, connect to MongoDB, and set up collections and indexes

        Args:
            None

        Return:
            None
        """
        self.client = pymongo.MongoClient("mongodb://127.0.0.1:27017")
        self.db = self.client["fomc"]
        self.metadata = self.db["fomc_metadata"]
        self.minutes_raw = self.db["fomc_minutes_raw"]
        self.minutes_clean = self.db["fomc_minutes_clean"]

        self.metadata.create_index([("meeting_date", pymongo.ASCENDING)], unique=True)
        self.minutes_raw.create_index([("meeting_date", pymongo.ASCENDING)], unique=True)
        self.minutes_raw.create_index([("raw_text", pymongo.TEXT)])
        self.lda_metadata = self.db['lda_metadata']

    def get_meeting_dates_from_calendar(self, start_year, end_year):
        """Scrape FOMC meeting dates from the Federal Reserve website and store them in MongoDB

        Args:
            start_year (int): First year to scrape (inclusive)
            end_year (int): Last year to scrape

        Return:
            None
        """
        unscraped_count = self.metadata.count_documents({"year": {"$gte": 1994, "$lte": 2020}})
        print(f"unscraped count: {unscraped_count}")
        meeting_dates = []
        # Handles different layout for historical data
        
            # Loop over historic years
        for current_year in range(start_year, end_year + 1):
            time.sleep(scraper_sleep)
            
            if current_year < 2011:                
                sub_url = build_dates_url(current_year)
                resp = requests.get(sub_url, headers=HEADERS, timeout=15)
                print(f"URL: {sub_url}")
                print(f"Status: {resp.status_code}")
                soup = BeautifulSoup(resp.text, "html.parser")

                panels = soup.find_all("div", class_="panel-heading")
                for heading in panels:
                    print(f"Found {len(panels)} panel-heading divs")
                    h5 = heading.find("h5")
                    if not h5:
                        continue

                    match = re.search(r"(\w+)\s+(\d+)(?:-(\d+))?\s+Meeting.*(\d{4})", h5.get_text(strip=True))
                    if not match:
                        continue

                    month_str  = match.group(1)
                    first_day  = match.group(2)
                    last_day   = match.group(3)

                    try:
                        month_num = datetime.strptime(month_str, "%b").month
                    except ValueError:
                        month_num = datetime.strptime(month_str, "%B").month

                    meeting_end = parse_meeting_end(first_day, current_year, month_num)
                    if last_day:
                        meeting_end2 = parse_meeting_end(last_day, current_year, month_num)

                    if meeting_end is None:
                        print("meeting end is empty")
                        continue

                    date_str = meeting_end.strftime("%Y%m%d")
                    day_range = [date_str]
                    if last_day:
                        date_str2 = meeting_end2.strftime("%Y%m%d")
                        day_range.append(date_str2)

                    meeting_dates.append({
                        "meeting_date": day_range,
                        "year": current_year,
                        "month": month_str,
                        "datetime": meeting_end,
                        "minutes_url": build_url(date_str),
                        "scraped": False
                    })
                    unscraped_count -= 1
                    print(f"unscraped count: {unscraped_count}")

            elif current_year >= 2011 and current_year <= 2020:
        
                print(f"scraping {current_year}")
                url = build_dates_url(current_year)
                resp = requests.get(url, headers=HEADERS, timeout=15)

                print(f"URL: {url}")
                print(f"Status: {resp.status_code}")

                soup = BeautifulSoup(resp.text, "html.parser")

                panel_divs = soup.find_all("div", class_=lambda c: c and "panel-padded" in c)
                print(f"found {len(panel_divs)} panel divs")

                for p in panel_divs:
                    h5 = p.find("h5", class_="panel-heading--shaded")
                    

                    match = re.search(r"(\w+)\s+(\d+)(?:-(\d+))?\s+Meeting.*(\d{4})", h5.get_text(strip=True))
                    print(h5.get_text())

                    if not match:
                        continue

                    print(f"found h5 tag")
                    month_str  = match.group(1)
                    first_day  = match.group(2)
                    last_day   = match.group(3)

                    day_range = parse_month_date(month_text=month_str, date=first_day, \
                                                current_year=current_year, date1=last_day)
                    
                    meeting_dates.append({
                            "meeting_date": day_range,
                            "year": current_year,
                            "month": month_str,
                            "datetime": False,
                            "minutes_url": build_url(day_range[0]),
                            "scraped": False
                        })
                    unscraped_count -= 1
                    print(f"unscraped count: {unscraped_count}")
            else:
                # Different Logic for handling modern dates web layout
                url = build_dates_url(current_year)
                resp = requests.get(url, headers=HEADERS, timeout=15)

                print(f"URL: {sub_url}")
                print(f"Status: {resp.status_code}")

                soup = BeautifulSoup(resp.text, "html.parser")

                panels = soup.find_all("div", class_="panel-heading")
                for h in panels:
                    text = h.get_text(strip=True)

                for heading in panels:
                    print(f"Found {len(panels)} panel-heading divs")
                    h4 = heading.find("h4")
                    if not h4:
                        continue
                    match = re.match(r"(\d{4})\s+FOMC Meetings", h4.get_text(strip=True))
                    if not match:
                        continue
                    current_year = int(match.group(1))

                    for meeting_row in heading.find_next_siblings("div", class_="fomc-meeting"):
                        month_div = meeting_row.find("div", class_=lambda c: c and "fomc-meeting__month" in c)
                        date_div  = meeting_row.find("div", class_=lambda c: c and "fomc-meeting__date" in c)

                        if not month_div or not date_div:
                            continue
                        if "notation" in date_div.get_text(strip=True).lower():
                            continue

                        month_text = month_div.find("strong").get_text(strip=True)
                        raw_date   = date_div.get_text(strip=True).replace("*", "").strip()

                        if not raw_date or raw_date in ("TBD", "—"):
                            continue

                        # Handle split headings e.g. "Jan/Feb"
                        month_str = month_text
                        for sep in ['/', '⁄', '∕']:
                            if sep in month_text:
                                month_str = month_text[-3:]
                                break

                        try:
                            month_num = datetime.strptime(month_str, "%b").month
                        except ValueError:
                            month_num = datetime.strptime(month_str, "%B").month

                        meeting_end = parse_meeting_end(raw_date, current_year, month_num)
                        if meeting_end is None:
                            continue

                        date_str = meeting_end.strftime("%Y%m%d")
                        meeting_dates.append({
                            "meeting_date": [date_str],
                            "year": current_year,
                            "month": month_str,
                            "datetime": meeting_end,
                            "minutes_url": build_url(date_str),
                            "scraped": False
                        })
                        unscraped_count -= 1
                        print(f"unscraped count: {unscraped_count}")

        if meeting_dates:
            self.metadata.insert_many(meeting_dates)
        count = self.metadata.count_documents({})
        print(f"Collection has {count} documents after update")
        

    def get_minute_docs(self):
        """Scrape FOMC meeting minutes HTML for all unscraped metadata records and store raw text

        Args:
            None

        Return:
            None
        """
        unscraped_count = self.metadata.count_documents({"scraped": False})
        print(f"unscraped count: {unscraped_count}")

        for doc in self.metadata.find({"scraped": False}):
            chair = None
            raw_text = None
            date_str = doc["meeting_date"]
            
            dates = date_str if isinstance(date_str, list) else [date_str]

            if any(self.minutes_raw.find_one({"date_str": d}) for d in dates):
                continue
            
            resp = None
            for d in dates:
                url = build_url(d)  # also use build_url_by_year not build_url
                
                for i in range(3):
                    try:
                        resp = requests.get(url, headers=HEADERS, timeout=15)
                        if resp.status_code == 200:
                            break
                    except requests.RequestException as e:
                        time.sleep(5)
                                    
            soup = BeautifulSoup(resp.text, "html.parser")

            attend_div = soup.find("div", class_="attendees")
            if attend_div:
                chair = attend_div.find("p").text


            # actual transcript starts after hr tag
                hr = soup.find("hr")
                if not hr:
                    continue
                
                paragraphs = []
                for tag in hr.find_all_next("p"):
                    text = tag.get_text(strip=True)
                
                    if not text:
                        continue
                    if len(text) < 20:  
                        continue
                    if re.match(r"^\d+\.$", text):
                        continue
                        
                    paragraphs.append(text)
                raw_text = "\n\n".join(paragraphs)
            else:

                raw_text = " ".join(p.get_text(strip=True) for p in soup.find_all("p"))
                match = re.search(r"([\w\s]+),\s*Chair", raw_text)
                if match:
                    chair = match.group(1).strip()

            minute_doc = {"meeting_date": date_str, "year": date_str[:4],
                           "raw_text":raw_text,
                            "chair": chair, "scraped_at": datetime.now()}
            
            self.minutes_raw.insert_one(minute_doc)
            self.metadata.update_one(
                {"_id": doc["_id"]},
                {"$set": {"meeting_date": date_str,
                          "scraped": True, "scraped_at": datetime.now()}}
            )
            unscraped_count -= 1
            print(f"unscraped count: {unscraped_count}")

            time.sleep(scraper_sleep)

        

    def corpus_to_sentences(self):
        '''
        Clean every raw document in the corpus

        Args:
            None

        Return:
            list: A list of lists of sentences for each document
        '''
        for doc in self.minutes_raw.find():
            self._clean_doc(doc['raw_text'], 20)

    def _append_year(self):
        '''
        Helper function to update minutes_raw collection with year

        Args:
            None

        Return:
            None
        '''
        for doc in self.metadata.find():

            date_str = doc['meeting_date']

            print(date_str)

    def get_minutes_stats(self):
        """Print average word count and document count per year from the raw minutes collection.

        Args:
            None

        Return:
            None
        """
        pipeline = [
            {"$group": {
                "_id": "$year",
                "avg_word_count": {
                    "$avg": {
                        "$size": {"$split": ["$raw_text", " "]}
                    }
                },
                "doc_count": {"$sum": 1}
            }},
            {"$sort": {"_id": 1}}
        ]

        stats = list(self.minutes_raw.aggregate(pipeline))
        for s in stats:
            print(f"{s['_id']}: {s['doc_count']} docs, avg {s['avg_word_count']:.0f} words")

    def set_scrape(self, year):
        """Reset the scraped flag to False for all metadata documents in a given year

        Args:
            year (int): The year whose metadata documents should be marked as unscraped

        Return:
            None
        """
        self.metadata.update_many(
            {"year": year},
            {"$set": {"scraped": False}}
            )

    def debug_html_structure(self, url):
        """Fetch a URL and print its top-level div classes and paragraph text for debugging

        Args:
            url (str): URL of the page to inspect

        Return:
            None
        """
        print(url)
        print()
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Print all top level divs and their classes
        for div in soup.find_all("div", recursive=False):
            print(div.get("class"), len(div.get_text(strip=True)))
        
        # Print first 500 chars of each p tag
        for i, p in enumerate(soup.find_all("p")):
            text = p.get_text(strip=True)
            if text:
                print(f"p[{i}]: {len(text)} chars — {text[:100]}")

    def get_dates_from_year(self, year):
        """Retrieve one meeting date record for the given year from the metadata collection

        Args:
            year (int): The year to query

        Return:
            list: A list containing at most one document with the meeting_date field
        """
        pipeline = [
        {"$match": {"year": year}},
        {"$project": {"meeting_date": 1, "_id": 0}},
        {"$limit": 1}
        ]

        return list(self.metadata.aggregate(pipeline))
    
    def get_keyword_count(self, *args):
        """Count how many documents contain each keyword using the full-text index

        Args:
            *args (str): One or more keyword strings to search for

        Return:
            result (dict): Mapping from keyword to the number of documents containing that keyword
        """
        result = {}
        start = time.time()
        for keyword in args:
            pipeline = [
                {"$match": {"$text": {"$search": f'"{keyword}"'}}},
                {"$group": {"_id": None, "count": {"$sum": 1}}}
            ]
            docs = list(self.minutes_raw.aggregate(pipeline))
            result[keyword] = docs[0]["count"] if docs else 0

        fin = time.time()
        for k, v in result.items():
            print(f"{k} appeared in {v} docs\n")
        print(f"Text index query for {len(args)} terms took {(fin - start):4f} seconds\n")
        return result
    
    def tokenize_text(self, text):
        """Lemmatize and filter tokens from a text string using spaCy

        Args:
            text (str): Raw text to tokenize

        Return:
            tokens (list): Lemmatized tokens that are nouns, adjectives, or verbs, excluding
                stopwords and tokens shorter than 5 characters
        """
        # make lowercase and remove non-alphabetic characters
        text = text.lower()
        text = re.sub(r"[^a-z\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        chunk_size = 900000
        chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
        
        tokens = []
        for chunk in chunks:
            doc = nlp(chunk)
            chunk_tokens = [
                token.lemma_
                for token in doc
                if token.pos_ in ("NOUN", "ADJ", "VERB")
                and token.lemma_ not in STOPWORDS
                and len(token.lemma_) > 4
                and not token.is_space
            ]
            tokens.extend(chunk_tokens)
        
        return tokens
    
    def tokenize_corpus(self):
        """Tokenize all raw minutes documents and store the results in the clean collection

        Args:
            None

        Return:
            None
        """
        raw_count = self.minutes_raw.count_documents({})
        cleaned_count = self.minutes_clean.count_documents({"meeting_date": {"$exists": True}})
        print(f"{raw_count - cleaned_count} needs cleaning")

        count = 0
        for doc in self.minutes_raw.find({"raw_text": {"$exists": True}}):
            meeting_date = doc['meeting_date']
            
            #check if already tokenized
            if self.minutes_clean.find_one({"meeting_date": meeting_date}):
                continue
            
            tokens = self.tokenize_text(doc['raw_text'])
            
            self.minutes_clean.insert_one({
                "meeting_date": meeting_date,
                "year": doc.get("year"),
                "chair": doc.get("chair"),
                "tokens": tokens,
                "token_count": len(tokens),
                "tokenized_at": datetime.now()
            })
            count += 1
            print(f"{raw_count - cleaned_count - count} docs to clean")
            
        
        count = self.minutes_clean.count_documents({})
        print(f"Cleaned collection has {count} documents")

    def average_token_per_doc(self, type):
        """Print average token count per document grouped by year

        Args:
            type (str): Field name in the clean collection to measure (e.g. "tokens")

        Return:
            None
        """
        pipeline = [
        {"$match": {"tokens": {"$exists": True}}},
        {"$group": {
            "_id": "$year",
            "avg_token_count": {"$avg": {"$size": f"${type}"}},
            "doc_count": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
        ]

        for doc in db_manager.minutes_clean.aggregate(pipeline):
            print(f"{doc['_id']}: {doc['doc_count']} docs, avg {doc['avg_token_count']:.0f}")

    def get_bigrams(self):
        """Build a bigram model from the clean token corpus and return bigram-enhanced documents

        Args:
            None

        Return:
            bigram_docs (list): List of token lists with bigrams joined by underscores
        """
        all_tokens = [
        doc["tokens"] 
        for doc in self.minutes_clean.find({"tokens": {"$exists": True}})]

        bigram_model = Phrases(all_tokens, min_count=5, threshold=10)
        bigram = Phraser(bigram_model)
        bigram_docs = [bigram[tokens] for tokens in all_tokens]

        print([k for k in bigram_model.vocab.keys() if "_" in k][:100])
        print(f"Total documents: {len(bigram_docs)}")

        return bigram_docs
    
    def store_lda_results(self, lda_model, dictionary, corpus):
        """Store per-document topic distributions and LDA metadata in MongoDB

        Args:
            lda_model: Trained Gensim LDA model
            dictionary (Dictionary): Gensim dictionary used to build the corpus
            corpus (list): List of bag-of-words vectors corresponding to clean documents

        Return:
            None
        """
        docs = list(self.minutes_clean.find({"tokens": {"$exists": True}}))
        
        for doc, bow in zip(docs, corpus):
            
            # full topic distribution
            topic_dist = lda_model.get_document_topics(bow, minimum_probability=0.0)
            
            # dominant topic
            dominant_topic = max(topic_dist, key=lambda x: x[1])
            
            self.minutes_clean.update_one(
                {"_id": doc["_id"]},
                {"$set": {
                    "topic_distribution": [
                        {"topic_id": int(t), "weight": round(float(w), 4)}
                        for t, w in topic_dist
                    ],
                    "dominant_topic": int(dominant_topic[0]),
                    "dominant_topic_weight": round(float(dominant_topic[1]), 4),
                }}
            )
        
        print(f"Stored topic distributions for {len(docs)} documents")
        

        topic_words = {}
        for idx, topic in lda_model.print_topics(num_words=10):
            topic_words[str(idx)] = topic
        
        self.db["fomc_lda_metadata"].insert_one({
            "num_topics": lda_model.num_topics,
            "passes": 50,
            "dictionary_size": len(dictionary),
            "topic_words": topic_words,
            "created_at": datetime.now()
        })
        
        print("Stored LDA metadata")

    def show_docs_by_topic(self):
        """Print the number of documents assigned to each dominant topic

        Args:
            None

        Return:
            None
        """
        
        pipeline = [
        {"$group": {"_id": "$dominant_topic", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}}
        ]
        for doc in self.minutes_clean.aggregate(pipeline):
            print(f"Topic {topic_num_TO_words[doc['_id']]}: {doc['count']} documents")

    def show_topic_by_year(self):
        """Print the dominant topic per year
        
        Args:
            None

        Return:
            None
        """
        pipeline = [
            {"$group": {
                "_id": {"year": "$year", "topic": "$dominant_topic"},
                "count": {"$sum": 1}
            }},
            {"$sort": {"count": -1}},
            {"$group": {
                "_id": "$_id.year",
                "most_common_topic": {"$first": "$_id.topic"},
                "count": {"$first": "$count"}
            }},
            {"$sort": {"_id": 1}}
        ]
        for doc in self.minutes_clean.aggregate(pipeline):
            print(f"{doc['_id']}: {topic_num_TO_words[doc['most_common_topic']]}")

    def visualize_lda(self, lda_model, corpus, dictionary):
        """Generate an interactive pyLDAvis visualization and save it as an HTML file

        Args:
            lda_model: Trained LDA model
            corpus (list): List of bag-of-words vectors for the documents
            dictionary (Dictionary): Gensim dictionary used to build the corpus

        Return:
            None
        """
        vis_data = gensimvis.prepare(
            lda_model, 
            corpus, 
            dictionary,
            sort_topics=False 
        )
        
        pyLDAvis.save_html(vis_data, 'lda_visualization.html')
        print("Saved to lda_visualization.html")


if __name__ == '__main__':
    db_manager = DB_Manager()
    #db_manager.get_meeting_dates_from_calendar(2011,2020)
    #db_manager.get_minute_docs()
    #db_manager.get_minutes_stats()
    '''
    db_manager.get_keyword_count("high inflation", "low inflation", \
                                "high unemployment", "low unemployment",\
                                )
    '''
    
    #db_manager.tokenize_corpus()
    #bigram_docs = db_manager.get_bigrams()
    #model, dictionary, corpus = fit_lda(bigram_docs, num_topics=4)
    #db_manager.store_lda_results(model, dictionary=dictionary, corpus=corpus, bigram_docs=bigram_docs)
    #db_manager.show_docs_by_topic()
    #db_manager.visualize_lda(model, corpus=corpus, dictionary=dictionary)
    db_manager.show_topic_by_year()
    
#93-94 format: "https://www.federalreserve.gov/fomc/MINUTES/{year}/{date}min.htm"
#95-07 format: https://www.federalreserve.gov/fomc/minutes/{date}.htm
#08-26 format: https://www.federalreserve.gov/monetarypolicy/fomcminutes{date}.htm
