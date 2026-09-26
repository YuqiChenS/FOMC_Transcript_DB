# src/fomc_pipeline/ingestion/scraper_base.py
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

# Month group allows separators so "January/February 31-1" survives intact;
# a bare \w+ captures only "February" and hides the month crossing.
MEETING_HEADING_RE = re.compile(r"([\w/⁄∕]+)\s+(\d+)(?:-(\d+))?\s+Meeting.*(\d{4})")

# Most minutes pages say "minutes" in the path, but a few (e.g. June 2008)
# are published as /monetarypolicy/fomc<YYYYMMDD>.htm with only the PDF
# carrying the word. Anchored on the date so fomcpressconf/fomcprojtabl and
# friends do not match.
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

    A range whose last day is smaller than its first, e.g. "31-1", crosses a
    month boundary. Normally month_num names the month the meeting *starts*
    in, so the end date rolls into the next month. When the caller has already
    resolved a split label like "Jan/Feb" down to the later month, pass
    month_is_end=True so the month is not advanced a second time.

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
                # month_num is already the later month, so do not advance it.
                # A January end still means the meeting began the previous
                # December, so the year rolls forward.
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

    # Derive the start from the resolved end, so this holds whether month_num
    # named the starting or the ending month.
    if int(date1) < int(date):
        start_month = end.month - 1 or 12
        start_year = end.year - 1 if start_month == 12 else end.year
        start = datetime(start_year, start_month, int(date))
    else:
        start = datetime(end.year, end.month, int(date))

    return [start.strftime("%Y%m%d"), end.strftime("%Y%m%d")]


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

    @staticmethod
    def find_minutes_link(container):
        """Pull the minutes URL out of a calendar entry

        The calendar pages link each meeting to its own minutes, which is the
        only reliable source for that URL: the day used varies per meeting
        (1999 uses the first day of a two-day meeting, 2003 the last), and the
        path scheme changes mid-2007. Constructing the URL from a date cannot
        express either. Modern pages offer both a PDF and an HTML version;
        only the HTML one is parseable here.

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

        Meetings are listed as <h5> headings inside panel-heading divs. This
        layout is shared by every era before 2011, so the 1993-1995,
        1996-2007 and 2008-2010 scrapers all read it the same way; only
        build_url differs between them.

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

            # parse_month_date owns the split-label and rollover handling, so
            # every layout resolves dates the same way.
            day_range = parse_month_date(month_label, first_day, year, last_day)
            if not day_range:
                logger.debug("%s: unparseable meeting date in %r", year, month_label)
                continue

            month_str = split_month_label(month_label)[0]

            # The page's own link beats anything we could reconstruct.
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
        """Return meeting date records for the given year.

        Must return a list of dicts shaped like:
        {"meeting_end": str, "year": int, "month": str, "minutes_url": str,
         "scraped": bool}

        meeting_end is the single YYYYMMDD date the minutes are published
        under — the last day of a multi-day meeting. It is the unique key for
        both the metadata and minutes_raw collections.
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

    @staticmethod
    def content_root(soup):
        """Narrow a minutes page down to its article body

        Modern pages wrap the minutes in #article; everything outside it is
        the .gov banner, navigation and the Board's footer address. Older
        pages have no such wrapper, so fall back to the whole document.

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

        The Fed's pre-2011 HTML leaves <p> tags unclosed. html.parser nests
        them rather than auto-closing, so find_all("p") returns outer and
        inner paragraphs alike and get_text() on an outer one repeats every
        descendant -- inflating a 58 KB document to 2.6 MB. Taking only
        paragraphs with no <p> ancestor yields each passage exactly once.

        Args:
            root (Tag): Element to search

        Return:
            list: Paragraph strings in document order
        """
        return [
            text
            for p in root.find_all("p")
            if not p.find_parent("p")
            for text in [p.get_text(" ", strip=True)]
            if text
        ]

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
