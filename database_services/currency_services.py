import requests
import time
from typing import Dict, List, Optional
from database.db_manager import DatabaseManager

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"


def get_price_from_dex(pool: dict, db, currency_id: str) -> Optional[float]:
    print("CALLLING HERE")
    """
    Get price from DEX by calculating the ratio of ERG value to token amount.

    Args:
        pool: Pool configuration containing DEX information
        db: Database manager instance to fetch ERG native price
        currency_id: The currency ID to get price for

    Returns:
        USD price from DEX, or None if unavailable
    """
    from helpers.platform_functions import get_dex_box

    try:
        # Get the DEX NFT from pool configuration
        # For token pools, the collateral is ERG, so we get the dex_nft from there
        dex_nft = None
        collateral_supported = pool.get("collateral_supported", {})

        # Try to find the dex_nft in collateral_supported
        for collateral_type, collateral_info in collateral_supported.items():
            if isinstance(collateral_info, dict) and "dex_nft" in collateral_info:
                dex_nft = collateral_info["dex_nft"]
                break

        if not dex_nft:
            print(f"No DEX NFT found for {currency_id}")
            return None

        # Fetch the DEX box
        dex_box = get_dex_box(dex_nft)
        if not dex_box:
            print(f"Could not fetch DEX box for {currency_id}")
            return None

        # Extract ERG value (in nanoERG) and token amount
        erg_value = float(dex_box["value"])  # ERG in nanoERG (9 decimals)

        # The token is in assets[2] (assets[0] is NFT, assets[1] is LP tokens)
        if len(dex_box["assets"]) < 3:
            print(f"DEX box does not have expected asset structure for {currency_id}")
            return None

        token_amount = float(dex_box["assets"][2]["amount"])

        # Get token decimals from pool config
        token_decimals = pool.get("decimals", 0)
        erg_decimals = 9

        # Calculate price in ERG (accounting for decimals)
        # price_in_erg = (erg_value / 10^9) / (token_amount / 10^token_decimals)
        # Simplified: price_in_erg = (erg_value * 10^token_decimals) / (token_amount * 10^9)
        price_in_erg = (erg_value * (10 ** token_decimals)) / (token_amount * (10 ** erg_decimals))

        # Get ERG native price in USD from database
        currency_rates = db.get_currency_rates()
        erg_usd_price = currency_rates.get("erg...native")

        if erg_usd_price is None:
            print(f"Could not fetch ERG native price from database")
            return None

        # Calculate USD price
        usd_price = price_in_erg * erg_usd_price

        print(f"Calculated DEX price for {currency_id}: ${usd_price:.6f} (ERG price: ${erg_usd_price:.6f}, ratio: {price_in_erg:.6f} ERG)")
        return usd_price

    except Exception as e:
        print(f"Error getting price from DEX for {currency_id}: {e}")
        return None


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


def sync_currency_rates(db: DatabaseManager, pools: List[dict], sync_block: Optional[int] = None, min_height: int = 0,
                        sync_dex_pools: bool = True) -> Dict[str, str]:
    """Sync USD currency rates for all pooled assets (latest only).

    - Fetches prices from CoinGecko API
    - Only inserts new rate if >= 5 minutes since last timestamp
    - Returns a per-CURRENCY_ID status dict

    Args:
        db: Database manager instance
        pools: List of pool configurations
        sync_block: Block height when this sync was performed
        min_height: Minimum block height
        sync_dex_pools: Whether to sync DEX pool prices (default: True)
    """
    print("Starting USD currency rates sync (latest only)...")

    current_timestamp = int(time.time())
    assets_to_skip = set()

    # Check which assets need updates based on 5-minute threshold
    try:
        for pool in pools:
            currency_id = pool.get("CURRENCY_ID_DB")
            if not currency_id:
                continue

            latest_timestamp = db.get_latest_currency_timestamp(currency_id)
            if latest_timestamp:
                time_diff = current_timestamp - latest_timestamp
                if time_diff < 300:  # Less than 5 minutes (300 seconds)
                    assets_to_skip.add(currency_id)
                    print(f"Skipping {currency_id}: Last update was {time_diff}s ago (< 5 min)")
    except Exception as e:
        print(f"Error checking recent currency updates: {e}")

    # Collect distinct CoinGecko IDs (excluding recently synced ones and DEX-priced assets)
    coingecko_ids: List[str] = []
    pools_to_process = []
    for pool in pools:
        currency_id = pool.get("CURRENCY_ID_DB")
        if currency_id in assets_to_skip:
            continue

        # Skip DEX-priced pools if DEX syncing is disabled
        if pool.get("get_price_from_dex") and not sync_dex_pools:
            print(f"Skipping DEX pool {currency_id}: DEX syncing not scheduled this loop")
            continue

        pools_to_process.append(pool)

        # Skip CoinGecko collection if this pool uses DEX pricing
        if pool.get("get_price_from_dex"):
            continue

        cg = pool.get("coingecko")
        if cg and cg not in coingecko_ids:
            coingecko_ids.append(cg)
        cg = pool.get("coingecko")
        if cg and cg not in coingecko_ids:
            coingecko_ids.append(cg)

    if not coingecko_ids:
        print("No coingecko fields found in pools (or all recently synced)")
        # Return skipped status for recently synced assets
        results = {}
        for pool in pools:
            currency_id = pool.get("CURRENCY_ID_DB")
            if currency_id in assets_to_skip:
                results[currency_id] = 'skipped_recent'
        return results

    print(f"Found coingecko IDs: {coingecko_ids}")

    # Fetch prices from API
    print(f"Fetching USD prices for: {coingecko_ids}")
    prices: Dict[str, float] = fetch_usd_prices(coingecko_ids) or {}
    if not prices:
        print("Failed to fetch prices from CoinGecko")

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

    # Process each pool individually (only those not recently synced)
    for pool in pools_to_process:
        currency_id = pool.get("CURRENCY_ID_DB")
        coingecko_id = pool.get("coingecko")

        # Validate required fields
        if not currency_id:
            print("Skipping pool with missing CURRENCY_ID")
            continue

        try:
            # Check if this pool should use DEX pricing instead of CoinGecko
            if pool.get("get_price_from_dex"):
                usd_price = get_price_from_dex(pool, db, currency_id)
                source = "DEX"
            else:
                if not coingecko_id:
                    print(f"Skipping {currency_id} - missing CoinGecko ID")
                    results[currency_id] = 'skipped'
                    continue
                usd_price = prices.get(coingecko_id)
                source = f"cg:{coingecko_id}"

            # CHANGED: allow 0.0 as a valid price (only reject None or negative)
            if usd_price is None or usd_price < 0:
                print(f"Skipping {currency_id} ({source}) - no valid price")
                results[currency_id] = 'skipped'
                continue

            # Insert new rate with timestamp
            success = db.insert_currency_rate(currency_id, float(usd_price), current_timestamp, sync_block)

            if success:
                print(f"✓ Updated {currency_id} ({source}): ${float(usd_price):.6f}")
                results[currency_id] = 'success'
            else:
                print(f"✗ Failed to save {currency_id} ({source})")
                results[currency_id] = 'failed'

        except Exception as e:
            print(f"✗ Error processing {currency_id} ({source}): {e}")
            results[currency_id] = 'failed'

    # Summary
    success_count = sum(1 for r in results.values() if r == 'success')
    print(f"Currency sync complete: {success_count} successful")

    return results


def sync_currency_rates_batched(db: DatabaseManager, pools, sync_block: Optional[int] = None,
                                sync_dex_pools: bool = True):
    """
    Sync USD currency rates using batch processing (latest only with 5-minute check).

    Args:
        db: Database manager instance
        pools: List of pool configurations
        sync_block: Block height when this sync was performed
        sync_dex_pools: Whether to sync DEX pool prices (default: True)
    """
    print("Starting batch currency rates sync (latest only)...")

    current_timestamp = int(time.time())
    assets_to_skip = set()

    # Check which assets need updates based on 5-minute threshold
    try:
        for pool in pools:
            currency_id = pool.get("CURRENCY_ID_DB")
            if not currency_id:
                continue

            latest_timestamp = db.get_latest_currency_timestamp(currency_id)
            if latest_timestamp:
                time_diff = current_timestamp - latest_timestamp
                if time_diff < 300:  # Less than 5 minutes (300 seconds)
                    assets_to_skip.add(currency_id)
                    print(f"Skipping {currency_id}: Last update was {time_diff}s ago (< 5 min)")
    except Exception as e:
        print(f"Error checking recent currency updates: {e}")

    # Collect distinct CoinGecko IDs (excluding recently synced and DEX-priced assets)
    coingecko_ids = []
    pools_to_process = []
    for pool in pools:
        currency_id = pool.get("CURRENCY_ID_DB")
        if currency_id in assets_to_skip:
            continue

        # Skip DEX-priced pools if DEX syncing is disabled
        if pool.get("get_price_from_dex") and not sync_dex_pools:
            print(f"Skipping DEX pool {currency_id}: DEX syncing not scheduled this loop")
            continue

        pools_to_process.append(pool)

        # Skip CoinGecko collection if this pool uses DEX pricing
        if pool.get("get_price_from_dex"):
            continue

        cg = pool.get("coingecko")
        if cg and cg not in coingecko_ids:
            coingecko_ids.append(cg)

    if not coingecko_ids:
        print("No coingecko fields found in pools (or all recently synced)")
        results = {}
        for pool in pools:
            currency_id = pool.get("CURRENCY_ID_DB")
            if currency_id in assets_to_skip:
                results[currency_id] = 'skipped_recent'
        return results

    print(f"Found coingecko IDs: {coingecko_ids}")

    # Fetch prices from API
    print(f"Fetching USD prices for: {coingecko_ids}")
    prices = fetch_usd_prices(coingecko_ids) or {}

    if not prices:
        print("No prices resolved")
        return {}

    # Prepare batch data with timestamp
    batch_data = []
    results = {}

    for pool in pools_to_process:
        currency_id = pool.get("CURRENCY_ID_DB")
        coingecko_id = pool.get("coingecko")

        if not currency_id:
            continue

        # Check if this pool should use DEX pricing instead of CoinGecko
        if pool.get("get_price_from_dex"):
            usd_price = get_price_from_dex(pool, db, currency_id)
        else:
            if not coingecko_id:
                continue
            usd_price = prices.get(coingecko_id)

        if usd_price is None or usd_price < 0:
            results[currency_id] = 'skipped'
            continue

        batch_data.append((currency_id, float(usd_price), current_timestamp, sync_block))
        results[currency_id] = 'pending'

    # Batch insert all currency rates
    if batch_data:
        success_count = db.batch_insert_currency_rates(batch_data, sync_block)
        print(f"Successfully inserted {success_count}/{len(batch_data)} currency rates")

        # Update results
        for i, (currency_id, _, _, _) in enumerate(batch_data):
            if i < success_count:
                results[currency_id] = 'success'
            else:
                results[currency_id] = 'failed'

    # Add skipped assets to results
    for currency_id in assets_to_skip:
        results[currency_id] = 'skipped_recent'

    return results


def fetch_historical_prices(coingecko_id: str, from_timestamp: int, to_timestamp: int) -> Dict[int, float]:
    """
    Fetch historical USD prices from CoinGecko API.

    Args:
        coingecko_id: CoinGecko asset ID
        from_timestamp: Start Unix timestamp
        to_timestamp: End Unix timestamp

    Returns:
        Dictionary mapping Unix timestamps to USD prices
    """
    url = f"{COINGECKO_BASE_URL}/coins/{coingecko_id}/market_chart/range"
    params = {
        'vs_currency': 'usd',
        'from': from_timestamp,
        'to': to_timestamp
    }

    for attempt in range(3):
        try:
            response = requests.get(url, params=params, timeout=60)
            response.raise_for_status()

            data = response.json()
            prices = {}

            # CoinGecko returns prices as [[timestamp_ms, price], ...]
            if 'prices' in data:
                for timestamp_ms, price in data['prices']:
                    timestamp = int(timestamp_ms / 1000)  # Convert to seconds
                    prices[timestamp] = price

            return prices

        except Exception as e:
            print(f"CoinGecko historical API error for {coingecko_id} (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)

    return {}


def sync_currency_all_time(db: DatabaseManager, pools: List[dict], from_timestamp: int = None, sync_block: Optional[int] = None) -> Dict[str, int]:
    """
    Sync historical currency rates from inception (or specified timestamp).

    This function fetches and stores historical price data for all assets.
    Use this for initial backfill or to fill gaps in historical data.

    Args:
        db: Database manager instance
        pools: List of pool configurations
        from_timestamp: Start timestamp (default: 1 year ago)
        sync_block: Block height when this sync was performed

    Returns:
        Dictionary mapping currency_id to number of records inserted
    """
    print("Starting historical currency rates sync (all time)...")

    # Default to 1 year ago if not specified
    if from_timestamp is None:
        from_timestamp = int(time.time()) - (365 * 24 * 60 * 60)

    to_timestamp = int(time.time())

    print(f"Fetching historical data from {from_timestamp} to {to_timestamp}")

    results = {}

    # Process each pool
    for pool in pools:
        currency_id = pool.get("CURRENCY_ID_DB")
        coingecko_id = pool.get("coingecko")

        if not currency_id or not coingecko_id:
            print(f"Skipping pool - missing CURRENCY_ID_DB or coingecko")
            continue

        print(f"Fetching historical prices for {currency_id} (cg:{coingecko_id})...")

        historical_prices = fetch_historical_prices(coingecko_id, from_timestamp, to_timestamp)

        if not historical_prices:
            print(f"No historical prices found for {currency_id}")
            results[currency_id] = 0
            continue

        # Prepare batch data
        batch_data = []
        for timestamp, price in historical_prices.items():
            batch_data.append((currency_id, float(price), timestamp, sync_block))

        # Insert in batches
        if batch_data:
            inserted_count = db.batch_insert_currency_rates(batch_data, sync_block)
            results[currency_id] = inserted_count
            print(f"✓ Inserted {inserted_count} historical rates for {currency_id}")

            # Rate limit: CoinGecko free tier allows ~10-50 calls/minute
            time.sleep(2)  # Wait 2 seconds between assets

    # Summary
    total_inserted = sum(results.values())
    print(f"\nHistorical currency sync complete: {total_inserted} total records inserted")

    return results