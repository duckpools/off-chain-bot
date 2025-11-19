import time
import requests
from typing import Optional, Dict
from database.db_manager import DatabaseManager
from current_pools import current_pools


def calculate_all_time_volume(db: DatabaseManager) -> float:
    """
    Calculate all-time volume across all pools by summing all transaction amounts
    and converting them to USD.

    Args:
        db: Database manager instance

    Returns:
        Total all-time volume in USD
    """
    try:
        # Get all transactions from database
        query = """
            SELECT t.pool_nft, t.amount, p.pooled_asset
            FROM transactions t
            JOIN pools p ON t.pool_nft = p.nft
        """
        transactions = db.execute_query(query)

        if not transactions:
            print("No transactions found for volume calculation")
            return 0.0

        # Group transactions by pool and sum amounts
        pool_volumes: Dict[str, float] = {}
        pool_assets: Dict[str, str] = {}

        for tx in transactions:
            pool_nft = tx['pool_nft']
            amount = float(tx['amount'])
            pooled_asset = tx['pooled_asset']

            if pool_nft not in pool_volumes:
                pool_volumes[pool_nft] = 0.0
                pool_assets[pool_nft] = pooled_asset

            pool_volumes[pool_nft] += amount

        # Create a mapping of pool NFT to pool config for quick lookup
        pool_config_map = {pool.get('POOL_NFT'): pool for pool in current_pools if 'POOL_NFT' in pool}

        # Print amounts for each pool (already in friendly format from DB)
        print("\n=== Pool Transaction Sums ===")
        for pool_nft, amount in pool_volumes.items():
            pooled_asset = pool_assets.get(pool_nft, "unknown")
            print(f"Pool {pool_nft[:16]}... ({pooled_asset}): {amount:,.2f} units")
        print("=" * 50 + "\n")

        # Convert to USD and sum
        total_volume_usd = 0.0

        for pool_nft, total_amount in pool_volumes.items():
            # Get latest USD rate for this asset
            pooled_asset = pool_assets[pool_nft]
            rate_query = """
                SELECT usd_rate
                FROM currency_rates
                WHERE pooled_asset = %s
                ORDER BY timestamp DESC
                LIMIT 1
            """
            rate_result = db.execute_query(rate_query, (pooled_asset,))

            if rate_result and len(rate_result) > 0:
                usd_rate = float(rate_result[0]['usd_rate'])
                volume_usd = total_amount * usd_rate
                total_volume_usd += volume_usd
            else:
                print(f"Warning: No USD rate found for {pooled_asset}, skipping pool {pool_nft}")

        return total_volume_usd

    except Exception as e:
        print(f"Error calculating all-time volume: {e}")
        return 0.0


def get_total_value_locked() -> float:
    """
    Get total value locked from DefiLlama API.

    Returns:
        Total value locked in USD, or 0.0 if failed
    """
    url = "https://api.llama.fi/tvl/duckpools"

    # Retry logic with exponential backoff
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            tvl = float(response.text)
            return tvl
        except Exception as e:
            print(f"DefiLlama API error (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s

    print("Failed to fetch TVL from DefiLlama after 3 attempts")
    return 0.0


def get_quacks_holders() -> int:
    """
    Get number of QUACKS token holders by counting unique addresses
    holding the QUACKS token from the Ergo blockchain.

    Returns:
        Number of unique holders, or 0 if failed
    """
    token_id = "089990451bb430f05a85f4ef3bcb6ebf852b3d6ee68d86d78658b9ccef20074f"
    base_url = f"https://api.ergoplatform.com/api/v1/boxes/unspent/byTokenId/{token_id}"

    unique_addresses = set()
    limit = 100  # Number of items per request (API maximum)
    offset = 0

    try:
        while True:
            # Make API request with pagination
            params = {"limit": limit, "offset": offset}

            for attempt in range(3):
                try:
                    response = requests.get(base_url, params=params, timeout=30)
                    response.raise_for_status()
                    data = response.json()
                    break
                except Exception as e:
                    print(f"Ergo API error (attempt {attempt + 1}/3): {e}")
                    if attempt < 2:
                        time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s
                    else:
                        print(f"Failed to fetch QUACKS holders after 3 attempts")
                        return 0

            items = data.get('items', [])

            # If no items returned, we've fetched all data
            if not items:
                break

            # Extract unique addresses from each box
            for item in items:
                address = item.get('address')
                if address:
                    unique_addresses.add(address)

            # Move to next page
            offset += limit

            # If we received fewer items than the limit, we're done
            if len(items) < limit:
                break

        holder_count = len(unique_addresses)
        print(f"Found {holder_count} unique QUACKS token holders")
        return holder_count

    except Exception as e:
        print(f"Error fetching QUACKS holders: {e}")
        return 0


def calculate_monthly_volume(db: DatabaseManager, current_all_time_volume: float) -> float:
    """
    Calculate monthly volume by comparing current all-time volume with volume from
    1 month ago (or oldest available entry).

    Args:
        db: Database manager instance
        current_all_time_volume: Current all-time volume

    Returns:
        Monthly volume in USD
    """
    try:
        # Calculate timestamp for 1 month ago (30 days)
        current_timestamp = int(time.time())
        one_month_ago = current_timestamp - (30 * 24 * 60 * 60)

        # Query for first entry at least 1 month old
        query = """
            SELECT all_time_volume, timestamp
            FROM headlinestats
            WHERE timestamp <= %s
            ORDER BY timestamp DESC
            LIMIT 1
        """
        result = db.execute_query(query, (one_month_ago,))

        if result and len(result) > 0:
            old_volume = float(result[0]['all_time_volume'])
            monthly_volume = current_all_time_volume - old_volume
            return max(0.0, monthly_volume)  # Ensure non-negative

        # If no entry at least 1 month old, try to get oldest entry
        oldest_query = """
            SELECT all_time_volume, timestamp
            FROM headlinestats
            ORDER BY timestamp ASC
            LIMIT 1
        """
        oldest_result = db.execute_query(oldest_query)

        if oldest_result and len(oldest_result) > 0:
            old_volume = float(oldest_result[0]['all_time_volume'])
            monthly_volume = current_all_time_volume - old_volume
            return max(0.0, monthly_volume)  # Ensure non-negative

        # No historical data available
        return 0.0

    except Exception as e:
        print(f"Error calculating monthly volume: {e}")
        return 0.0


def insert_headline_stats(db: DatabaseManager, sync_block: Optional[int] = None) -> Optional[int]:
    """
    Insert headline statistics into the database.

    Args:
        db: Database manager instance
        sync_block: Block height when this data was synced

    Returns:
        id of the inserted record if successful, None if failed
    """
    try:
        # Get current timestamp
        current_timestamp = int(time.time())

        # Calculate real metrics
        print("Calculating all-time volume...")
        all_time_volume = calculate_all_time_volume(db)

        print("Fetching total value locked from DefiLlama...")
        total_value_locked = get_total_value_locked()

        print("Getting QUACKS holders count...")
        quacks_holders = get_quacks_holders()

        print("Calculating monthly volume...")
        monthly_volume = calculate_monthly_volume(db, all_time_volume)

        print(f"Metrics calculated - Volume: ${all_time_volume:.2f}, TVL: ${total_value_locked:.2f}, Holders: {quacks_holders}, Monthly: ${monthly_volume:.2f}")

        result = db.insert_headlinestats(
            all_time_volume=all_time_volume,
            total_value_locked=total_value_locked,
            quacks_holders=quacks_holders,
            monthly_volume=monthly_volume,
            timestamp=current_timestamp,
            sync_block=sync_block
        )

        if result:
            print(f"Successfully inserted headline stats at timestamp {current_timestamp}")
        else:
            print("Failed to insert headline stats")

        return result

    except Exception as e:
        print(f"Error in insert_headline_stats: {e}")
        return None
