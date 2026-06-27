import json
import logging
import re
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from disposition import Disposition
from scrapers.rental_offer import RentalOffer
from scrapers.scraper_base import ScraperBase


class ScraperSreality(ScraperBase):

    name = "Sreality"
    logo_url = "https://www.sreality.cz/img/icons/android-chrome-192x192.png"
    color = 0xCC0000
    base_url = "https://www.sreality.cz"

    disposition_mapping = {
        Disposition.FLAT_1KK: "1+kk",
        Disposition.FLAT_1: "1+1",
        Disposition.FLAT_2KK: "2+kk",
        Disposition.FLAT_2: "2+1",
        Disposition.FLAT_3KK: "3+kk",
        Disposition.FLAT_3: "3+1",
        Disposition.FLAT_4KK: "4+kk",
        Disposition.FLAT_4: "4+1",
        Disposition.FLAT_5_UP: ("5+kk", "5+1", "6-a-vice"),
        Disposition.FLAT_OTHERS: "atypicky",
    }

    def _create_link_to_offer(self, offer) -> str:
        locality = offer.get("locality", {})
        locality_slug = "-".join(filter(None, [
            locality.get("citySeoName"),
            locality.get("cityPartSeoName"),
            locality.get("streetSeoName")
        ]))
        category_sub = self._slugify_disposition(offer["categorySubCb"]["name"])

        return urljoin(
            self.base_url,
            f"/detail/pronajem/byt/{category_sub}/{locality_slug}/{offer['id']}"
        )

    @staticmethod
    def _slugify_disposition(value: str) -> str:
        return re.sub(r"\s+", "-", value.strip().lower()).replace("více", "vice")

    @staticmethod
    def _format_location(locality: dict) -> str:
        return ", ".join(filter(None, [
            locality.get("street"),
            locality.get("cityPart"),
            locality.get("city")
        ]))

    @staticmethod
    def _find_search_results(payload: dict) -> list[dict]:
        queries = payload.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
        for query in queries:
            data = query.get("state", {}).get("data")
            if isinstance(data, dict) and isinstance(data.get("results"), list):
                return data["results"]
        return []

    def build_response(self) -> requests.Response:
        dispositions = quote(",".join(self.get_dispositions_data()), safe=",")
        url = self.base_url + f"/hledani/pronajem/byty/brno?velikost={dispositions}"

        logging.debug("Sreality request: %s", url)

        return requests.get(url, headers=self.headers)

    def get_latest_offers(self) -> list[RentalOffer]:
        raw_response = self.build_response()
        if not raw_response.ok:
            logging.warning(
                "Sreality request failed with HTTP %s, skipping scraper",
                raw_response.status_code
            )
            return []

        soup = BeautifulSoup(raw_response.text, "html.parser")
        next_data = soup.find("script", id="__NEXT_DATA__")
        if not next_data or not next_data.string:
            logging.warning("Sreality response did not include search data, skipping scraper")
            return []

        try:
            response = json.loads(next_data.string)
        except ValueError:
            logging.warning("Sreality search data could not be parsed, skipping scraper")
            return []

        items: list[RentalOffer] = []

        for item in self._find_search_results(response):
            images = item.get("images") or []
            image_url = images[0]["url"] if images else ""
            items.append(RentalOffer(
                scraper = self,
                link = self._create_link_to_offer(item),
                title = item["name"],
                location = self._format_location(item.get("locality", {})),
                price = item["priceCzk"],
                image_url = "https:" + image_url if image_url.startswith("//") else image_url
            ))

        return items
