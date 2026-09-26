from .scraper_base import ScraperBase, build_dates_url
import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class Scraper1996to2007(ScraperBase):

    ERA_START = 1996
    ERA_END = 2007

    @staticmethod
    def build_url(date_str: str):
        """Build the FOMC minutes URL for a given date string

        Only a fallback. This era is the reason URL construction is unsafe:
        1999 files two-day meetings under the first day while 2003 uses the
        last, and from October 2007 the path switches to the modern
        /monetarypolicy/ scheme mid-year. get_meeting_dates reads the real
        link off the calendar page instead.

        Args:
            date_str (str): Date string in YYYYMMDD format

        Return:
            str: URL to the FOMC minutes page for the given date
        """
        return f"https://www.federalreserve.gov/fomc/minutes/{date_str}.htm"

    def get_meeting_dates(self, year):
        """Return meeting date records for the given year

        Args:
            year (int): Four digit year

        Return:
            list: Meeting records, or None if the year is outside this era
        """
        if not self.handles(year):
            logger.warning("%s is outside %s (%s-%s)",
                           year, type(self).__name__, self.ERA_START, self.ERA_END)
            return

        sub_url = build_dates_url(year)
        resp = requests.get(sub_url, headers=self.HEADERS, timeout=self.TIMEOUT)
        logger.debug("GET %s -> %s", sub_url, resp.status_code)
        soup = BeautifulSoup(resp.text, "html.parser")

        return self.parse_panel_headings(soup, year)
