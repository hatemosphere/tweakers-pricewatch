"""Tweakers.net Pricewatch helper library.

Provides access to product search, current shop prices, and historical price data
from Tweakers.net Pricewatch via reverse-engineered API endpoints.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html import unescape

import requests


_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_BASE = "https://tweakers.net"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PricePoint:
    date: str
    min_price: float
    avg_price: float


@dataclass
class PriceHistory:
    product_id: int
    country: str
    prices: list[PricePoint]
    lowest_ever: float | None = None
    lowest_ever_date: str | None = None
    last_price: float | None = None
    last_price_date: str | None = None


@dataclass
class ProductInfo:
    product_id: int
    name: str
    brand: str = ""
    description: str = ""
    gtin: list[str] = field(default_factory=list)
    mpn: list[str] = field(default_factory=list)
    low_price: float | None = None
    high_price: float | None = None
    offer_count: int = 0
    url: str = ""
    image_url: str | None = None


@dataclass
class ShopOffer:
    shop_name: str
    shop_id: int
    price: float
    product_price: float
    shipping_cost: float
    url: str = ""


@dataclass
class SearchResult:
    product_id: int
    name: str
    url: str
    price: float | None = None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class TweakersClient:
    """Client for Tweakers.net Pricewatch data."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "nl,en;q=0.9",
        })
        self._init_consent_cookies()

    # -- public API ---------------------------------------------------------

    def search(self, query: str) -> list[SearchResult]:
        """Search Tweakers Pricewatch for products matching *query*.

        Uses the undocumented suggest/autocomplete endpoint which returns
        up to ~8 results (5 product editions + 3 entities). No auth needed.
        """
        resp = self.session.get(
            f"{_BASE}/ajax/zoeken/pricewatch/",
            params={"keyword": query},
            headers={"Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results: list[SearchResult] = []
        seen_ids: set[int] = set()

        # "articles" contains productedition items
        for item in data.get("articles", []):
            pid = self._extract_product_id_from_link(item.get("link", ""))
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                results.append(SearchResult(
                    product_id=pid,
                    name=item.get("name", ""),
                    url=item.get("link", ""),
                ))

        # "entities" may contain additional products with prices
        for item in data.get("entities", []):
            if item.get("type") != "product":
                continue
            pid = self._extract_product_id_from_link(item.get("link", ""))
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                price = self._parse_min_price_html(item.get("minPrice", ""))
                results.append(SearchResult(
                    product_id=pid,
                    name=item.get("name", ""),
                    url=item.get("link", ""),
                    price=price,
                ))

        return results

    def get_price_history(
        self, product_id: int, country: str = "nl",
    ) -> PriceHistory:
        """Fetch full price history for a product.

        *country* can be ``"nl"`` (Netherlands) or ``"be"`` (Belgium).
        No authentication required — this endpoint is open.
        """
        resp = self.session.get(
            f"{_BASE}/ajax/price_chart/{product_id}/{country}/",
            headers={
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{_BASE}/pricewatch/{product_id}/",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            error = data.get("error", {}).get("message", "Unknown error")
            raise ValueError(f"Tweakers API error for product {product_id}: {error}")

        points = [
            PricePoint(date=row[0], min_price=row[1], avg_price=row[2])
            for row in data.get("dataset", {}).get("source", [])
            if len(row) >= 3
        ]

        # Extract "lowest ever" from markers
        lowest_ever = None
        for marker_group in data.get("markers", []):
            for marker in marker_group:
                if "yAxis" in marker:
                    val = marker["yAxis"]
                    if lowest_ever is None or val < lowest_ever:
                        lowest_ever = val

        # Find the date of the lowest-ever min price
        lowest_ever_date = None
        if lowest_ever is not None:
            for p in points:
                if p.min_price == lowest_ever:
                    lowest_ever_date = p.date
                    break

        last_price = points[-1].min_price if points else None
        last_price_date = points[-1].date if points else None

        return PriceHistory(
            product_id=product_id,
            country=country,
            prices=points,
            lowest_ever=lowest_ever,
            lowest_ever_date=lowest_ever_date,
            last_price=last_price,
            last_price_date=last_price_date,
        )

    def get_product_info(self, product_id: int) -> ProductInfo:
        """Fetch structured product information from the product page.

        Parses JSON-LD structured data embedded in the HTML.
        """
        html = self._fetch_product_page(product_id)
        return self._parse_product_info(product_id, html)

    def get_current_prices(self, product_id: int) -> list[ShopOffer]:
        """Fetch current shop offers for a product.

        Parses the shop listing table from the product page HTML.
        Returns an empty list for discontinued products with no shops.
        """
        html = self._fetch_product_page(product_id)
        return self._parse_shop_offers(html)

    def get_product_details(self, product_id: int) -> tuple[ProductInfo, list[ShopOffer]]:
        """Fetch product info and current shop prices in a single request."""
        html = self._fetch_product_page(product_id)
        info = self._parse_product_info(product_id, html)
        offers = self._parse_shop_offers(html)
        return info, offers

    @staticmethod
    def product_id_from_url(url: str) -> int:
        """Extract product ID from a Tweakers Pricewatch URL.

        >>> TweakersClient.product_id_from_url(
        ...     "https://tweakers.net/pricewatch/1562498/foo.html"
        ... )
        1562498
        """
        m = re.search(r"/pricewatch/(\d+)", url)
        if not m:
            raise ValueError(f"No product ID found in URL: {url}")
        return int(m.group(1))

    # -- private helpers ----------------------------------------------------

    def _init_consent_cookies(self) -> None:
        """Follow the DPG Media consent redirect to obtain session cookies."""
        self.session.get(f"{_BASE}/", timeout=15, allow_redirects=True)

    def _fetch_product_page(self, product_id: int) -> str:
        resp = self.session.get(
            f"{_BASE}/pricewatch/{product_id}/",
            timeout=15,
            allow_redirects=True,
        )
        resp.raise_for_status()
        return resp.text

    @staticmethod
    def _parse_product_info(product_id: int, html: str) -> ProductInfo:
        # Try JSON-LD first — Tweakers wraps it in @graph
        ld_match = re.search(
            r'<script\s+type="application/ld\+json">\s*(\{.*?\})\s*</script>',
            html,
            re.DOTALL,
        )
        if ld_match:
            try:
                ld_root = json.loads(ld_match.group(1))
                # Find the Product entry in @graph
                product_ld = None
                for item in ld_root.get("@graph", []):
                    if item.get("@type") == "Product":
                        product_ld = item
                        break
                # Fallback: maybe it's a direct Product (no @graph)
                if product_ld is None and ld_root.get("@type") == "Product":
                    product_ld = ld_root

                if product_ld:
                    offers = product_ld.get("offers", {})
                    images = product_ld.get("image", [])
                    return ProductInfo(
                        product_id=product_id,
                        name=product_ld.get("name", ""),
                        brand=(
                            product_ld["brand"].get("name", "")
                            if isinstance(product_ld.get("brand"), dict)
                            else ""
                        ),
                        description=product_ld.get("description", ""),
                        gtin=product_ld.get("gtin13", []) if isinstance(product_ld.get("gtin13"), list) else [],
                        mpn=product_ld.get("mpn", []) if isinstance(product_ld.get("mpn"), list) else [],
                        low_price=_to_float(offers.get("lowPrice")),
                        high_price=_to_float(offers.get("highPrice")),
                        offer_count=int(offers.get("offerCount", 0)),
                        url=product_ld.get("url", f"{_BASE}/pricewatch/{product_id}/"),
                        image_url=images[0] if isinstance(images, list) and images else images if isinstance(images, str) else None,
                    )
            except (json.JSONDecodeError, KeyError):
                pass

        # Fallback: data-product attribute
        dp_match = re.search(r'data-product="([^"]*)"', html)
        if dp_match:
            try:
                dp = json.loads(unescape(dp_match.group(1)))
                return ProductInfo(
                    product_id=product_id,
                    name=dp.get("name", ""),
                    url=dp.get("url", f"{_BASE}/pricewatch/{product_id}/"),
                    image_url=dp.get("img"),
                )
            except (json.JSONDecodeError, KeyError):
                pass

        return ProductInfo(product_id=product_id, name="", url=f"{_BASE}/pricewatch/{product_id}/")

    @staticmethod
    def _parse_shop_offers(html: str) -> list[ShopOffer]:
        offers: list[ShopOffer] = []

        # Split by <li data-shop-id="..."> elements
        for m in re.finditer(
            r'<li\s+data-shop-id="(\d+)"[^>]*>(.*?)</li>',
            html,
            re.DOTALL,
        ):
            shop_id = int(m.group(1))
            block = m.group(2)

            # Shop name — inside <span class="shop-name"><a>Name</a></span>
            name_m = re.search(r'class="shop-name"[^>]*>\s*<a[^>]*>(.*?)</a>', block, re.DOTALL)
            shop_name = _strip_html(name_m.group(1)) if name_m else ""

            # Try cost breakdown from tooltip (most accurate)
            product_price = 0.0
            shipping_cost = 0.0
            total_price = 0.0

            tooltip_m = re.search(r'data-tooltip-html="([^"]*)"', block)
            if tooltip_m:
                tooltip = unescape(tooltip_m.group(1))
                # Parse <dt>Label</dt><dd>€ X,-</dd> pairs
                prod_m = re.search(r'Productprijs</dt>\s*<dd>€\s*([\d.,]+(?:-)?)', tooltip)
                ship_m = re.search(r'Pakketpost[^<]*</dt>\s*<dd>€\s*([\d.,]+(?:-)?)', tooltip)
                total_m = re.search(r'Totaal[^<]*</(?:b>)?</dt>\s*<dd>€\s*([\d.,]+(?:-)?)', tooltip)
                if prod_m:
                    product_price = _parse_dutch_price(prod_m.group(1))
                if ship_m:
                    shipping_cost = _parse_dutch_price(ship_m.group(1))
                if total_m:
                    total_price = _parse_dutch_price(total_m.group(1))

            # Fallback: parse displayed price from <span class="shop-price">
            if total_price == 0.0:
                price_m = re.search(r'class="shop-price"[^>]*>.*?€\s*([\d.,]+(?:-)?)', block, re.DOTALL)
                if price_m:
                    total_price = _parse_dutch_price(price_m.group(1))
                    product_price = total_price

            if total_price == 0.0:
                continue

            # Clickout URL — first <a> with href containing "clickout"
            url = ""
            url_m = re.search(r'href="([^"]*clickout[^"]*)"', block)
            if url_m:
                url = url_m.group(1)
                if url.startswith("/"):
                    url = _BASE + url

            offers.append(ShopOffer(
                shop_name=shop_name,
                shop_id=shop_id,
                price=total_price,
                product_price=product_price,
                shipping_cost=shipping_cost,
                url=url,
            ))

        return offers

    @staticmethod
    def _extract_product_id_from_link(link: str) -> int | None:
        m = re.search(r"/pricewatch/(\d+)", link)
        return int(m.group(1)) if m else None

    @staticmethod
    def _parse_min_price_html(html_snippet: str) -> float | None:
        """Parse price from HTML like ``<a ...>vanaf € 91,99</a>``."""
        m = re.search(r'€\s*([\d,.]+(?:-)?)', html_snippet)
        if m:
            return _parse_dutch_price(m.group(1))
        return None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _parse_dutch_price(s: str) -> float:
    """Parse Dutch price string like ``399,-`` or ``135,50`` to float."""
    s = s.strip().rstrip("-").rstrip(",")
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _to_float(val: object) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val))
    except (ValueError, TypeError):
        return None


def _strip_html(s: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", s)).strip()
