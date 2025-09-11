import time
from typing import Dict, Optional, Union, Any


def sync_user_analytics(db, sync_block):
    addresses = db.get_all_addresses()
    print("Addresses: ", addresses)
    for address in addresses:
        upa = calculate_user_pool_analytics(db,address)
        print(upa)
        upsert_user_pool_analytics(db, address, upa, sync_block)

def calculate_total_profits(db, address: str) -> Dict[str, Dict[str, Optional[float]]]:
    """
    Calculate 30-day, 90-day, and 365-day total profits for an address by pool.

    Args:
        db: Database instance with AnalyticsMixin methods
        address: The blockchain address to calculate profits for

    Returns:
        Dictionary with pool_nft as keys, each containing profit calculations:
        {
            'pool_nft_1': {
                '30d': float or None,
                '90d': float or None,
                '365d': float or None
            },
            'pool_nft_2': {
                '30d': float or None,
                '90d': float or None,
                '365d': float or None
            }
        }
        Returns None for periods where insufficient data exists.
    """
    try:
        # Get current timestamp in milliseconds
        current_timestamp_ms = int(time.time() * 1000)

        # Calculate timestamps for lookback periods (in milliseconds)
        # 1 day = 24 * 60 * 60 * 1000 = 86,400,000 ms
        ms_per_day = 86_400_000

        timestamp_30d = current_timestamp_ms - (30 * ms_per_day)
        timestamp_90d = current_timestamp_ms - (90 * ms_per_day)
        timestamp_365d = current_timestamp_ms - (365 * ms_per_day)

        # Get the latest snapshots by pool
        latest_snapshots = db.get_latest_snapshot(address)
        if not latest_snapshots:
            print(f"No latest snapshots found for address: {address}")
            return {}

        # Get historical snapshots by pool
        snapshots_30d = db.get_next_snapshot(address, timestamp_30d)
        snapshots_90d = db.get_next_snapshot(address, timestamp_90d)
        snapshots_365d = db.get_next_snapshot(address, timestamp_365d)

        # Calculate profits for each pool
        result = {}

        for pool_nft, latest_snapshot in latest_snapshots.items():
            latest_profit = latest_snapshot['total_profit']

            # Calculate profits for this pool
            profit_30d = None
            profit_90d = None
            profit_365d = None

            if pool_nft in snapshots_30d:
                profit_30d = latest_profit - snapshots_30d[pool_nft]['total_profit']

            if pool_nft in snapshots_90d:
                profit_90d = latest_profit - snapshots_90d[pool_nft]['total_profit']

            if pool_nft in snapshots_365d:
                profit_365d = latest_profit - snapshots_365d[pool_nft]['total_profit']

            result[pool_nft] = {
                '30d': profit_30d,
                '90d': profit_90d,
                '365d': profit_365d
            }

        return result

    except Exception as e:
        print(f"Error calculating total profits for address {address}: {e}")
        return {}


def calculate_user_pool_analytics(db, address: str) -> Dict[str, Dict[str, Any]]:
    """
    Calculate comprehensive analytics for each pool for an address.

    Args:
        db: Database instance with AnalyticsMixin methods
        address: The blockchain address to calculate analytics for

    Returns:
        Dictionary with pool_nft as keys containing analytics data for each pool
    """
    try:
        # Get profit calculations
        profits = calculate_total_profits(db, address)
        if not profits:
            return {}

        # Get current timestamp and historical timestamps
        current_timestamp_ms = int(time.time() * 1000)
        ms_per_day = 86_400_000

        timestamp_30d = current_timestamp_ms - (30 * ms_per_day)
        timestamp_90d = current_timestamp_ms - (90 * ms_per_day)
        timestamp_365d = current_timestamp_ms - (365 * ms_per_day)

        # Get latest snapshots (for current position values)
        latest_snapshots = db.get_latest_snapshot(address)

        # Get historical snapshots for starting position values
        snapshots_30d = db.get_next_snapshot(address, timestamp_30d)
        snapshots_90d = db.get_next_snapshot(address, timestamp_90d)
        snapshots_365d = db.get_next_snapshot(address, timestamp_365d)

        # Get currency rates and pool assets
        currency_rates = db.get_currency_rates()

        analytics = {}

        for pool_nft in latest_snapshots.keys():
            # Get pooled asset for this pool
            pooled_asset = db.get_pool_asset(pool_nft)
            usd_rate = currency_rates.get(pooled_asset, 0) if currency_rates and pooled_asset else 0

            # Get current lend APY for projected calculations
            current_lend_apy = db.get_pool_lend_apy(pool_nft)

            # Current position value
            current_position_value = float(latest_snapshots[pool_nft]['position_value'])

            # Historical position values (starting values for periods) - convert to float
            position_value_30d = float(snapshots_30d.get(pool_nft, {}).get('position_value', 0)) if snapshots_30d else 0
            position_value_90d = float(snapshots_90d.get(pool_nft, {}).get('position_value', 0)) if snapshots_90d else 0
            position_value_365d = float(
                snapshots_365d.get(pool_nft, {}).get('position_value', 0)) if snapshots_365d else 0

            # Profits - convert to float
            profit_30d = float(profits.get(pool_nft, {}).get('30d') or 0)
            profit_90d = float(profits.get(pool_nft, {}).get('90d') or 0)
            profit_365d = float(profits.get(pool_nft, {}).get('365d') or 0)

            # Calculate APYs (profit / starting_position_value)
            apy_30d = profit_30d / position_value_30d if position_value_30d > 0 else 0
            apy_90d = profit_90d / position_value_90d if position_value_90d > 0 else 0
            apy_365d = profit_365d / position_value_365d if position_value_365d > 0 else 0

            # Calculate projected 30-day earnings with compounding
            # Convert annual APY to 30-day: (1 + annual_apy)^(30/365) - 1
            if current_lend_apy > 0 and current_position_value > 0:
                projected_30d_multiplier = pow(1 + current_lend_apy, 30 / 365) - 1
                projected_earnt_30d = current_position_value * projected_30d_multiplier
                projected_earnt_30d_usd = projected_earnt_30d * usd_rate
            else:
                projected_earnt_30d = 0
                projected_earnt_30d_usd = 0

            analytics[pool_nft] = {
                'total_earnt_30d': profit_30d,
                'total_earnt_30d_usd': profit_30d * usd_rate,
                'apy_earnt_30d': apy_30d,
                'position_value_30d': position_value_30d,
                'total_earnt_90d': profit_90d,
                'total_earnt_90d_usd': profit_90d * usd_rate,
                'apy_earnt_90d': apy_90d,
                'position_value_90d': position_value_90d,
                'total_earnt_365d': profit_365d,
                'total_earnt_365d_usd': profit_365d * usd_rate,
                'apy_earnt_365d': apy_365d,
                'position_value_365d': position_value_365d,
                'projected_earnt_30d': projected_earnt_30d,
                'projected_earnt_30d_usd': projected_earnt_30d_usd,
                'projected_apy_30d': current_lend_apy * 100
            }

        return analytics

    except Exception as e:
        print(f"Error calculating user pool analytics for address {address}: {e}")
        return {}

def upsert_user_pool_analytics(db, address: str, analytics_data: Dict[str, Dict[str, Any]],
                               sync_block: int = None) -> bool:
    """
    Upsert user pool analytics data for an address.

    Args:
        db: Database instance with AnalyticsMixin methods
        address: The blockchain address
        analytics_data: Dictionary with pool_nft as keys containing analytics data
        sync_block: Current sync block number

    Returns:
        True if successful, False otherwise
    """
    try:
        # Get address_id
        address_id = db.get_address_id(address)
        if not address_id:
            print(f"Address not found: {address}")
            return False

        for pool_nft, data in analytics_data.items():
            query = """
                INSERT INTO user_pool_analytics (
                    address_id, pool_nft, total_earnt_30d, total_earnt_30d_usd, apy_earnt_30d, position_value_30d,
                    total_earnt_90d, total_earnt_90d_usd, apy_earnt_90d, position_value_90d,
                    total_earnt_365d, total_earnt_365d_usd, apy_earnt_365d, position_value_365d,
                    projected_earnt_30d, projected_earnt_30d_usd, projected_apy_30d, sync_block, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP
                )
                ON CONFLICT (address_id, pool_nft) 
                DO UPDATE SET
                    total_earnt_30d = EXCLUDED.total_earnt_30d,
                    total_earnt_30d_usd = EXCLUDED.total_earnt_30d_usd,
                    apy_earnt_30d = EXCLUDED.apy_earnt_30d,
                    position_value_30d = EXCLUDED.position_value_30d,
                    total_earnt_90d = EXCLUDED.total_earnt_90d,
                    total_earnt_90d_usd = EXCLUDED.total_earnt_90d_usd,
                    apy_earnt_90d = EXCLUDED.apy_earnt_90d,
                    position_value_90d = EXCLUDED.position_value_90d,
                    total_earnt_365d = EXCLUDED.total_earnt_365d,
                    total_earnt_365d_usd = EXCLUDED.total_earnt_365d_usd,
                    apy_earnt_365d = EXCLUDED.apy_earnt_365d,
                    position_value_365d = EXCLUDED.position_value_365d,
                    projected_earnt_30d = EXCLUDED.projected_earnt_30d,
                    projected_earnt_30d_usd = EXCLUDED.projected_earnt_30d_usd,
                    projected_apy_30d = EXCLUDED.projected_apy_30d,
                    sync_block = EXCLUDED.sync_block,
                    updated_at = CURRENT_TIMESTAMP;
            """

            params = (
                address_id, pool_nft,
                data['total_earnt_30d'], data['total_earnt_30d_usd'], data['apy_earnt_30d'], data['position_value_30d'],
                data['total_earnt_90d'], data['total_earnt_90d_usd'], data['apy_earnt_90d'], data['position_value_90d'],
                data['total_earnt_365d'], data['total_earnt_365d_usd'], data['apy_earnt_365d'],
                data['position_value_365d'],
                data['projected_earnt_30d'], data['projected_earnt_30d_usd'], data['projected_apy_30d'],
                sync_block
            )

            # Use execute_upsert instead of execute_query
            db.execute_upsert(query, params)

        return True

    except Exception as e:
        print(f"Error upserting user pool analytics for address {address}: {e}")
        return False