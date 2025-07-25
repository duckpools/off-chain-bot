from typing import Optional
from .core import CoreDB

class HistoryMixin:
    def upsert_lend_position_historical(self,
                                        address: str,
                                        pool_nft: str,
                                        transaction_id: Optional[str],
                                        block_height: int,
                                        timestamp: int,
                                        position_tokens: float,
                                        position_value: float,
                                        total_deposited: float,
                                        total_withdrawn: float,
                                        realized_profit: float,
                                        total_profit: float) -> Optional[int]:
        """
        Upsert a lend position historical record.
        Updates if a record exists for this address/pool/timestamp, otherwise inserts.

        Returns:
            The id of the upserted record if successful, None if failed
        """
        try:
            # Get or create address_id
            address_query = "SELECT id FROM addresses WHERE address = %s"
            address_result = self.execute_query(address_query, (address,))

            if address_result:
                address_id = address_result[0]['id']
            else:
                user_id = self.execute_insert("INSERT INTO users DEFAULT VALUES RETURNING id", return_id=True)
                if not user_id:
                    print("Failed to create user")
                    return None

                address_id = self.execute_insert(
                    "INSERT INTO addresses (address, user_id, is_primary) VALUES (%s, %s, %s) RETURNING id",
                    (address, user_id, True),
                    return_id=True
                )
                if not address_id:
                    print("Failed to create address")
                    return None

            # Upsert historical record
            upsert_query = """
                INSERT INTO lend_positions_historical 
                (address_id, pool_nft, transaction_id, block_height, timestamp,
                 position_tokens, position_value, total_deposited, total_withdrawn,
                 realized_profit, total_profit)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (address_id, pool_nft, timestamp)
                DO UPDATE SET
                    transaction_id = EXCLUDED.transaction_id,
                    block_height = EXCLUDED.block_height,
                    position_tokens = EXCLUDED.position_tokens,
                    position_value = EXCLUDED.position_value,
                    total_deposited = EXCLUDED.total_deposited,
                    total_withdrawn = EXCLUDED.total_withdrawn,
                    realized_profit = EXCLUDED.realized_profit,
                    total_profit = EXCLUDED.total_profit
                RETURNING id
            """

            params = (address_id, pool_nft, transaction_id, block_height, timestamp,
                      position_tokens, position_value, total_deposited, total_withdrawn,
                      realized_profit, total_profit)

            return self.execute_insert(upsert_query, params, return_id=True)

        except Exception as e:
            print(f"Error upserting lend position historical: {e}")
            return None

    def upsert_user_lend_position_historical(self,
                                             address: str,
                                             pool_nft: str,
                                             block_height: int,
                                             timestamp: int,
                                             position_tokens: float,
                                             position_value: float) -> Optional[int]:
        """
        Upsert a user lend position historical record.
        Updates if a record exists for this address/pool/block_height, otherwise inserts.

        Returns:
            The id of the upserted record if successful, None if failed
        """
        try:
            # Get or create address_id
            address_query = "SELECT id FROM addresses WHERE address = %s"
            address_result = self.execute_query(address_query, (address,))

            if address_result:
                address_id = address_result[0]['id']
            else:
                user_id = self.execute_insert("INSERT INTO users DEFAULT VALUES RETURNING id", return_id=True)
                if not user_id:
                    print("Failed to create user")
                    return None

                address_id = self.execute_insert(
                    "INSERT INTO addresses (address, user_id, is_primary) VALUES (%s, %s, %s) RETURNING id",
                    (address, user_id, True),
                    return_id=True
                )
                if not address_id:
                    print("Failed to create address")
                    return None

            # Upsert historical record
            upsert_query = """
                INSERT INTO user_lend_positions_historical 
                (address_id, pool_nft, block_height, timestamp, position_tokens, position_value)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (address_id, pool_nft, block_height)
                DO UPDATE SET
                    timestamp = EXCLUDED.timestamp,
                    position_tokens = EXCLUDED.position_tokens,
                    position_value = EXCLUDED.position_value
                RETURNING id
            """

            params = (address_id, pool_nft, block_height, timestamp, position_tokens, position_value)

            return self.execute_insert(upsert_query, params, return_id=True)

        except Exception as e:
            print(f"Error upserting user lend position historical: {e}")
            return None

    def upsert_user_deposits_historical(self,
                                        address: str,
                                        pool_nft: str,
                                        transaction_id: Optional[str],
                                        block_height: int,
                                        timestamp: int,
                                        total_deposited: float,
                                        total_withdrawn: float) -> Optional[int]:
        """
        Upsert a user deposits historical record.
        Updates if a record exists for this address/pool/transaction_id, otherwise inserts.

        Returns:
            The id of the upserted record if successful, None if failed
        """
        try:
            # Get or create address_id
            address_query = "SELECT id FROM addresses WHERE address = %s"
            address_result = self.execute_query(address_query, (address,))

            if address_result:
                address_id = address_result[0]['id']
            else:
                user_id = self.execute_insert("INSERT INTO users DEFAULT VALUES RETURNING id", return_id=True)
                if not user_id:
                    print("Failed to create user")
                    return None

                address_id = self.execute_insert(
                    "INSERT INTO addresses (address, user_id, is_primary) VALUES (%s, %s, %s) RETURNING id",
                    (address, user_id, True),
                    return_id=True
                )
                if not address_id:
                    print("Failed to create address")
                    return None

            # Upsert historical record
            upsert_query = """
                INSERT INTO user_deposits_historical 
                (address_id, pool_nft, transaction_id, block_height, timestamp, total_deposited, total_withdrawn)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (address_id, pool_nft, transaction_id)
                DO UPDATE SET
                    block_height = EXCLUDED.block_height,
                    timestamp = EXCLUDED.timestamp,
                    total_deposited = EXCLUDED.total_deposited,
                    total_withdrawn = EXCLUDED.total_withdrawn
                RETURNING id
            """

            params = (address_id, pool_nft, transaction_id, block_height, timestamp, total_deposited, total_withdrawn)

            return self.execute_insert(upsert_query, params, return_id=True)

        except Exception as e:
            print(f"Error upserting user deposits historical: {e}")
            return None

    def upsert_user_portfolio_snapshot(self,
                                       address: str,
                                       pool_nft: str,
                                       block_height: int,
                                       timestamp: int,
                                       position_value: float,
                                       total_profit: float) -> Optional[int]:
        """
        Upsert a user portfolio snapshot record.
        Updates if a record exists for this address/pool/timestamp, otherwise inserts.

        Returns:
            The id of the upserted record if successful, None if failed
        """
        try:
            # Get or create address_id
            address_query = "SELECT id FROM addresses WHERE address = %s"
            address_result = self.execute_query(address_query, (address,))

            if address_result:
                address_id = address_result[0]['id']
            else:
                user_id = self.execute_insert("INSERT INTO users DEFAULT VALUES RETURNING id", return_id=True)
                if not user_id:
                    print("Failed to create user")
                    return None

                address_id = self.execute_insert(
                    "INSERT INTO addresses (address, user_id, is_primary) VALUES (%s, %s, %s) RETURNING id",
                    (address, user_id, True),
                    return_id=True
                )
                if not address_id:
                    print("Failed to create address")
                    return None

            # Upsert snapshot record
            upsert_query = """
                INSERT INTO user_portfolio_snapshots 
                (address_id, pool_nft, block_height, timestamp, position_value, total_profit)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (address_id, pool_nft, timestamp)
                DO UPDATE SET
                    block_height = EXCLUDED.block_height,
                    position_value = EXCLUDED.position_value,
                    total_profit = EXCLUDED.total_profit,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
            """

            params = (address_id, pool_nft, block_height, timestamp, position_value, total_profit)

            return self.execute_insert(upsert_query, params, return_id=True)

        except Exception as e:
            print(f"Error upserting user portfolio snapshot: {e}")
            return None