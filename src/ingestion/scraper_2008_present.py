from .scraper_base import ScraperBase, build_dates_url, parse_meeting_end_date, parse_month_date
import logging
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class Scraper2008Present(ScraperBase):

    ERA_START = 2008
    ERA_END = None

    @staticmethod
    def build_url(date_str: str):
        """Build the FOMC minutes URL for a given date string

        Args:
            date_str (str): Date string in YYYYMMDD format

        Return:
            str: URL to the FOMC minutes page for the given date
        """
        return f"https://www.federalreserve.gov/monetarypolicy/fomcminutes{date_str}.htm"

    def get_meeting_dates(self, year):

        if not self.handles(year):
            logger.warning("%s is outside %s (%s-present)",
                           year, type(self).__name__, self.ERA_START)
            return

        meeting_dates = []
        url = build_dates_url(year)
        resp = requests.get(url, headers=self.HEADERS, timeout=15)
        logger.debug("GET %s -> %s", url, resp.status_code)
        soup = BeautifulSoup(resp.text, "html.parser")

        if year < 2011:
            # 2008-2010 still use the historical calendar layout, same as the
            # pre-2008 eras; only the minutes URL scheme differs.
            return self.parse_panel_headings(soup, year)

        elif year <= 2020:
            panel_divs = soup.find_all("div", class_=lambda c: c and "panel-padded" in c)
            logger.debug("%s: %s panel divs", year, len(panel_divs))

            for p in panel_divs:
                h5 = p.find("h5", class_="panel-heading--shaded")
                if not h5:
                    continue

                match = re.search(r"(\w+)\s+(\d+)(?:-(\d+))?\s+Meeting.*(\d{4})", h5.get_text(strip=True))
                if not match:
                    continue

                month_str  = match.group(1)
                first_day  = match.group(2)
                last_day   = match.group(3)

                day_range = parse_month_date(month_text=month_str, date=first_day, \
                                            current_year=year, date1=last_day)

                meeting_dates.append({
                        "meeting_end": day_range[-1],
                        "year": year,
                        "month": month_str,
                        "minutes_url": self.build_url(day_range[-1]),
                        "scraped": False
                    })

            return meeting_dates
        else:
            # Different Logic for handling modern dates web layout
            url = build_dates_url(year)
            resp = requests.get(url, headers=self.HEADERS, timeout=15)
            logger.debug("GET %s -> %s", url, resp.status_code)

            soup = BeautifulSoup(resp.text, "html.parser")

            panels = soup.find_all("div", class_="panel-heading")
            logger.debug("%s: %s panel headings", year, len(panels))

            for heading in panels:
                h4 = heading.find("h4")
                if not h4:
                    continue
                match = re.match(r"(\d{4})\s+FOMC Meetings", h4.get_text(strip=True))
                if not match:
                    continue

                # fomccalendars.htm lists several years on one page; keep only
                # the one asked for so the caller's per-year loop stays honest.
                panel_year = int(match.group(1))
                if panel_year != year:
                    continue

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

                    meeting_end = parse_meeting_end_date(raw_date, year, month_num)
                    if meeting_end is None:
                        continue

                    date_str = meeting_end.strftime("%Y%m%d")
                    meeting_dates.append({
                        "meeting_end": date_str,
                        "year": year,
                        "month": month_str,
                        "minutes_url": self.build_url(date_str),
                        "scraped": False
                    })

            return meeting_dates
    