import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Tuple


class DatabaseManager:
    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')

        if not self.db_url:
            raise ValueError("DATABASE_URL or POSTGRES_URL environment variable not set")

    @contextmanager
    def get_connection(self):
        conn = None
        try:
            conn = psycopg2.connect(self.db_url)
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                conn.close()

    def execute_query(self, query: str, params: Optional[Tuple] = None) -> List[Dict[str, Any]]:
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, params)
                    results = cur.fetchall()
                    return [dict(row) for row in results]
        except Exception as e:
            print(f"Error executing query: {e}")
            return []

    def execute_insert(self, query: str, params: Optional[Tuple] = None, return_id: bool = True) -> Optional[int]:
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)

                    result_id = None
                    if return_id:
                        result = cur.fetchone()
                        result_id = result[0] if result else None

                    conn.commit()
                    return result_id
        except Exception as e:
            print(f"Error executing insert: {e}")
            return None


    def insert_transaction(self,
                           transaction_id: str,
                           address: str,
                           pool_nft: str,
                           transaction_type: str,
                           amount: float,
                           block_height: Optional[int] = None,
                           timestamp: Optional[int] = None) -> Optional[str]:
        """
        Insert a new transaction into the database.
        If the address doesn't exist, creates a new user and address automatically.

        Args:
            transaction_id: Unique identifier for the transaction
            address: Wallet address
            pool_nft: NFT identifier for the pool
            transaction_type: Type of transaction ('lend', 'borrow', 'repayment', 'liquidation')
            amount: Transaction amount
            block_height: Blockchain block height (optional)
            timestamp: Unix timestamp (optional)

        Returns:
            transaction_id if successful, None if failed
        """
        try:
            # Check if address exists
            address_query = "SELECT id FROM addresses WHERE address = %s"
            address_result = self.execute_query(address_query, (address,))

            if address_result:
                # Address exists, use it
                address_id = address_result[0]['id']
            else:
                # Address doesn't exist, create new user and address
                user_insert = "INSERT INTO users DEFAULT VALUES RETURNING id"
                user_id = self.execute_insert(user_insert, return_id=True)

                if not user_id:
                    print("Failed to create user")
                    return None

                # Create address for the new user
                address_insert = """
                    INSERT INTO addresses (address, user_id, is_primary)
                    VALUES (%s, %s, %s)
                    RETURNING id
                """
                address_id = self.execute_insert(address_insert, (address, user_id, True), return_id=True)

                if not address_id:
                    print("Failed to create address")
                    return None

            # Validate transaction type
            valid_types = ['lend', 'borrow', 'repayment', 'liquidation']
            if transaction_type not in valid_types:
                print(f"Error: Invalid transaction type '{transaction_type}'. Must be one of: {valid_types}")
                return None

            # Insert the transaction
            insert_query = """
                INSERT INTO transactions (id, address_id, pool_nft, type, amount, block_height, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """

            params = (transaction_id, address_id, pool_nft, transaction_type, amount, block_height, timestamp)
            result_id = self.execute_insert(insert_query, params, return_id=True)

            if result_id:
                return transaction_id
            else:
                print(f"Failed to insert transaction: {transaction_id}")
                return None

        except Exception as e:
            print(f"Error inserting transaction: {e}")
            return None


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
