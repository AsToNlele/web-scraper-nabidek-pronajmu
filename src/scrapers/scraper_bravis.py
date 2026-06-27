import logging
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from disposition import Disposition
from scrapers.rental_offer import RentalOffer
from scrapers.scraper_base import ScraperBase


class ScraperBravis(ScraperBase):

    name = "BRAVIS"
    logo_url = "https://www.bravis.cz/content/img/logo-small.png"
    color = 0xCE0020
    base_url = "https://www.bravis.cz/pronajem-bytu"


    def build_response(self) -> requests.Response:
        url = self.base_url + "?"

        if Disposition.FLAT_1KK in self.disposition or Disposition.FLAT_1 in self.disposition:
            url += "typ-nemovitosti-byt+1=&"
        if Disposition.FLAT_2KK in self.disposition or Disposition.FLAT_2 in self.disposition:
            url += "typ-nemovitosti-byt+2=&"
        if Disposition.FLAT_3KK in self.disposition or Disposition.FLAT_3 in self.disposition:
            url += "typ-nemovitosti-byt+3=&"
        if Disposition.FLAT_4KK in self.disposition or Disposition.FLAT_4 in self.disposition:
            url += "typ-nemovitosti-byt+4=&"
        if Disposition.FLAT_5_UP in self.disposition:
            url += "typ-nemovitosti-byt+5=&"

        url += "typ-nabidky=pronajem-bytu&lokalita=cele-brno&vybavenost=nezalezi&q=&action=search&s=1-20-order-0"

        logging.debug("BRAVIS request: %s", url)

        return requests.get(url, headers=self.headers)

    def get_latest_offers(self) -> list[RentalOffer]:
        response = self.build_response()
        if not response.ok:
            logging.warning("BRAVIS request failed with HTTP %s, skipping scraper", response.status_code)
            return []

        soup = BeautifulSoup(response.text, 'html.parser')

        items: list[RentalOffer] = []

        for item in soup.select(".itemslist .item"):
            title = item.select_one(".desc h1")
            location = item.select_one(".desc .location")
            price = item.select_one(".desc .price")
            image = item.select_one(".image img")
            link = item.select_one("a")
            if not all((title, location, price, image, link)):
                continue
            rent_price = int(re.sub(r"[^\d]", "", next(price.stripped_strings, "0")) or "0")
            total_price = rent_price + parse_monthly_fee(price)

            items.append(RentalOffer(
                scraper = self,
                link = urljoin(self.base_url, link.get("href")),
                title = title.get_text().strip(),
                location = location.get_text().strip(),
                price = rent_price,
                image_url = urljoin(self.base_url, image.get("src")),
                total_price = total_price,
                rent_price = rent_price,
                fees_price = total_price - rent_price,
            ))

        return items


def parse_monthly_fee(price_element) -> int:
    fee_text = price_element.find("small")
    if fee_text is None:
        return 0

    match = re.search(r"\+?\s*(\d[\d\s\u00a0.]*)", fee_text.get_text())
    if not match:
        return 0

    return int(re.sub(r"\D", "", match.group(1)) or "0")
