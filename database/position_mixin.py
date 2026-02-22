import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class PositionMixin:
    """Mixin for handling user current position operations (on-chain verification)."""

    def batch_upsert_user_current_positions(
            self,
            positions_data: List[Tuple[str, str, float, float]],
            sync_block: Optional[int] = None
    ) -> int:
        """
        Batch upsert user current positions.

        Args:
            positions_data: List of tuples (address, pool_nft, position_tokens, position_value)
            sync_block: Block height to mark as sync point

        Returns:
            Number of records upserted
        """
        if not positions_data:
            return 0

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # First, get or create all address_ids
                    addresses = list(set([addr for addr, _, _, _ in positions_data]))
                    address_map = {}

                    for address in addresses:
                        cur.execute("SELECT id FROM addresses WHERE address = %s", (address,))
                        result = cur.fetchone()

                        if result:
                            address_map[address] = result[0]
                        else:
                            # Create address
                            cur.execute(
                                "INSERT INTO addresses (address, sync_block) VALUES (%s, %s) RETURNING id",
                                (address, sync_block)
                            )
                            result = cur.fetchone()
                            if result:
                                address_map[address] = result[0]

                    # Prepare data for batch upsert
                    upsert_values = [
                        (address_map[addr], pool_nft, position_tokens, position_value, sync_block)
                        for addr, pool_nft, position_tokens, position_value in positions_data
                        if addr in address_map
                    ]

                    if not upsert_values:
                        return 0

                    # Batch upsert using execute_values for better performance
                    from psycopg2.extras import execute_values

                    upsert_query = """
                        INSERT INTO user_current_positions
                        (address_id, pool_nft, position_tokens, position_value, sync_block)
                        VALUES %s
                        ON CONFLICT (address_id, pool_nft)
                        DO UPDATE SET
                            position_tokens = EXCLUDED.position_tokens,
                            position_value = EXCLUDED.position_value,
                            sync_block = EXCLUDED.sync_block,
                            updated_at = CURRENT_TIMESTAMP
                    """

                    execute_values(cur, upsert_query, upsert_values)
                    conn.commit()

                    return len(upsert_values)

        except Exception as e:
            print(f"Error batch upserting user current positions ({len(positions_data)} records): {e}")
            logger.error("Error batch upserting user current positions (%d records): %s",
                         len(positions_data), e, exc_info=True)
            return 0

    def get_current_positions_by_pool(self, pool_nft: str) -> List[Dict]:
        """
        Get all current positions for a specific pool.

        Args:
            pool_nft: Pool NFT identifier

        Returns:
            List of dicts with address, pool_nft, position_tokens, position_value
        """
        try:
            query = """
                SELECT a.address, ucp.pool_nft, ucp.position_tokens, ucp.position_value,
                       ucp.sync_block, ucp.updated_at
                FROM user_current_positions ucp
                JOIN addresses a ON ucp.address_id = a.id
                WHERE ucp.pool_nft = %s
                ORDER BY ucp.position_value DESC
            """
            return self.execute_query(query, (pool_nft,))
        except Exception as e:
            print(f"Error getting current positions by pool {pool_nft}: {e}")
            logger.error("Error getting current positions by pool %s: %s", pool_nft, e, exc_info=True)
            return []

    def delete_pool_current_positions(self, pool_nft: str) -> int:
        """
        Delete all current position entries for a specific pool.

        Args:
            pool_nft: Pool NFT identifier

        Returns:
            Number of rows deleted
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    delete_query = "DELETE FROM user_current_positions WHERE pool_nft = %s"
                    cur.execute(delete_query, (pool_nft,))
                    rows_deleted = cur.rowcount
                    conn.commit()
                    return rows_deleted
        except Exception as e:
            print(f"Error deleting pool current positions for {pool_nft}: {e}")
            logger.error("Error deleting pool current positions for %s: %s", pool_nft, e, exc_info=True)
            return 0

    def get_latest_lend_token_value(self, pool_nft: str) -> Optional[float]:
        """
        Get the latest lend_token_value for a pool from pool_data_historical.

        Args:
            pool_nft: Pool NFT identifier

        Returns:
            Latest lend_token_value or None
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    query = """
                        SELECT lend_token_value
                        FROM pool_data_historical
                        WHERE pool_nft = %s
                        ORDER BY block_height DESC
                        LIMIT 1
                    """
                    cur.execute(query, (pool_nft,))
                    result = cur.fetchone()
                    if result:
                        return float(result[0])
                    return None
        except Exception as e:
            print(f"Error getting latest lend token value for {pool_nft}: {e}")
            logger.error("Error getting latest lend token value for %s: %s", pool_nft, e, exc_info=True)
            return None
