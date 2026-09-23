from scraper_1993_1995 import Scraper1993to1995
from scraper_1996_2007 import Scraper1996to2007
from scraper_2008_present import Scraper2008Present
import time
def main():
    S = Scraper1993to1995()
    for i in range(1993, 1996):
       time.sleep(1)
       S.get_meeting_dates(i)
    S2 = Scraper1996to2007()
    for i in range(1996, 2008):
        time.sleep(1)
        S2.get_meeting_dates(i)
    S1 = Scraper2008Present()
    for i in range(2008, 2027):
        time.sleep(1)
        S1.get_meeting_dates(i)
        
if __name__ == "__main__":
    main()