# src/fomc_pipeline/ingestion/scraper_base.py
from abc import ABC, abstractmethod
from datetime import datetime
import re
import requests
import time
from bs4 import BeautifulSoup

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
        return "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

def parse_meeting_end_date(raw_date, current_year, month_num):
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

        meeting_end = parse_meeting_end_date(raw_date, current_year, month_num)
        date_str = meeting_end.strftime("%Y%m%d")
        day_range.append(date_str)

        if date1:
            meeting_end1 = parse_meeting_end_date(raw_date, current_year, month_num)
            date_str1 = meeting_end1.strftime("%Y%m%d")
            day_range.append(date_str1)
        
        return day_range
    
class ScraperBase(ABC):
    """Every era-specific scraper must implement these two methods."""

    # Inclusive year range this scraper is responsible for.
    # ERA_END of None means "no upper bound".
    ERA_START: int = None
    ERA_END: int = None

    MAX_RETRIES = 3
    RETRY_SLEEP = 5
    TIMEOUT = 15

    def __init__(self):
        self.HEADERS = {"User-Agent": ("Mozilla/5.0 (academic research scraper)")}

    @classmethod
    def handles(cls, year: int) -> bool:
        """Report whether this scraper covers the given year

        Args:
            year (int): Four digit year

        Return:
            bool: True if year falls inside this scraper's era
        """
        if cls.ERA_START is None:
            return False
        if year < cls.ERA_START:
            return False
        return cls.ERA_END is None or year <= cls.ERA_END

    def fetch(self, url: str):
        """Fetch a URL, retrying on transport errors and non-200 responses

        Args:
            url (str): URL to fetch

        Return:
            requests.Response or None: The 200 response, or None if every attempt failed
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = requests.get(url, headers=self.HEADERS, timeout=self.TIMEOUT)
                if resp.status_code == 200:
                    return resp
                print(f"Status {resp.status_code} for {url}")
            except requests.RequestException as e:
                print(f"Request failed for {url}: {e}")

            if attempt < self.MAX_RETRIES - 1:
                time.sleep(self.RETRY_SLEEP)

        return None

    @abstractmethod
    def get_meeting_dates(self, year: int) -> list[dict]:
        """Return meeting date records for the given year.

        Must return a list of dicts shaped like:
        {"meeting_date": [str], "year": int, "month": str, "minutes_url": str}
        """
        ...

    @staticmethod
    @abstractmethod
    def build_url(date_str: str):
        """Build the FOMC minutes URL for a given date string

        Args:
            date_str (str): Date string in YYYYMMDD format

        Return:
            str: URL to the FOMC minutes page for the given date
        """
        ...

    def get_minutes_text(self, url: str) -> dict:
        """Fetch and parse a single minutes page.

        The layout is detected from the page itself rather than from the year:
        historical pages carry an "attendees" div and put the transcript after
        an <hr>, modern pages do neither. Override in a subclass only if an era
        turns out to need something this cannot handle.

        Args:
            url (str): URL of the minutes page

        Return:
            dict: {"raw_text": str | None, "chair": str | None}
        """
        chair = None
        raw_text = None

        resp = self.fetch(url)
        if resp is None:
            return {"raw_text": None, "chair": None}

        soup = BeautifulSoup(resp.text, "html.parser")

        attend_div = soup.find("div", class_="attendees")
        if attend_div:
            chair_p = attend_div.find("p")
            if chair_p:
                chair = chair_p.text

            # actual transcript starts after hr tag
            hr = soup.find("hr")
            if hr:
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

        return {"raw_text": raw_text, "chair": chair}
