from typing import Optional, List

from psycopg2.extras import execute_values

from .core import CoreDB
from logger import set_logger

logger = set_logger(__name__)


class PoolMixin:
    def upsert_pool(self,
                    nft: str,
                    pooled_asset: str,
                    total_lent: float = 0,
                    total_borrowed: float = 0,
                    lend_apy: float = 0,
                    borrow_apy: float = 0,
                    sync_block: Optional[int] = None) -> Optional[str]:
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
            sync_block: Block height when this data was synced

        Returns:
            nft identifier if successful, None if failed
        """
        try:
            # Use PostgreSQL's ON CONFLICT to handle upsert
            upsert_query = """
                   INSERT INTO pools (nft, pooled_asset, total_lent, total_borrowed, lend_apy, borrow_apy, sync_block)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (nft)
                   DO UPDATE SET
                       pooled_asset = EXCLUDED.pooled_asset,
                       total_lent = EXCLUDED.total_lent,
                       total_borrowed = EXCLUDED.total_borrowed,
                       lend_apy = EXCLUDED.lend_apy,
                       borrow_apy = EXCLUDED.borrow_apy,
                       sync_block = EXCLUDED.sync_block,
                       updated_at = CURRENT_TIMESTAMP
                   RETURNING nft
               """

            params = (nft, pooled_asset, total_lent, total_borrowed, lend_apy, borrow_apy, sync_block)
            result_nft = self.execute_insert(upsert_query, params, return_id=True)

            if result_nft:
                return nft
            else:
                print(f"Failed to upsert pool: {nft}")
                logger.error("Failed to upsert pool: %s", nft)
                return None

        except Exception as e:
            print(f"Error upserting pool {nft}: {e}")
            logger.error("Error upserting pool %s: %s", nft, e, exc_info=True)
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
                                    box_timestamp: int,
                                    pool_box_id: str,
                                    lend_token_value: float,
                                    sync_block: Optional[int] = None) -> Optional[bool]:
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
            pool_box_id: Pool box ID
            lend_token_value: Lend token value
            sync_block: Block height when this data was synced

        Returns:
            True if successful, None if failed
        """
        try:
            # Use PostgreSQL's ON CONFLICT to handle upsert
            upsert_query = """
                INSERT INTO pool_data_historical (pool_nft, block_height, transaction_id, lend_apy, borrow_apy, pool_utilization, total_lent, total_borrowed, box_timestamp, pool_box_id, lend_token_value, sync_block)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (pool_nft, block_height, transaction_id)
                DO UPDATE SET
                    lend_apy = EXCLUDED.lend_apy,
                    borrow_apy = EXCLUDED.borrow_apy,
                    pool_utilization = EXCLUDED.pool_utilization,
                    total_lent = EXCLUDED.total_lent,
                    total_borrowed = EXCLUDED.total_borrowed,
                    box_timestamp = EXCLUDED.box_timestamp,
                    pool_box_id = EXCLUDED.pool_box_id,
                    lend_token_value = EXCLUDED.lend_token_value,
                    sync_block = EXCLUDED.sync_block,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING pool_nft, block_height, transaction_id
            """

            params = (
                pool_nft, block_height, transaction_id, lend_apy, borrow_apy, pool_utilization,
                total_lent, total_borrowed, box_timestamp, pool_box_id, lend_token_value, sync_block
            )
            result = self.execute_insert(upsert_query, params, return_id=True)

            if result:
                return True
            else:
                print(f"Failed to upsert pool data for pool: {pool_nft} at block: {block_height}, transaction: {transaction_id}")
                logger.error("Failed to upsert pool data for pool: %s at block: %d, transaction: %s",
                             pool_nft, block_height, transaction_id)
                return None

        except Exception as e:
            print(f"Error upserting pool data for pool {pool_nft}: {e}")
            logger.error("Error upserting pool data for pool %s: %s", pool_nft, e, exc_info=True)
            return None

    def batch_upsert_pools(self, pools_data: List[tuple]) -> int:
        """
        Batch upsert pools data.

        Args:
            pools_data: List of tuples (nft, pooled_asset, total_lent, total_borrowed, lend_apy, borrow_apy, sync_block)

        Returns:
            Number of successfully processed pools
        """
        if not pools_data:
            return 0

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    upsert_query = """
                        INSERT INTO pools (nft, pooled_asset, total_lent, total_borrowed, lend_apy, borrow_apy, sync_block)
                        VALUES %s
                        ON CONFLICT (nft)
                        DO UPDATE SET
                            pooled_asset = EXCLUDED.pooled_asset,
                            total_lent = EXCLUDED.total_lent,
                            total_borrowed = EXCLUDED.total_borrowed,
                            lend_apy = EXCLUDED.lend_apy,
                            borrow_apy = EXCLUDED.borrow_apy,
                            sync_block = EXCLUDED.sync_block,
                            updated_at = CURRENT_TIMESTAMP
                    """

                    execute_values(
                        cur,
                        upsert_query,
                        pools_data,
                        template=None,
                        page_size=1000
                    )

                    conn.commit()
                    return len(pools_data)

        except Exception as e:
            print(f"Error batch upserting pools ({len(pools_data)} records): {e}")
            logger.error("Error batch upserting pools (%d records): %s", len(pools_data), e, exc_info=True)
            return 0

    def batch_upsert_pool_data_historical(self, pool_data: List[tuple]) -> int:
        """
        Batch upsert pool historical data.

        Args:
            pool_data: List of tuples containing pool historical data with sync_block

        Returns:
            Number of successfully processed records
        """
        if not pool_data:
            return 0

        logger.debug("batch_upsert_pool_data_historical: inserting %d records", len(pool_data))

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    upsert_query = """
                        INSERT INTO pool_data_historical
                        (pool_nft, block_height, transaction_id, lend_apy, borrow_apy,
                         pool_utilization, total_lent, total_borrowed, box_timestamp,
                         pool_box_id, lend_token_value, sync_block)
                        VALUES %s
                        ON CONFLICT (pool_nft, block_height, transaction_id)
                        DO UPDATE SET
                            lend_apy = EXCLUDED.lend_apy,
                            borrow_apy = EXCLUDED.borrow_apy,
                            pool_utilization = EXCLUDED.pool_utilization,
                            total_lent = EXCLUDED.total_lent,
                            total_borrowed = EXCLUDED.total_borrowed,
                            box_timestamp = EXCLUDED.box_timestamp,
                            pool_box_id = EXCLUDED.pool_box_id,
                            lend_token_value = EXCLUDED.lend_token_value,
                            sync_block = EXCLUDED.sync_block,
                            updated_at = CURRENT_TIMESTAMP
                    """

                    execute_values(
                        cur,
                        upsert_query,
                        pool_data,
                        template=None,
                        page_size=1000
                    )

                    conn.commit()
                    logger.info("batch_upsert_pool_data_historical: successfully inserted %d records", len(pool_data))
                    return len(pool_data)

        except Exception as e:
            print(f"batch_upsert_pool_data_historical FAILED ({len(pool_data)} records): {e}")
            logger.error("batch_upsert_pool_data_historical FAILED (%d records): %s", len(pool_data), e, exc_info=True)
            # Log sample of the data that failed for diagnosis
            if pool_data:
                sample = pool_data[0]
                logger.error("  Sample row — pool_nft: %s, block_height: %s, tx_id: %s, "
                             "lend_apy: %s, borrow_apy: %s, utilization: %s, total_lent: %s, "
                             "total_borrowed: %s, timestamp: %s (type=%s), box_id: %s, "
                             "lend_token_value: %s, sync_block: %s",
                             str(sample[0])[:20], sample[1], str(sample[2])[:20],
                             sample[3], sample[4], sample[5], sample[6],
                             sample[7], sample[8], type(sample[8]).__name__, str(sample[9])[:20],
                             sample[10], sample[11])
                # Check for duplicate keys in the batch
                keys = [(r[0], r[1], r[2]) for r in pool_data]
                unique_keys = set(keys)
                if len(keys) != len(unique_keys):
                    logger.error("  DUPLICATE KEYS DETECTED: %d total rows, %d unique keys, %d duplicates",
                                 len(keys), len(unique_keys), len(keys) - len(unique_keys))
                    # Log the actual duplicate keys
                    from collections import Counter
                    key_counts = Counter(keys)
                    dup_keys = [(k, cnt) for k, cnt in key_counts.items() if cnt > 1]
                    for (pool_nft, height, tx_id), cnt in dup_keys[:20]:
                        logger.error("  DUP KEY (x%d): pool_nft=%s, block_height=%s, tx_id=%s",
                                     cnt, str(pool_nft)[:20], height, str(tx_id)[:20])
                # Check for None values in NOT NULL columns
                none_rows = [i for i, r in enumerate(pool_data) if any(v is None for v in r[:11])]
                if none_rows:
                    logger.error("  NULL VALUES in NOT NULL columns at row indices: %s", none_rows[:10])
                    first_bad = pool_data[none_rows[0]]
                    logger.error("  First bad row: %s", first_bad)
            return 0