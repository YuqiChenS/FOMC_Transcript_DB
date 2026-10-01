from .scraper_base import ScraperBase, build_dates_url
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class Scraper1996to2007(ScraperBase):

    ERA_START = 1996
    ERA_END = 2007

    @staticmethod
    def build_url(date_str: str):
        """Build the FOMC minutes URL for a given date string

        Only used if the calendar page doesn't have a link (this era is
        inconsistent about which meeting day the URL uses).

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
            list: Meeting records (empty if the year isn't in this era)
        """
        if not self.handles(year):
            logger.warning("%s is outside %s-%s", year, self.ERA_START, self.ERA_END)
            return []

        resp = self.fetch(build_dates_url(year))
        if resp is None:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")

        return self.parse_panel_headings(soup, year)
