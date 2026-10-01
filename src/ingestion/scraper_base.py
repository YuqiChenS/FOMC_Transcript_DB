from abc import ABC, abstractmethod
from datetime import datetime
import logging
import re
import requests
import time
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

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

FED_ROOT = "https://www.federalreserve.gov"

MONTH_SEPARATORS = ('/', '⁄', '∕')

# month can be "January/February" so allow slashes in the first group
MEETING_HEADING_RE = re.compile(r"([\w/⁄∕]+)\s+(\d+)(?:-(\d+))?\s+Meeting.*(\d{4})")

# some minutes pages (like June 2008) are just fomcYYYYMMDD.htm without "minutes"
MINUTES_HTML_RE = re.compile(r"/fomc(?:minutes)?\d{8}\.htm$", re.I)


def split_month_label(month_text):
    """Resolve a month label that may name two months, e.g. "Jan/Feb"

    Args:
        month_text (str): Month label from the calendar page

    Return:
        tuple: (month_str, spans_months) where month_str is the month the
            meeting ends in, and spans_months says whether the label named two
    """
    for sep in MONTH_SEPARATORS:
        if sep in month_text:
            return month_text.split(sep)[-1].strip(), True
    return month_text, False


def month_number(month_str):
    """Convert an abbreviated or full month name to its number

    Args:
        month_str (str): Month name, e.g. "Jan" or "January"

    Return:
        int: Month number 1-12
    """
    try:
        return datetime.strptime(month_str, "%b").month
    except ValueError:
        return datetime.strptime(month_str, "%B").month


def parse_meeting_end_date(raw_date, current_year, month_num, month_is_end=False):
    """Parse a raw date string into a datetime for the last day of a meeting

    If the last day is smaller than the first (e.g. "31-1") the meeting goes
    into the next month. If month_num is already the later month (from a
    "Jan/Feb" label) pass month_is_end=True so it doesn't get bumped twice.

    Args:
        raw_date (str): Raw date string, may be a single day or a dash-separated range
        current_year (int): The year of the meeting
        month_num (int): The month number (1-12) of the meeting
        month_is_end (bool): True if month_num already names the ending month

    Return:
        datetime or None: datetime for the last day of the meeting, or None if the date is unusable
    """
    if not raw_date or raw_date in ("TBD", "—"):
        return None

    if "-" in raw_date:
        first_day, last_day = raw_date.split("-")
        first_day, last_day = int(first_day), int(last_day)

        if last_day < first_day:
            if month_is_end:
                # Dec/Jan meeting ends in January of the next year
                year = current_year + 1 if month_num == 1 else current_year
                return datetime(year, month_num, last_day)

            next_month = month_num % 12 + 1
            year = current_year + 1 if next_month == 1 else current_year
            return datetime(year, next_month, last_day)

        return datetime(current_year, month_num, last_day)

    return datetime(current_year, month_num, int(raw_date))


def parse_month_date(month_text, date, current_year, date1=None):
    """Parse a month label and day range into YYYYMMDD date strings

    Args:
        month_text (str): Month label, possibly a slash-separated pair
        date (str): First day of the meeting as a string
        current_year (int): The year of the meeting
        date1 (str): Last day of the meeting if it spans multiple days

    Return:
        list: [start, end] date strings, or [date] for a single-day meeting
    """
    month_str, spans_months = split_month_label(month_text)
    month_num = month_number(month_str)

    if not date1:
        single = parse_meeting_end_date(date, current_year, month_num)
        return [single.strftime("%Y%m%d")] if single else []

    raw_date = f"{date}-{date1}"
    end = parse_meeting_end_date(raw_date, current_year, month_num,
                                 month_is_end=spans_months)
    if end is None:
        return []

    # work backwards from the end date to get the start date
    if int(date1) < int(date):
        start_month = end.month - 1 or 12
        start_year = end.year - 1 if start_month == 12 else end.year
        start = datetime(start_year, start_month, int(date))
    else:
        start = datetime(end.year, end.month, int(date))

    return [start.strftime("%Y%m%d"), end.strftime("%Y%m%d")]


class ScraperBase(ABC):
    """Base class for the scrapers, each one covers a range of years (era)"""

    # years this scraper covers, ERA_END = None means up to today
    ERA_START = None
    ERA_END = None

    MAX_RETRIES = 3
    RETRY_SLEEP = 5
    TIMEOUT = 15
    HEADERS = {"User-Agent": "Mozilla/5.0 (academic research scraper)"}

    @staticmethod
    def find_minutes_link(container):
        """Pull the minutes URL out of a calendar entry

        Better than building the URL from the date because the Fed isn't
        consistent (1999 uses the first day of the meeting, 2003 the last, and
        the URL format changes in 2007). Only the .htm link is used, not the PDF.

        Args:
            container (Tag): Calendar element holding one meeting's links

        Return:
            str or None: Absolute URL to the minutes page, or None if absent
        """
        hrefs = [a["href"].split("#")[0] for a in container.find_all("a", href=True)]

        html_links = [
            h for h in hrefs
            if h.lower().endswith(".htm")
            and ("minutes" in h.lower() or MINUTES_HTML_RE.search(h))
        ]
        if not html_links:
            return None

        href = html_links[0]
        if href.startswith("http"):
            return href
        return f"{FED_ROOT}{href}"

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
                logger.warning("HTTP %s for %s (attempt %s/%s)",
                               resp.status_code, url, attempt + 1, self.MAX_RETRIES)
            except requests.RequestException as e:
                logger.warning("request failed for %s (attempt %s/%s): %s",
                               url, attempt + 1, self.MAX_RETRIES, e)

            if attempt < self.MAX_RETRIES - 1:
                time.sleep(self.RETRY_SLEEP)

        return None

    def parse_panel_headings(self, soup, year):
        """Parse the pre-2011 fomchistorical<year>.htm calendar layout

        Every year before 2011 uses this layout (meetings are <h5> headings
        inside panel-heading divs) so all three scrapers share it.

        Args:
            soup (BeautifulSoup): Parsed calendar page
            year (int): Four digit year being scraped

        Return:
            list: Meeting records shaped per get_meeting_dates
        """
        meeting_dates = []

        panels = soup.find_all("div", class_="panel-heading")
        logger.debug("%s: %s panel headings", year, len(panels))

        for heading in panels:
            h5 = heading.find("h5")
            if not h5:
                continue

            match = MEETING_HEADING_RE.search(h5.get_text(strip=True))
            if not match:
                continue

            month_label = match.group(1)
            first_day = match.group(2)
            last_day = match.group(3)

            day_range = parse_month_date(month_label, first_day, year, last_day)
            if not day_range:
                logger.debug("%s: unparseable meeting date in %r", year, month_label)
                continue

            month_str = split_month_label(month_label)[0]

            # use the link on the page, only build it ourselves if it's missing
            minutes_url = self.find_minutes_link(heading.parent)
            if minutes_url is None:
                minutes_url = self.build_url(day_range[-1])
                logger.debug("%s: no minutes link for %s, falling back to %s",
                             year, day_range[-1], minutes_url)

            meeting_dates.append({
                "meeting_end": day_range[-1],
                "year": year,
                "month": month_str,
                "minutes_url": minutes_url,
                "scraped": False,
            })

        return meeting_dates

    @abstractmethod
    def get_meeting_dates(self, year: int) -> list[dict]:
        """Return a list of meeting dicts for the year:
        {"meeting_end": str, "year": int, "month": str, "minutes_url": str, "scraped": bool}

        meeting_end (YYYYMMDD, last day of the meeting) is the unique key in Mongo
        """
        pass

    @staticmethod
    @abstractmethod
    def build_url(date_str: str):
        """Build the FOMC minutes URL for a given date string

        Args:
            date_str (str): Date string in YYYYMMDD format

        Return:
            str: URL to the FOMC minutes page for the given date
        """
        pass

    @staticmethod
    def content_root(soup):
        """Narrow a minutes page down to its article body

        Newer pages put the minutes in #article, older ones don't have it so
        just use the whole page.

        Args:
            soup (BeautifulSoup): Parsed minutes page

        Return:
            Tag: The element containing the minutes text
        """
        return (soup.find(id="article")
                or soup.find("div", class_="col-xs-12 col-sm-8")
                or soup)

    @staticmethod
    def article_paragraphs(root):
        """Collect paragraph text without double-counting nested markup

        Old pages never close their <p> tags so html.parser nests them, and
        get_text() on the outer one repeats everything inside it (the text was
        coming out way too big). Skipping any <p> that's inside another <p>
        fixes it.

        Args:
            root (Tag): Element to search

        Return:
            list: Paragraph strings in document order
        """
        paragraphs = []
        for p in root.find_all("p"):
            if p.find_parent("p"):
                continue
            text = p.get_text(" ", strip=True)
            if text:
                paragraphs.append(text)
        return paragraphs

    def get_minutes_text(self, url: str) -> dict:
        """Fetch and parse a single minutes page.

        Args:
            url (str): URL of the minutes page

        Return:
            dict: {"raw_text": str | None, "chair": str | None}
        """
        resp = self.fetch(url)
        if resp is None:
            return {"raw_text": None, "chair": None}

        soup = BeautifulSoup(resp.text, "html.parser")
        root = self.content_root(soup)

        paragraphs = self.article_paragraphs(root)
        if not paragraphs:
            logger.warning("no paragraphs found in %s", url)
            return {"raw_text": None, "chair": None}

        raw_text = "\n\n".join(paragraphs)

        chair = None
        attend_div = soup.find("div", class_="attendees")
        if attend_div:
            chair_p = attend_div.find("p")
            if chair_p:
                chair = chair_p.get_text(" ", strip=True)
        if chair is None:
            match = re.search(r"([\w\s]+),\s*Chair", raw_text)
            if match:
                chair = match.group(1).strip()

        return {"raw_text": raw_text, "chair": chair}
