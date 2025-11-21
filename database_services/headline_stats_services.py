import time
import requests
from typing import Optional, Dict
from database.db_manager import DatabaseManager
from current_pools import current_pools


def calculate_all_time_volume(db: DatabaseManager) -> Dict[str, float]:
    """
    Calculate all-time volume across all pools by summing all transaction amounts
    grouped by pooled asset.

    Args:
        db: Database manager instance

    Returns:
        Dictionary mapping pooled_asset to total volume (e.g., {"ERG": 12345.67, "SigUSD": 98765.43})
    """
    try:
        # Get all transactions from database
        query = """
            SELECT t.amount, p.pooled_asset
            FROM transactions t
            JOIN pools p ON t.pool_nft = p.nft
        """
        transactions = db.execute_query(query)

        if not transactions:
            print("No transactions found for volume calculation")
            return {}

        # Group transactions by pooled_asset and sum amounts
        asset_volumes: Dict[str, float] = {}

        for tx in transactions:
            amount = float(tx['amount'])
            pooled_asset = tx['pooled_asset']

            if pooled_asset not in asset_volumes:
                asset_volumes[pooled_asset] = 0.0

            asset_volumes[pooled_asset] += amount

        # Print amounts for each asset
        print("\n=== All-Time Volume by Asset ===")
        for pooled_asset, amount in asset_volumes.items():
            print(f"{pooled_asset}: {amount:,.2f} units")
        print("=" * 50 + "\n")

        return asset_volumes

    except Exception as e:
        print(f"Error calculating all-time volume: {e}")
        return {}


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
        print("Calculating all-time volume by asset...")
        all_time_volume_by_asset = calculate_all_time_volume(db)

        print("Fetching total value locked from DefiLlama...")
        total_value_locked = get_total_value_locked()

        print("Getting QUACKS holders count...")
        quacks_holders = get_quacks_holders()

        print(f"Metrics calculated - TVL: ${total_value_locked:.2f}, Holders: {quacks_holders}")

        result = db.insert_headlinestats(
            all_time_volume_by_asset=all_time_volume_by_asset,
            total_value_locked=total_value_locked,
            quacks_holders=quacks_holders,
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
