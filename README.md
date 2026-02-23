# tweakers-pricewatch

Unofficial Python client for [Tweakers.net](https://tweakers.net) Pricewatch — the biggest price comparison site in the Netherlands.

Lets you search products, browse categories, pull current shop prices, and grab full price history (years of daily min/avg data). All from reverse-engineered endpoints, no API key needed.

## Install

Just `requests` as a dependency. Copy `tweakers.py` + `categories.json` into your project, or:

```
pip install requests
```

## Quick start

```python
from tweakers import TweakersClient

client = TweakersClient()
```

### Search for a product

```python
results = client.search("DDR5 6000")
for r in results:
    print(f"[{r.product_id}] {r.name} — {r.url}")
```

Or grab just the first match:

```python
r = client.search_one("F4-3600C16D-32GTZN")
if r:
    print(f"{r.name} [{r.product_id}]")
```

### Browse a category

List all products in a category with pagination and sorting — 40 items per page:

```python
page = client.browse_category("smartphones", sort="prijs", sort_dir="asc")

print(f"{page.total_count} products, page {page.page}/{page.total_pages}")
for item in page.items[:5]:
    print(f"  {item.name} — EUR {item.price} ({item.shop_count} shops)")
```

Auto-paginate through all results with `browse_all()`:

```python
for item in client.browse_all("interne-ssds"):
    print(f"{item.name}: EUR {item.price}")
```

Limit to the first N pages:

```python
for item in client.browse_all("videokaarten", max_pages=3):
    print(f"{item.name}: EUR {item.price}")
```

Sort by `"prijs"` (price), `"popularity"`, or `"score"` (rating). See [CATEGORIES.md](CATEGORIES.md) for all 243 available category slugs.

### Look up categories

```python
from tweakers import get_categories, category_id

cats = get_categories()            # {slug: {id, name}, ...}
cid = category_id("videokaarten")  # -> 49
```

### Price history

Daily min and average prices going back years:

```python
history = client.get_price_history(2064068)

print(f"{len(history.prices)} days of data")
print(f"Lowest ever: EUR {history.lowest_ever} ({history.lowest_ever_date})")
print(f"Last known:  EUR {history.last_price} ({history.last_price_date})")

for p in history.prices[-5:]:
    print(f"  {p.date}  min=EUR {p.min_price}  avg=EUR {p.avg_price}")
```

Belgium prices too:

```python
history_be = client.get_price_history(2064068, country="be")
```

### Product info

Structured data from JSON-LD:

```python
info = client.get_product_info(2064068)
print(f"{info.brand} {info.name}")
print(f"MPN: {info.mpn}")        # ['KF560C30BBEK2-32']
print(f"EAN: {info.gtin}")        # ['0740617342994']
print(f"EUR {info.low_price} - {info.high_price} ({info.offer_count} shops)")
```

### Current shop prices

All offers:

```python
offers = client.get_current_prices(2064068)
for o in offers:
    print(f"  {o.shop_name}: EUR {o.price}")
```

Or just the cheapest:

```python
cheapest = client.get_cheapest_offer(2064068)
if cheapest:
    print(f"EUR {cheapest.price} at {cheapest.shop_name}")
```

### Combo: info + prices in one request

```python
info, offers = client.get_product_details(2064068)
```

### Extract product ID from a URL

```python
pid = TweakersClient.product_id_from_url(
    "https://tweakers.net/pricewatch/2064068/kingston-fury-beast-kf560c30bbek2-32.html"
)
# -> 2064068
```

## How it works

No official API exists. This uses reverse-engineered endpoints:

| Endpoint | Auth | Returns |
|---|---|---|
| `/ajax/zoeken/pricewatch/?keyword=...` | None | Search results (JSON) |
| `/{category}/vergelijken/?page=...` | Session cookies | Category listing with pagination (HTML) |
| `/ajax/price_chart/{id}/{country}/` | None | Full price history (JSON) |
| `/pricewatch/{id}/` | Session cookies | Product page with JSON-LD + shop listings (HTML) |

The search and price history endpoints need zero authentication — they just work. Product and category pages need a session cookie which the client obtains automatically on init by following Tweakers' DPG Media consent redirect.

Category IDs are stored in `categories.json` (243 categories). To refresh:

```
python scripts/update_categories.py
```

## Limitations

- Search returns ~8 results max (it's the autocomplete/suggest endpoint, not full search — the real search page has reCAPTCHA). Use `browse_category()` to list products by category instead.
- Category browsing and shop offer parsing use regex on HTML, so they may break if Tweakers redesigns the page
- Price history only covers NL and BE
- Be nice with request frequency — there's no rate limiting implemented, so add your own delays if you're hitting it in a loop

## License

MIT
