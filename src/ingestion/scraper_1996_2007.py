from .scraper_base import ScraperBase, build_dates_url, parse_meeting_end_date
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup

class Scraper1996to2007(ScraperBase):

    ERA_START = 1996
    ERA_END = 2007

    @staticmethod
    def build_url(date_str: str):
        """Build the FOMC minutes URL for a given date string

        Args:
            date_str (str): Date string in YYYYMMDD format

        Return:
            str: URL to the FOMC minutes page for the given date
        """
        return f"https://www.federalreserve.gov/fomc/minutes/{date_str}.htm"
    
    def get_meeting_dates(self, year):
        if not self.handles(year):
            print("wrong year for this parser")
            return
        
        meeting_dates = []
        sub_url = build_dates_url(year)
        resp = requests.get(sub_url, headers=self.HEADERS, timeout=15)
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

            meeting_end = parse_meeting_end_date(first_day, year, month_num)
            if last_day:
                meeting_end2 = parse_meeting_end_date(last_day, year, month_num)

            if meeting_end is None:
                print("meeting end is empty")
                continue

            date_str = meeting_end.strftime("%Y%m%d")
            day_range = [date_str]
            if last_day:
                date_str2 = meeting_end2.strftime("%Y%m%d")
                day_range.append(date_str2)

            meeting_dates.append({
                "meeting_end": day_range[-1],
                "year": year,
                "month": month_str,
                "minutes_url": self.build_url(day_range[-1]),
                "scraped": False
                                })

        print(meeting_dates)
        return meeting_dates