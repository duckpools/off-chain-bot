import logging
from typing import List, Dict, Optional, Tuple
from .core import CoreDB

logger = logging.getLogger(__name__)


class DebtMixin:
    """Mixin for handling user pool debt operations."""

    def batch_upsert_user_pool_debts(
            self,
            debts_data: List[Tuple[str, str, float]],
            sync_block: Optional[int] = None
    ) -> int:
        """
        Batch upsert user pool debts.

        Args:
            debts_data: List of tuples (address, pool_nft, total_debt)
            sync_block: Block height to mark as sync point

        Returns:
            Number of records upserted
        """
        if not debts_data:
            return 0

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # First, get or create all address_ids
                    addresses = list(set([addr for addr, _, _ in debts_data]))
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
                        (address_map[addr], pool_nft, total_debt, sync_block)
                        for addr, pool_nft, total_debt in debts_data
                        if addr in address_map
                    ]

                    if not upsert_values:
                        return 0

                    # Batch upsert using execute_values for better performance
                    from psycopg2.extras import execute_values

                    upsert_query = """
                        INSERT INTO user_pool_debts
                        (address_id, pool_nft, total_debt, sync_block)
                        VALUES %s
                        ON CONFLICT (address_id, pool_nft)
                        DO UPDATE SET
                            total_debt = EXCLUDED.total_debt,
                            sync_block = EXCLUDED.sync_block,
                            updated_at = CURRENT_TIMESTAMP
                    """

                    execute_values(cur, upsert_query, upsert_values)
                    conn.commit()

                    return len(upsert_values)

        except Exception as e:
            print(f"Error batch upserting user pool debts: {e}")
            logger.error("Error batch upserting user pool debts: %s", e, exc_info=True)
            return 0

    def get_user_debts_by_pool(self, pool_nft: str) -> List[Dict]:
        """
        Get all user debts for a specific pool.

        Args:
            pool_nft: Pool NFT identifier

        Returns:
            List of dicts with address, pool_nft, total_debt
        """
        try:
            query = """
                SELECT a.address, upd.pool_nft, upd.total_debt, upd.sync_block, upd.updated_at
                FROM user_pool_debts upd
                JOIN addresses a ON upd.address_id = a.id
                WHERE upd.pool_nft = %s
                ORDER BY upd.total_debt DESC
            """
            return self.execute_query(query, (pool_nft,))
        except Exception as e:
            print(f"Error getting user debts by pool: {e}")
            logger.error("Error getting user debts by pool: %s", e, exc_info=True)
            return []

    def get_user_debts_by_address(self, address: str) -> List[Dict]:
        """
        Get all debts for a specific address across all pools.

        Args:
            address: User address

        Returns:
            List of dicts with address, pool_nft, total_debt
        """
        try:
            query = """
                SELECT a.address, upd.pool_nft, upd.total_debt, upd.sync_block, upd.updated_at
                FROM user_pool_debts upd
                JOIN addresses a ON upd.address_id = a.id
                WHERE a.address = %s
                ORDER BY upd.pool_nft
            """
            return self.execute_query(query, (address,))
        except Exception as e:
            print(f"Error getting user debts by address: {e}")
            logger.error("Error getting user debts by address: %s", e, exc_info=True)
            return []

    def get_all_addresses(self) -> List[str]:
        """
        Get all addresses from the addresses table.

        Returns:
            List of address strings
        """
        try:
            query = "SELECT address FROM addresses ORDER BY id"
            results = self.execute_query(query)
            return [row['address'] for row in results]
        except Exception as e:
            print(f"Error getting all addresses: {e}")
            logger.error("Error getting all addresses: %s", e, exc_info=True)
            return []

    def delete_pool_debts(self, pool_nft: str) -> int:
        """
        Delete all debt entries for a specific pool.
        This is useful for clearing old data before inserting fresh debt calculations.

        Args:
            pool_nft: Pool NFT identifier

        Returns:
            Number of rows deleted
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    delete_query = "DELETE FROM user_pool_debts WHERE pool_nft = %s"
                    cur.execute(delete_query, (pool_nft,))
                    rows_deleted = cur.rowcount
                    conn.commit()
                    return rows_deleted
        except Exception as e:
            print(f"Error deleting pool debts for {pool_nft}: {e}")
            logger.error("Error deleting pool debts for %s: %s", pool_nft, e, exc_info=True)
            return 0
