import logging
import re
import unicodedata
from dataclasses import dataclass

from scrapers.rental_offer import RentalOffer


@dataclass
class OfferFilter:
    price_min: int | None = None
    price_max: int | None = None
    excluded_localities: list[str] | None = None

    def __post_init__(self):
        self.excluded_localities = [
            normalize_text(locality)
            for locality in (self.excluded_localities or [])
            if locality.strip()
        ]

    def filter(self, offers: list[RentalOffer]) -> tuple[list[RentalOffer], list[RentalOffer]]:
        accepted: list[RentalOffer] = []
        rejected: list[RentalOffer] = []

        for offer in offers:
            reason = self.reject_reason(offer)
            if reason:
                logging.debug("Offer filtered out (%s): %s", reason, offer.link)
                rejected.append(offer)
            else:
                accepted.append(offer)

        return accepted, rejected

    def reject_reason(self, offer: RentalOffer) -> str | None:
        price = offer.total_price if offer.total_price is not None else parse_price(offer.price)
        price_filter_enabled = self.price_min is not None or self.price_max is not None
        if price_filter_enabled and (price is None or price <= 0):
            return "unknown price"

        if self.price_min is not None and price is not None and price < self.price_min:
            return f"price {price} below minimum {self.price_min}"
        if self.price_max is not None and price is not None and price > self.price_max:
            return f"price {price} above maximum {self.price_max}"

        location = normalize_text(offer.location)
        for locality in self.excluded_localities:
            if locality in location:
                return f"excluded locality {locality}"

        return None


def parse_price(price: int | str) -> int | None:
    if isinstance(price, int):
        return price

    matches = re.findall(r"\d[\d\s\u00a0.]*", str(price))
    if not matches:
        return None

    return int(re.sub(r"\D", "", matches[0]))


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return without_accents.casefold()
