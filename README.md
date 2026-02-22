# tweakers-pricewatch

Unofficial Python client for [Tweakers.net](https://tweakers.net) Pricewatch — the biggest price comparison site in the Netherlands.

Lets you search products, pull current shop prices, and grab full price history (years of daily min/avg data). All from reverse-engineered endpoints, no API key needed.

## Install

Just `requests` as a dependency. Copy `tweakers.py` into your project, or:

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

Works great with exact model numbers too:

```python
results = client.search("F4-3600C16D-32GTZN")
# -> G.Skill Trident Z Neo F4-3600C16D-32GTZN [ID: 1456176]
```

### Price history

The good stuff — daily min and average prices going back years:

```python
history = client.get_price_history(1456176)

print(f"{len(history.prices)} days of data")
print(f"Lowest ever: EUR {history.lowest_ever} ({history.lowest_ever_date})")
print(f"Last known:  EUR {history.last_price} ({history.last_price_date})")

# individual data points
for p in history.prices[-5:]:
    print(f"  {p.date}  min=EUR {p.min_price}  avg=EUR {p.avg_price}")
```

Belgium prices are available too:

```python
history_be = client.get_price_history(1456176, country="be")
```

### Product info

Structured data pulled from the page's JSON-LD:

```python
info = client.get_product_info(1456176)
print(f"{info.brand} {info.name}")
print(f"MPN: {info.mpn}")        # ['F4-3600C16D-32GTZN']
print(f"EAN: {info.gtin}")        # ['4713294223425']
print(f"EUR {info.low_price} - {info.high_price} ({info.offer_count} shops)")
```

### Current shop prices

```python
offers = client.get_current_prices(2064068)
for o in offers:
    print(f"  {o.shop_name}: EUR {o.price} (product {o.product_price} + shipping {o.shipping_cost})")
```

Returns an empty list for discontinued products (no shops carrying it anymore).

### Combo: info + prices in one request

```python
info, offers = client.get_product_details(2064068)
```

Saves an HTTP call vs calling both separately.

### Extract product ID from a URL

```python
pid = TweakersClient.product_id_from_url(
    "https://tweakers.net/pricewatch/1456176/g-punt-skill-trident-z-neo.html"
)
# -> 1456176
```

## How it works

No official API exists. This uses three undocumented endpoints:

| Endpoint | Auth | Returns |
|---|---|---|
| `/ajax/zoeken/pricewatch/?keyword=...` | None | Search results (JSON) |
| `/ajax/price_chart/{id}/{country}/` | None | Full price history (JSON) |
| `/pricewatch/{id}/` | Session cookies | Product page with JSON-LD + shop listings (HTML) |

The search and price history endpoints need zero authentication — they just work. Product pages need a session cookie which the client obtains automatically on init by following Tweakers' DPG Media consent redirect.

## Limitations

- Search returns ~8 results max (it's the autocomplete/suggest endpoint, not full search — the real search page has reCAPTCHA)
- Shop offer parsing uses regex on HTML, so it may break if Tweakers redesigns the page
- Price history only covers NL and BE
- Be nice with request frequency — there's no rate limiting implemented, so add your own delays if you're hitting it in a loop

## License

MIT
