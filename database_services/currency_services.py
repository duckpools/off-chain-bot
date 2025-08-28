import requests
import time
from typing import Dict, List
from database.db_manager import DatabaseManager

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"

# ── Add/maintain any hardcoded USD prices here ────────────────────────────────
# Keys are CoinGecko IDs; values are USD floats/ints.
HARD_CODED_PRICES: Dict[str, float] = {
    "spf": 0.0
}
# ─────────────────────────────────────────────────────────────────────────────


def fetch_usd_prices(asset_ids: list):
    """Fetch USD prices from CoinGecko API."""
    if not asset_ids:
        return {}

    ids_param = ','.join(set(asset_ids))
    url = f"{COINGECKO_BASE_URL}/simple/price"
    params = {'ids': ids_param, 'vs_currencies': 'usd'}

    for attempt in range(3):
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            prices = {}
            for asset_id, price_data in data.items():
                if 'usd' in price_data:
                    prices[asset_id] = price_data['usd']

            return prices

        except Exception as e:
            print(f"CoinGecko API error (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)

    return None


def sync_currency_rates(db: DatabaseManager, pools: List[dict]) -> Dict[str, str]:
    """Sync USD currency rates for all pooled assets.

    - Uses HARD_CODED_PRICES for any matching CoinGecko IDs
    - Fetches remaining prices from CoinGecko
    - Hardcoded values override API values
    - Upserts by each pool's 'CURRENCY_ID'
    - Returns a per-CURRENCY_ID status dict
    """
    print("Starting USD currency rates sync...")

    # Collect distinct CoinGecko IDs
    coingecko_ids: List[str] = []
    for pool in pools:
        cg = pool.get("coingecko")
        if cg and cg not in coingecko_ids:
            coingecko_ids.append(cg)

    if not coingecko_ids:
        print("No coingecko fields found in pools")
        return {}

    print(f"Found coingecko IDs: {coingecko_ids}")

    # Split into hardcoded vs to-fetch
    hardcoded_ids = [cg for cg in coingecko_ids if cg in HARD_CODED_PRICES]
    to_fetch_ids = [cg for cg in coingecko_ids if cg not in HARD_CODED_PRICES]

    if hardcoded_ids:
        print(f"Using hardcoded prices for: {hardcoded_ids}")

    # Fetch remaining from API, only if needed
    api_prices: Dict[str, float] = {}
    if to_fetch_ids:
        print(f"Fetching USD prices for: {to_fetch_ids}")
        api_prices = fetch_usd_prices(to_fetch_ids) or {}
        if not api_prices and to_fetch_ids:
            print("Failed to fetch some/all prices from CoinGecko (non-hardcoded)")

    # Merge with hardcoded overriding API  # CHANGED: ensure hardcoded has precedence
    prices: Dict[str, float] = {}
    prices.update(api_prices)
    for cg in hardcoded_ids:
        prices[cg] = HARD_CODED_PRICES[cg]

    # If nothing at all, report failures for pools that had coingecko + currency IDs
    if not prices:
        results = {}
        for pool in pools:
            currency_id = pool.get("CURRENCY_ID_DB")
            cg = pool.get("coingecko")
            if cg and currency_id:
                results[currency_id] = 'failed'
        print("No prices resolved (hardcoded or API).")
        return results

    results: Dict[str, str] = {}

    # Process each pool individually
    for pool in pools:
        currency_id = pool.get("CURRENCY_ID_DB")
        coingecko_id = pool.get("coingecko")

        # Validate required fields
        if not currency_id:
            print("Skipping pool with missing CURRENCY_ID")
            continue
        if not coingecko_id:
            print(f"Skipping {currency_id} - missing CoinGecko ID")
            results[currency_id] = 'skipped'
            continue

        try:
            usd_price = prices.get(coingecko_id)

            # CHANGED: allow 0.0 as a valid price (only reject None or negative)
            if usd_price is None or usd_price < 0:
                print(f"Skipping {currency_id} (cg:{coingecko_id}) - no valid price")
                results[currency_id] = 'skipped'
                continue

            # Upsert by CURRENCY_ID
            success = db.upsert_currency_rate(currency_id, float(usd_price))

            # CHANGED: source detection—hardcoded overrides API, so report correctly
            src = "hardcoded" if coingecko_id in HARD_CODED_PRICES else "api"
            if success:
                print(f"✓ Updated {currency_id} (cg:{coingecko_id}, {src}): ${float(usd_price):.6f}")
                results[currency_id] = 'success'
            else:
                print(f"✗ Failed to save {currency_id} (cg:{coingecko_id}, {src})")
                results[currency_id] = 'failed'

        except Exception as e:
            print(f"✗ Error processing {currency_id} (cg:{coingecko_id}): {e}")
            results[currency_id] = 'failed'

    # Summary
    success_count = sum(1 for r in results.values() if r == 'success')
    print(f"Currency sync complete: {success_count} successful")

    return results


def sync_currency_rates_batched(db: DatabaseManager, pools):
    """
    Sync USD currency rates using batch processing.
    """
    print("Starting batch currency rates sync...")

    # Collect distinct CoinGecko IDs
    coingecko_ids = []
    for pool in pools:
        cg = pool.get("coingecko")
        if cg and cg not in coingecko_ids:
            coingecko_ids.append(cg)

    if not coingecko_ids:
        print("No coingecko fields found in pools")
        return {}

    print(f"Found coingecko IDs: {coingecko_ids}")

    # Split into hardcoded vs to-fetch
    hardcoded_ids = [cg for cg in coingecko_ids if cg in HARD_CODED_PRICES]
    to_fetch_ids = [cg for cg in coingecko_ids if cg not in HARD_CODED_PRICES]

    if hardcoded_ids:
        print(f"Using hardcoded prices for: {hardcoded_ids}")

    # Fetch remaining from API
    api_prices = {}
    if to_fetch_ids:
        print(f"Fetching USD prices for: {to_fetch_ids}")
        api_prices = fetch_usd_prices(to_fetch_ids) or {}

    # Merge prices
    prices = {}
    prices.update(api_prices)
    for cg in hardcoded_ids:
        prices[cg] = HARD_CODED_PRICES[cg]

    if not prices:
        print("No prices resolved")
        return {}

    # Prepare batch data
    batch_data = []
    results = {}

    for pool in pools:
        currency_id = pool.get("CURRENCY_ID_DB")
        coingecko_id = pool.get("coingecko")

        if not currency_id or not coingecko_id:
            continue

        usd_price = prices.get(coingecko_id)

        if usd_price is None or usd_price < 0:
            results[currency_id] = 'skipped'
            continue

        batch_data.append((currency_id, float(usd_price)))
        results[currency_id] = 'pending'

    # Batch upsert all currency rates
    if batch_data:
        success_count = db.batch_upsert_currency_rates(batch_data)
        print(f"Successfully updated {success_count}/{len(batch_data)} currency rates")

        # Update results
        for currency_id, _ in batch_data[:success_count]:
            results[currency_id] = 'success'

    return results
