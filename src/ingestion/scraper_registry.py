from .scraper_base import ScraperBase
from .scraper_1993_1995 import Scraper1993to1995
from .scraper_1996_2007 import Scraper1996to2007
from .scraper_2008_present import Scraper2008Present

SCRAPERS = (
    Scraper1993to1995,
    Scraper1996to2007,
    Scraper2008Present,
)


class ScraperRegistry:
    """Picks the right scraper for a given year.

    Keeps one instance per scraper so we don't create a new one for every meeting.
    """

    def __init__(self, scrapers=SCRAPERS):
        """Initialize the registry

        Args:
            scrapers (tuple): ScraperBase subclasses to dispatch across

        Return:
            None
        """
        self._classes = tuple(scrapers)
        self._instances = {}

    def for_year(self, year: int) -> ScraperBase:
        """Return the scraper instance covering the given year

        Args:
            year (int): Four digit year

        Return:
            ScraperBase: Cached scraper instance for that era

        Raises:
            ValueError: If no registered scraper claims the year
        """
        for cls in self._classes:
            if cls.handles(year):
                if cls not in self._instances:
                    self._instances[cls] = cls()
                return self._instances[cls]

        raise ValueError(f"no scraper registered for year {year}")

