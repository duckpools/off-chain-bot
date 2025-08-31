from typing import Optional, Dict, List


class SyncMixin:
    def get_lowest_sync_block(self) -> Optional[int]:
        """
        Get the lowest sync_block value across all tables to determine
        where to start incremental sync from. Treats NULL sync_block values as 0.

        Returns:
            The lowest sync_block value found (with NULL treated as 0), or None if no data exists
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # Query all tables with sync_block, treating NULL as 0
                    sync_block_queries = [
                        "SELECT MIN(COALESCE(sync_block, 0)) FROM user_pool_analytics",
                        "SELECT MIN(COALESCE(sync_block, 0)) FROM pools",
                        "SELECT MIN(COALESCE(sync_block, 0)) FROM currency_rates",
                        "SELECT MIN(COALESCE(sync_block, 0)) FROM pool_data_historical",
                        "SELECT MIN(COALESCE(sync_block, 0)) FROM transactions",
                        "SELECT MIN(COALESCE(sync_block, 0)) FROM borrow_positions",
                        "SELECT MIN(COALESCE(sync_block, 0)) FROM user_lend_positions_historical",
                        "SELECT MIN(COALESCE(sync_block, 0)) FROM user_deposits_historical",
                        "SELECT MIN(COALESCE(sync_block, 0)) FROM user_portfolio_snapshots"
                    ]

                    min_sync_blocks = []

                    for query in sync_block_queries:
                        try:
                            cur.execute(query)
                            result = cur.fetchone()
                            if result and result[0] is not None:
                                min_sync_blocks.append(int(result[0]))
                        except Exception as e:
                            print(f"Error querying sync_block from table: {e}")
                            continue

                    if not min_sync_blocks:
                        print("No sync_block values found in any table")
                        return None

                    lowest_sync_block = min(min_sync_blocks)
                    print(f"Lowest sync_block found: {lowest_sync_block}")
                    return lowest_sync_block

        except Exception as e:
            print(f"Error getting lowest sync_block: {e}")
            return None

    def get_highest_sync_block(self) -> Optional[int]:
        """
        Get the highest sync_block value across all tables to determine
        the most recent sync state.

        Returns:
            The highest sync_block value found, or None if no sync_blocks exist
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # Query all tables with sync_block to find the maximum value
                    sync_block_queries = [
                        "SELECT MAX(sync_block) FROM user_pool_analytics WHERE sync_block IS NOT NULL",
                        "SELECT MAX(sync_block) FROM pools WHERE sync_block IS NOT NULL",
                        "SELECT MAX(sync_block) FROM currency_rates WHERE sync_block IS NOT NULL",
                        "SELECT MAX(sync_block) FROM pool_data_historical WHERE sync_block IS NOT NULL",
                        "SELECT MAX(sync_block) FROM transactions WHERE sync_block IS NOT NULL",
                        "SELECT MAX(sync_block) FROM borrow_positions WHERE sync_block IS NOT NULL",
                        "SELECT MAX(sync_block) FROM user_lend_positions_historical WHERE sync_block IS NOT NULL",
                        "SELECT MAX(sync_block) FROM user_deposits_historical WHERE sync_block IS NOT NULL",
                        "SELECT MAX(sync_block) FROM user_portfolio_snapshots WHERE sync_block IS NOT NULL"
                    ]

                    max_sync_blocks = []

                    for query in sync_block_queries:
                        try:
                            cur.execute(query)
                            result = cur.fetchone()
                            if result and result[0] is not None:
                                max_sync_blocks.append(int(result[0]))
                        except Exception as e:
                            print(f"Error querying sync_block from table: {e}")
                            continue

                    if not max_sync_blocks:
                        print("No sync_block values found in any table")
                        return None

                    highest_sync_block = max(max_sync_blocks)
                    print(f"Highest sync_block found: {highest_sync_block}")
                    return highest_sync_block

        except Exception as e:
            print(f"Error getting highest sync_block: {e}")
            return None

    def get_sync_block_summary(self) -> Dict[str, Optional[int]]:
        """
        Get a summary of sync_block values per table for debugging/monitoring.

        Returns:
            Dictionary mapping table names to their min/max sync_block values
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    tables = [
                        'users', 'addresses', 'user_pool_analytics', 'pools',
                        'currency_rates', 'pool_data_historical',
                        'transactions', 'borrow_positions', 'user_lend_positions_historical',
                        'user_deposits_historical', 'user_portfolio_snapshots'
                    ]

                    summary = {}

                    for table in tables:
                        try:
                            # Get min, max, and count for each table
                            query = f"""
                                SELECT 
                                    MIN(sync_block) as min_sync,
                                    MAX(sync_block) as max_sync,
                                    COUNT(sync_block) as count_sync,
                                    COUNT(*) as total_rows
                                FROM {table}
                                WHERE sync_block IS NOT NULL
                            """
                            cur.execute(query)
                            result = cur.fetchone()

                            summary[table] = {
                                'min_sync_block': result[0] if result[0] is not None else None,
                                'max_sync_block': result[1] if result[1] is not None else None,
                                'synced_rows': result[2] if result[2] is not None else 0,
                                'total_rows': result[3] if result[3] is not None else 0
                            }
                        except Exception as e:
                            print(f"Error querying table {table}: {e}")
                            summary[table] = {
                                'min_sync_block': None,
                                'max_sync_block': None,
                                'synced_rows': 0,
                                'total_rows': 0
                            }

                    return summary

        except Exception as e:
            print(f"Error getting sync_block summary: {e}")
            return {}

    def clear_sync_blocks_before(self, before_block: int) -> Dict[str, int]:
        """
        Clear sync_block values that are before a certain block height.
        Useful for re-syncing data from a specific point.

        Args:
            before_block: Clear sync_blocks less than this value

        Returns:
            Dictionary mapping table names to number of rows affected
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    tables = [
                        'users', 'addresses', 'user_pool_analytics', 'pools',
                        'currency_rates', 'pool_data_historical',
                        'transactions', 'borrow_positions', 'user_lend_positions_historical',
                        'user_deposits_historical', 'user_portfolio_snapshots'
                    ]

                    affected_rows = {}

                    for table in tables:
                        try:
                            query = f"UPDATE {table} SET sync_block = NULL WHERE sync_block < %s"
                            cur.execute(query, (before_block,))
                            affected_rows[table] = cur.rowcount
                        except Exception as e:
                            print(f"Error clearing sync_blocks from table {table}: {e}")
                            affected_rows[table] = 0

                    conn.commit()
                    return affected_rows

        except Exception as e:
            print(f"Error clearing sync_blocks: {e}")
            return {}