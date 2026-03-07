"""Integration tests against live Tweakers.net.

Run with: python -m pytest tests/test_integration.py -v
Requires internet access. Tests use a known active product (Kingston Fury Beast DDR5).
"""

import pytest

from tweakers import (
    BrowseItem,
    CategoryPage,
    PriceHistory,
    ProductInfo,
    SearchResult,
    ShopOffer,
    TweakersClient,
    category_id,
    get_categories,
)

PRODUCT_ID = 2064068  # Kingston Fury Beast DDR5-5600 16GB
PRODUCT_URL = "https://tweakers.net/pricewatch/2064068/kingston-fury-beast-ddr5-5600-cl36-16gb.html"
CATEGORY_SLUG = "processors"


@pytest.fixture(scope="module")
def client():
    return TweakersClient()


# -- Categories registry ---------------------------------------------------

class TestCategories:
    def test_get_categories_returns_dict(self):
        cats = get_categories()
        assert isinstance(cats, dict)
        assert len(cats) > 200

    def test_category_id_known_slug(self):
        cid = category_id("smartphones")
        assert isinstance(cid, int)
        assert cid > 0

    def test_category_id_unknown_slug(self):
        with pytest.raises(ValueError, match="Unknown category slug"):
            category_id("nonexistent-category-slug-xyz")


# -- Search ----------------------------------------------------------------

class TestSearch:
    def test_search_returns_results(self, client):
        results = client.search("Kingston Fury Beast DDR5")
        assert len(results) > 0
        assert all(isinstance(r, SearchResult) for r in results)
        assert all(r.product_id > 0 for r in results)
        assert all(r.name for r in results)

    def test_search_empty_query(self, client):
        results = client.search("xyznonexistent999888777")
        assert results == []

    def test_search_one_found(self, client):
        result = client.search_one("Kingston Fury Beast DDR5")
        assert result is not None
        assert isinstance(result, SearchResult)

    def test_search_one_not_found(self, client):
        result = client.search_one("xyznonexistent999888777")
        assert result is None


# -- Browse category -------------------------------------------------------

class TestBrowseCategory:
    def test_browse_first_page(self, client):
        page = client.browse_category(CATEGORY_SLUG)
        assert isinstance(page, CategoryPage)
        assert page.page == 1
        assert page.total_count > 0
        assert page.total_pages > 0
        assert page.category_id > 0
        assert len(page.items) > 0
        assert all(isinstance(i, BrowseItem) for i in page.items)

    def test_browse_item_fields(self, client):
        page = client.browse_category(CATEGORY_SLUG)
        item = page.items[0]
        assert item.product_id > 0
        assert item.name
        assert item.url

    def test_browse_sort_desc(self, client):
        page = client.browse_category(CATEGORY_SLUG, sort="prijs", sort_dir="desc")
        assert len(page.items) > 0
        # Most expensive first — first item price should be >= last
        prices = [i.price for i in page.items if i.price is not None]
        if len(prices) >= 2:
            assert prices[0] >= prices[-1]

    def test_browse_all_max_pages(self, client):
        items = list(client.browse_all(CATEGORY_SLUG, max_pages=2))
        assert len(items) > 40  # more than one page
        assert all(isinstance(i, BrowseItem) for i in items)

    def test_browse_unknown_slug(self, client):
        with pytest.raises(ValueError, match="Unknown category slug"):
            client.browse_category("nonexistent-category-slug-xyz")


# -- Price history ---------------------------------------------------------

class TestPriceHistory:
    def test_price_history(self, client):
        history = client.get_price_history(PRODUCT_ID)
        assert isinstance(history, PriceHistory)
        assert history.product_id == PRODUCT_ID
        assert history.country == "nl"
        assert len(history.prices) > 0
        assert history.last_price is not None
        assert history.last_price > 0

    def test_price_history_belgium(self, client):
        history = client.get_price_history(PRODUCT_ID, country="be")
        assert history.country == "be"


# -- Product info ----------------------------------------------------------

class TestProductInfo:
    def test_get_product_info(self, client):
        info = client.get_product_info(PRODUCT_ID)
        assert isinstance(info, ProductInfo)
        assert info.product_id == PRODUCT_ID
        assert "Kingston" in info.name or "Fury" in info.name
        assert info.brand
        assert info.url

    def test_get_product_details(self, client):
        info, offers = client.get_product_details(PRODUCT_ID)
        assert isinstance(info, ProductInfo)
        assert isinstance(offers, list)
        assert info.product_id == PRODUCT_ID


# -- Shop offers -----------------------------------------------------------

class TestShopOffers:
    def test_get_current_prices(self, client):
        offers = client.get_current_prices(PRODUCT_ID)
        assert isinstance(offers, list)
        assert len(offers) > 0
        offer = offers[0]
        assert isinstance(offer, ShopOffer)
        assert offer.shop_name
        assert offer.shop_id > 0
        assert offer.price > 0

    def test_get_cheapest_offer(self, client):
        cheapest = client.get_cheapest_offer(PRODUCT_ID)
        assert cheapest is not None
        assert isinstance(cheapest, ShopOffer)
        # Verify it's actually the cheapest
        all_offers = client.get_current_prices(PRODUCT_ID)
        assert cheapest.price == min(o.price for o in all_offers)


# -- Utility ---------------------------------------------------------------

class TestUtility:
    def test_product_id_from_url(self):
        pid = TweakersClient.product_id_from_url(PRODUCT_URL)
        assert pid == PRODUCT_ID

    def test_product_id_from_url_invalid(self):
        with pytest.raises(ValueError, match="No product ID"):
            TweakersClient.product_id_from_url("https://example.com/foo")
