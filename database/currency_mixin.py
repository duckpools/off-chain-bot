import logging
from typing import Optional, List
import time

logger = logging.getLogger(__name__)


class CurrencyMixin:
    def insert_currency_rate(self, pooled_asset: str, usd_rate: float, timestamp: int, sync_block: Optional[int] = None) -> Optional[int]:
        """Insert a new currency rate record (historical tracking)."""
        try:
            insert_query = """
                INSERT INTO currency_rates (pooled_asset, usd_rate, timestamp, sync_block)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (pooled_asset, timestamp) DO NOTHING
                RETURNING id
            """

            params = (pooled_asset, usd_rate, timestamp, sync_block)
            result = self.execute_insert(insert_query, params, return_id=True)

            return result

        except Exception as e:
            print(f"Error inserting currency rate for {pooled_asset}: {e}")
            logger.error("Error inserting currency rate for %s: %s", pooled_asset, e, exc_info=True)
            return None

    def get_latest_currency_timestamp(self, pooled_asset: str) -> Optional[int]:
        """Get the timestamp of the most recent currency rate for an asset."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT timestamp
                        FROM currency_rates
                        WHERE pooled_asset = %s
                        ORDER BY timestamp DESC
                        LIMIT 1
                    """, (pooled_asset,))
                    result = cur.fetchone()
                    return result[0] if result else None
        except Exception as e:
            print(f"Error getting latest currency timestamp for {pooled_asset}: {e}")
            logger.error("Error getting latest currency timestamp for %s: %s", pooled_asset, e, exc_info=True)
            return None

    def upsert_currency_rate(self, pooled_asset: str, usd_rate: float = 0, sync_block: Optional[int] = None) -> Optional[str]:
        """
        DEPRECATED: Use insert_currency_rate() instead.
        This method is kept for backward compatibility during migration.
        Inserts with current timestamp.
        """
        timestamp = int(time.time())
        result = self.insert_currency_rate(pooled_asset, usd_rate, timestamp, sync_block)
        return pooled_asset if result else None

    def batch_insert_currency_rates(self, currency_data: List[tuple], sync_block: Optional[int] = None) -> int:
        """
        Batch insert currency rates (historical tracking).

        Args:
            currency_data: List of tuples (pooled_asset, usd_rate, timestamp) or (pooled_asset, usd_rate, timestamp, sync_block)
            sync_block: Block height when this data was synced (applied to all records if not provided in tuples)

        Returns:
            Number of successfully inserted rates
        """
        if not currency_data:
            return 0

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    from psycopg2.extras import execute_values

                    # Normalize the data to include sync_block
                    normalized_data = []
                    for item in currency_data:
                        if len(item) >= 4:  # Already has sync_block
                            normalized_data.append(item)
                        else:  # Add sync_block
                            normalized_data.append((*item, sync_block))

                    insert_query = """
                        INSERT INTO currency_rates (pooled_asset, usd_rate, timestamp, sync_block)
                        VALUES %s
                        ON CONFLICT (pooled_asset, timestamp) DO NOTHING
                    """

                    execute_values(
                        cur,
                        insert_query,
                        normalized_data,
                        template=None,
                        page_size=1000
                    )

                    conn.commit()
                    return len(normalized_data)

        except Exception as e:
            print(f"Error batch inserting currency rates: {e}")
            logger.error("Error batch inserting currency rates: %s", e, exc_info=True)
            return 0

    def batch_upsert_currency_rates(self, currency_data: List[tuple], sync_block: Optional[int] = None) -> int:
        """
        DEPRECATED: Use batch_insert_currency_rates() instead.
        This method is kept for backward compatibility during migration.
        Converts old format (pooled_asset, usd_rate) to new format with timestamp.
        """
        if not currency_data:
            return 0

        current_timestamp = int(time.time())
        # Convert to new format: (pooled_asset, usd_rate, timestamp, sync_block)
        new_format_data = []
        for item in currency_data:
            if len(item) >= 3:  # (pooled_asset, usd_rate, sync_block)
                new_format_data.append((item[0], item[1], current_timestamp, item[2]))
            else:  # (pooled_asset, usd_rate)
                new_format_data.append((item[0], item[1], current_timestamp, sync_block))

        return self.batch_insert_currency_rates(new_format_data, sync_block)