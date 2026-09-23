# src/fomc_pipeline/ingestion/scraper_base.py
from abc import ABC, abstractmethod
from datetime import datetime

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
    def __init__(self):
        self.HEADERS = {"User-Agent": ("Mozilla/5.0 (academic research scraper)")}

    @abstractmethod
    def get_meeting_dates(self, year: int) -> list[dict]:
        """Return meeting date records for the given year.

        Must return a list of dicts shaped like:
        {"meeting_date": [str], "year": int, "month": str, "minutes_url": str}
        """
        ...

    @abstractmethod
    def get_minutes_text(self, url: str) -> dict:
        """Fetch and parse a single minutes page.

        Must return a dict shaped like:
        {"raw_text": str, "chair": str | None}
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