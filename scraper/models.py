"""
models.py — Dataclasses for queries, results and scraped items.

Supports the multilingual CSV format:
    query_id, category_l1, category_l2, query_type, Query_EN, Query_IT, Query_DE
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


LANG_TO_COUNTRY = {
    "IT": "IT",
    "EN": "US",
    "DE": "DE",
}


@dataclass
class QuerySpec:
    """Specification of a single query read from the multilingual CSV."""
    query_id: str
    keyword: str
    country: str = "IT"
    language: str = "IT"
    category_l1: str = ""
    category_l2: str = ""
    query_type: str = "generic"
    max_results: int = 20


@dataclass
class ScrapedItem:
    """Single product extracted from Google Shopping."""
    query_id: str
    keyword: str
    language: str
    title: str
    price_raw: str
    price_value: float | None
    currency: str
    seller: str
    rating: float | None
    reviews_count: int | None
    url: str
    image_url: str
    position: int
    category_l1: str = ""
    category_l2: str = ""
    query_type: str = "generic"
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    run_id: str = ""


@dataclass
class QueryResult:
    """Aggregated result of a query."""
    spec: QuerySpec
    items: list[ScrapedItem]
    run_id: str
    duration_s: float
    error: str | None = None


def parse_price(raw: str) -> tuple[float | None, str]:
    """Extracts numeric value and currency from a raw price string."""
    if not raw:
        return None, ""
    raw = raw.replace("\xa0", " ").strip()

    currency = (
        "EUR" if "€" in raw else
        "USD" if "$" in raw else
        "GBP" if "£" in raw else
        ""
    )

    digits = re.sub(r"[^\d,.]", "", raw)
    if "," in digits and "." in digits:
        if digits.index(",") > digits.index("."):
            digits = digits.replace(".", "").replace(",", ".")
        else:
            digits = digits.replace(",", "")
    elif "," in digits:
        parts = digits.split(",")
        if len(parts[-1]) == 2:
            digits = digits.replace(",", ".")
        else:
            digits = digits.replace(",", "")

    try:
        return float(digits), currency
    except ValueError:
        return None, currency


def raw_item_to_scraped(
    raw: dict[str, Any],
    spec: QuerySpec,
    position: int,
    run_id: str,
) -> ScrapedItem:
    """Converts a raw Apify item → normalized ScrapedItem."""
    price_raw = raw.get("price", "") or ""
    price_value, currency = parse_price(price_raw)

    # Rating: burbn uses "productRating", legacy schema "rating"
    rating = raw.get("productRating", raw.get("rating"))
    if rating is not None:
        try:
            rating = float(rating)
        except (ValueError, TypeError):
            rating = None

    # Reviews: burbn uses "productNumReviews"
    reviews = (
        raw.get("productNumReviews")
        or raw.get("reviewsCount")
        or raw.get("reviews_count")
    )
    if reviews is not None:
        try:
            reviews = int(reviews)
        except (ValueError, TypeError):
            reviews = None

    # Image: burbn returns "productPhotos" as a list
    image_url = ""
    photos = raw.get("productPhotos")
    if isinstance(photos, list) and photos:
        image_url = photos[0] or ""
    if not image_url:
        image_url = raw.get("thumbnail", "") or raw.get("imageUrl", "") or ""

    return ScrapedItem(
        query_id=spec.query_id,
        keyword=spec.keyword,
        language=spec.language,
        title=raw.get("productTitle") or raw.get("title") or "N/A",
        price_raw=price_raw,
        price_value=price_value,
        currency=currency,
        seller=(
            raw.get("storeName")
            or raw.get("seller")
            or raw.get("merchant")
            or ""
        ),
        rating=rating,
        reviews_count=reviews,
        url=(
            raw.get("offerPageUrl")
            or raw.get("productPageUrl")
            or raw.get("link")
            or raw.get("url")
            or ""
        ),
        image_url=image_url,
        position=position,
        category_l1=spec.category_l1,
        category_l2=spec.category_l2,
        query_type=spec.query_type,
        run_id=run_id,
    )
