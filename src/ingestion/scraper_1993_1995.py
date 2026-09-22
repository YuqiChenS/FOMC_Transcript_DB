from scraper_base import ScraperBase, build_dates_url, parse_meeting_end_date
import re
import datetime
import requests
from bs4 import BeautifulSoup 

class Scraper1993to1995(ScraperBase):

    def build_url(date_str: str):
            """Build the FOMC minutes URL for a given date string
    
            Args:
                date_str (str): Date string in YYYYMMDD format
    
            Return:
                str: URL to the FOMC minutes page for the given date
            """
            year = int(date_str[:4])
            return f"https://www.federalreserve.gov/fomc/MINUTES/{year}/{date_str}min.htm"
            
    def get_meeting_dates(self, year):
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

        return [{"meeting_date": day_range, "year": year, "month": month_str, "minutes_url": \
                 self.build_url(date_str), "scraped":False}]

    def get_minutes_text(self, url):
        # this era's page has no <hr> splitting logic — different parsing entirely
        ...
        return {"raw_text": ..., "chair": ...}