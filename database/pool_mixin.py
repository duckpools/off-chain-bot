from typing import Optional
from .core import CoreDB

class PoolMixin:
    def upsert_pool(self,
                    nft: str,
                    pooled_asset: str,
                    total_lent: float = 0,
                    total_borrowed: float = 0,
                    lend_apy: float = 0,
                    borrow_apy: float = 0) -> Optional[str]:
        """
        Insert or update a pool in the database.
        If the pool exists, updates it with new data. If not, creates it.

        Args:
            nft: Unique NFT identifier for the pool (primary key)
            pooled_asset: The asset being pooled
            total_lent: Total amount lent in the pool (default: 0)
            total_borrowed: Total amount borrowed from the pool (default: 0)
            lend_apy: Annual percentage yield for lenders (default: 0)
            borrow_apy: Annual percentage yield for borrowers (default: 0)

        Returns:
            nft identifier if successful, None if failed
        """
        try:
            # Use PostgreSQL's ON CONFLICT to handle upsert
            upsert_query = """
                   INSERT INTO pools (nft, pooled_asset, total_lent, total_borrowed, lend_apy, borrow_apy)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (nft)
                   DO UPDATE SET
                       pooled_asset = EXCLUDED.pooled_asset,
                       total_lent = EXCLUDED.total_lent,
                       total_borrowed = EXCLUDED.total_borrowed,
                       lend_apy = EXCLUDED.lend_apy,
                       borrow_apy = EXCLUDED.borrow_apy,
                       updated_at = CURRENT_TIMESTAMP
                   RETURNING nft
               """

            params = (nft, pooled_asset, total_lent, total_borrowed, lend_apy, borrow_apy)
            result_nft = self.execute_insert(upsert_query, params, return_id=True)

            if result_nft:
                return nft
            else:
                print(f"Failed to upsert pool: {nft}")
                return None

        except Exception as e:
            print(f"Error upserting pool: {e}")
            return None

    def upsert_pool_data_historical(self,
                                    pool_nft: str,
                                    block_height: int,
                                    transaction_id: str,
                                    lend_apy: float,
                                    borrow_apy: float,
                                    pool_utilization: float,
                                    total_lent: float,
                                    total_borrowed: float,
                                    box_timestamp: int) -> Optional[bool]:
        """
        Insert or update pool historical data in the database.
        If the pool_nft, block_height, and transaction_id combination exists, updates it with new data.
        If not, creates a new record.

        Args:
            pool_nft: NFT identifier for the pool
            block_height: Blockchain block height when data was recorded
            transaction_id: Transaction ID that caused the pool state change
            lend_apy: Annual percentage yield for lenders
            borrow_apy: Annual percentage yield for borrowers
            pool_utilization: Pool utilization rate (0.0 to 1.0 or 0-100 depending on your preference)
            total_lent: Total amount lent in the pool at this point in time
            total_borrowed: Total amount borrowed from the pool at this point in time
            box_timestamp: Blockchain timestamp when the transaction occurred

        Returns:
            True if successful, None if failed
        """
        try:
            # Use PostgreSQL's ON CONFLICT to handle upsert
            upsert_query = """
                   INSERT INTO pool_data_historical (pool_nft, block_height, transaction_id, lend_apy, borrow_apy, pool_utilization, total_lent, total_borrowed, box_timestamp)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (pool_nft, block_height, transaction_id)
                   DO UPDATE SET
                       lend_apy = EXCLUDED.lend_apy,
                       borrow_apy = EXCLUDED.borrow_apy,
                       pool_utilization = EXCLUDED.pool_utilization,
                       total_lent = EXCLUDED.total_lent,
                       total_borrowed = EXCLUDED.total_borrowed,
                       box_timestamp = EXCLUDED.box_timestamp,
                       updated_at = CURRENT_TIMESTAMP
                   RETURNING pool_nft, block_height, transaction_id
               """

            params = (
                pool_nft, block_height, transaction_id, lend_apy, borrow_apy, pool_utilization, total_lent,
                total_borrowed,
                box_timestamp)
            result = self.execute_insert(upsert_query, params, return_id=True)

            if result:
                return True
            else:
                print(
                    f"Failed to upsert pool data for pool: {pool_nft} at block: {block_height}, transaction: {transaction_id}")
                return None

        except Exception as e:
            print(f"Error upserting pool data: {e}")
            return None
