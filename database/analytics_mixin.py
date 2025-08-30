from typing import Optional, List, Tuple, Dict
import time
from decimal import Decimal
import math

from current_pools import current_pools


class AnalyticsMixin:
    def sync_user_pool_analytics(self, days_lookback: int = 400) -> int:
        """
        Sync user pool analytics by calculating earnings and APY metrics.

        Args:
            days_lookback: How many days back to look for historical data (default 400 to ensure we capture 365d)

        Returns:
            Number of analytics records successfully processed
        """
        successful_updates = 0
        # Convert to milliseconds
        current_timestamp = int(time.time() * 1000)

        try:
            # Get pools data for decimals and lend_apy
            pools_data = self._get_pools_data()
            if not pools_data:
                print("No pools data available")
                return 0

            # Get currency rates
            currency_rates = self._get_currency_rates()

            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # Get all unique address_id, pool_nft combinations from portfolio snapshots
                    cur.execute("""
                        SELECT DISTINCT address_id, pool_nft
                        FROM user_portfolio_snapshots
                        ORDER BY address_id, pool_nft
                    """)

                    combinations = cur.fetchall()

                    for address_id, pool_nft in combinations:
                        try:
                            analytics_data = self._calculate_analytics_for_user_pool(
                                cur, address_id, pool_nft, current_timestamp,
                                days_lookback, pools_data, currency_rates
                            )

                            if analytics_data:
                                # Upsert the analytics data
                                success = self._upsert_user_pool_analytics(cur, address_id, pool_nft, analytics_data)
                                if success:
                                    successful_updates += 1
                        except Exception as e:
                            print(f"Error processing analytics for address_id {address_id}, pool {pool_nft}: {e}")
                            continue

                    conn.commit()

        except Exception as e:
            print(f"Error in sync_user_pool_analytics: {e}")

        return successful_updates

    def _get_pools_data(self) -> Dict[str, Dict]:
        """Get pools data including decimals and lend_apy"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT nft, pooled_asset, lend_apy
                        FROM pools
                    """)

                    pools = {}
                    for nft, pooled_asset, lend_apy in cur.fetchall():
                        # Get decimals from the current_pools data
                        decimals = self._get_decimals_for_pool(nft)
                        pools[nft] = {
                            'pooled_asset': pooled_asset,
                            'lend_apy': float(lend_apy) if lend_apy else 0,
                            'decimals': decimals
                        }

                    return pools
        except Exception as e:
            print(f"Error getting pools data: {e}")
            return {}

    def _get_decimals_for_pool(self, pool_nft: str) -> int:
        """Get decimals for a pool from the current_pools data"""
        for pool in current_pools:
            if pool.get('POOL_NFT') == pool_nft:
                return pool.get('decimals', 0)
        return 0

    def _get_currency_rates(self) -> Dict[str, float]:
        """Get latest currency rates"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT pooled_asset, usd_rate
                        FROM currency_rates
                        ORDER BY updated_at DESC
                    """)

                    return {asset: float(rate) for asset, rate in cur.fetchall()}
        except Exception as e:
            print(f"Error getting currency rates: {e}")
            return {}

    def _calculate_analytics_for_user_pool(self, cur, address_id: int, pool_nft: str,
                                           current_timestamp: int, days_lookback: int,
                                           pools_data: Dict, currency_rates: Dict) -> Optional[Dict]:
        """Calculate analytics for a specific user-pool combination"""

        # Get pool info
        pool_info = pools_data.get(pool_nft)
        if not pool_info:
            return None

        pooled_asset = pool_info['pooled_asset']
        lend_apy = pool_info['lend_apy']
        decimals = pool_info['decimals']
        usd_rate = currency_rates.get(pooled_asset, 0)

        # Calculate timestamps for lookback periods (using milliseconds)
        milliseconds_per_day = 86400 * 1000
        timestamp_30d = current_timestamp - (30 * milliseconds_per_day)
        timestamp_90d = current_timestamp - (90 * milliseconds_per_day)
        timestamp_365d = current_timestamp - (365 * milliseconds_per_day)
        earliest_timestamp = current_timestamp - (days_lookback * milliseconds_per_day)

        # Get snapshots
        cur.execute("""
            SELECT timestamp, position_value, total_profit
            FROM user_portfolio_snapshots
            WHERE address_id = %s AND pool_nft = %s 
            AND timestamp >= %s
            ORDER BY timestamp DESC
        """, (address_id, pool_nft, earliest_timestamp))

        snapshots = cur.fetchall()
        if not snapshots:
            return None

        # Get latest snapshot
        latest = snapshots[0]
        latest_timestamp, latest_position_value, latest_total_profit = latest
        latest_position_value = float(latest_position_value)
        latest_total_profit = float(latest_total_profit)

        # DEBUG: Print address_id and current total profit
        print(f"\n=== DEBUG: Address ID {address_id}, Pool {pool_nft} ===")
        print(f"Current total_profit: {latest_total_profit}")

        # Find snapshots closest to target dates
        def find_closest_snapshot(target_timestamp):
            print("Target timestamp", target_timestamp)
            closest = None
            min_diff = float('inf')
            for timestamp, position_value, total_profit in snapshots:
                diff = abs(timestamp - target_timestamp)
                if diff < min_diff:
                    min_diff = diff
                    closest = (timestamp, float(position_value), float(total_profit))
            return closest

        snapshot_30d = find_closest_snapshot(timestamp_30d)
        snapshot_90d = find_closest_snapshot(timestamp_90d)
        snapshot_365d = find_closest_snapshot(timestamp_365d)

        # DEBUG: Print historical total profits
        if snapshot_30d:
            print(f"Total profit 30d ago: {snapshot_30d[2]} (timestamp: {snapshot_30d[0]})")
        else:
            print("Total profit 30d ago: No snapshot found")

        if snapshot_90d:
            print(f"Total profit 90d ago: {snapshot_90d[2]} (timestamp: {snapshot_90d[0]})")
        else:
            print("Total profit 90d ago: No snapshot found")

        if snapshot_365d:
            print(f"Total profit 365d ago: {snapshot_365d[2]} (timestamp: {snapshot_365d[0]})")
        else:
            print("Total profit 365d ago: No snapshot found")

        # Calculate analytics
        analytics = {}

        # Calculate for each period
        periods = [
            ('30d', snapshot_30d, 30),
            ('90d', snapshot_90d, 90),
            ('365d', snapshot_365d, 365)
        ]

        for period_name, snapshot, days in periods:
            if snapshot and snapshot[0] != latest_timestamp:
                old_timestamp, old_position_value, old_total_profit = snapshot

                # Calculate total earned (change in total profit)
                total_earnt = latest_total_profit - old_total_profit

                # DEBUG: Print calculated earnings for this period
                print(f"Total earned {period_name}: {total_earnt} ({latest_total_profit} - {old_total_profit})")

                # Convert to USD (divide by decimals first, then multiply by USD rate)
                total_earnt_usd = (total_earnt / (10 ** decimals)) * usd_rate

                # Calculate APY (annualized return based on position value)
                if old_position_value > 0:
                    # Convert millisecond difference to days
                    actual_days = (latest_timestamp - old_timestamp) / milliseconds_per_day
                    if actual_days > 0:
                        # Calculate return rate and annualize it
                        return_rate = total_earnt / old_position_value
                        periods_per_year = 365.25 / actual_days

                        # Handle negative returns to avoid complex numbers
                        base = 1 + return_rate
                        if base > 0:
                            apy_earnt = (base ** periods_per_year) - 1
                        else:
                            # For losses greater than 100%, calculate as negative APY
                            # Use absolute value and make result negative
                            abs_base = abs(base)
                            if abs_base > 0:
                                apy_earnt = -((abs_base ** periods_per_year) + 1)
                            else:
                                apy_earnt = -1  # 100% loss
                    else:
                        apy_earnt = 0
                else:
                    apy_earnt = 0
            else:
                old_position_value = 0
                total_earnt = 0
                total_earnt_usd = 0
                apy_earnt = 0
                print(f"Total earned {period_name}: {total_earnt} (no valid snapshot)")

            analytics[f'total_earnt_{period_name}'] = total_earnt
            analytics[f'total_earnt_{period_name}_usd'] = total_earnt_usd
            analytics[f'apy_earnt_{period_name}'] = apy_earnt
            analytics[f'position_value_{period_name}'] = old_position_value

        print("=" * 50)  # End debug section

        # Calculate projected earnings for 30 days
        if latest_position_value > 0 and lend_apy > 0:
            # Simple interest calculation for 30 days
            projected_earnt_30d = latest_position_value * lend_apy * (30 / 365.25)
            projected_earnt_30d_usd = (projected_earnt_30d / (10 ** decimals)) * usd_rate
            projected_apy_30d = lend_apy  # Current lend APY from pool
        else:
            projected_earnt_30d = 0
            projected_earnt_30d_usd = 0
            projected_apy_30d = 0

        analytics.update({
            'projected_earnt_30d': projected_earnt_30d,
            'projected_earnt_30d_usd': projected_earnt_30d_usd,
            'projected_apy_30d': projected_apy_30d
        })

        return analytics

    def _upsert_user_pool_analytics(self, cur, address_id: int, pool_nft: str, analytics: Dict) -> bool:
        """Upsert analytics data into user_pool_analytics table"""
        try:
            upsert_query = """
                INSERT INTO user_pool_analytics (
                    address_id, pool_nft,
                    total_earnt_30d, total_earnt_30d_usd, apy_earnt_30d, position_value_30d,
                    total_earnt_90d, total_earnt_90d_usd, apy_earnt_90d, position_value_90d,
                    total_earnt_365d, total_earnt_365d_usd, apy_earnt_365d, position_value_365d,
                    projected_earnt_30d, projected_earnt_30d_usd, projected_apy_30d
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
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
                    updated_at = CURRENT_TIMESTAMP
            """

            params = (
                address_id, pool_nft,
                analytics['total_earnt_30d'], analytics['total_earnt_30d_usd'], analytics['apy_earnt_30d'], analytics['position_value_30d'],
                analytics['total_earnt_90d'], analytics['total_earnt_90d_usd'], analytics['apy_earnt_90d'], analytics['position_value_90d'],
                analytics['total_earnt_365d'], analytics['total_earnt_365d_usd'], analytics['apy_earnt_365d'], analytics['position_value_365d'],
                analytics['projected_earnt_30d'], analytics['projected_earnt_30d_usd'], analytics['projected_apy_30d']
            )

            cur.execute(upsert_query, params)
            return True

        except Exception as e:
            print(f"Error upserting analytics for address_id {address_id}, pool {pool_nft}: {e}")
            return False

    def get_user_pool_analytics(self, address: str, pool_nft: Optional[str] = None) -> List[Dict]:
        """
        Get user pool analytics for a specific address and optionally a specific pool.

        Args:
            address: User's wallet address
            pool_nft: Optional specific pool NFT to filter by

        Returns:
            List of analytics dictionaries
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    if pool_nft:
                        query = """
                            SELECT upa.*, p.pooled_asset, a.address
                            FROM user_pool_analytics upa
                            JOIN addresses a ON upa.address_id = a.id
                            JOIN pools p ON upa.pool_nft = p.nft
                            WHERE a.address = %s AND upa.pool_nft = %s
                        """
                        params = (address, pool_nft)
                    else:
                        query = """
                            SELECT upa.*, p.pooled_asset, a.address
                            FROM user_pool_analytics upa
                            JOIN addresses a ON upa.address_id = a.id
                            JOIN pools p ON upa.pool_nft = p.nft
                            WHERE a.address = %s
                            ORDER BY upa.pool_nft
                        """
                        params = (address,)

                    cur.execute(query, params)
                    rows = cur.fetchall()

                    if not rows:
                        return []

                    # Get column names
                    columns = [desc[0] for desc in cur.description]

                    # Convert to list of dictionaries
                    results = []
                    for row in rows:
                        result = dict(zip(columns, row))
                        # Convert Decimal values to float
                        for key, value in result.items():
                            if isinstance(value, Decimal):
                                result[key] = float(value)
                        results.append(result)

                    return results

        except Exception as e:
            print(f"Error getting user pool analytics: {e}")
            return []


def sync_user_pool_analytics_standalone(db_instance, days_lookback: int = 400) -> int:
    """
    Standalone function to sync user pool analytics.

    Args:
        db_instance: Database instance that has AnalyticsMixin mixed in
        days_lookback: How many days back to look for historical data (default 400)

    Returns:
        Number of analytics records successfully processed
    """
    if not hasattr(db_instance, 'sync_user_pool_analytics'):
        raise AttributeError("Database instance must have AnalyticsMixin mixed in")

    return db_instance.sync_user_pool_analytics(days_lookback)