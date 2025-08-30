from typing import Optional, List, Tuple, Dict
from .core import CoreDB


class HistoryMixin:
    def upsert_user_lend_position_historical(self,
                                             address: str,
                                             pool_nft: str,
                                             block_height: int,
                                             timestamp: int,
                                             position_tokens: float,
                                             position_value: float,
                                             sync_block: Optional[int] = None) -> Optional[int]:
        """
        Upsert a user lend position historical record.
        Updates if a record exists for this address/pool/block_height, otherwise inserts.

        Returns:
            The id of the upserted record if successful, None if failed
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # Get or create address_id in a single transaction
                    address_query = "SELECT id FROM addresses WHERE address = %s"
                    cur.execute(address_query, (address,))
                    address_result = cur.fetchone()

                    if address_result:
                        address_id = address_result[0]
                    else:
                        # Create user first
                        cur.execute("INSERT INTO users (sync_block) VALUES (%s) RETURNING id", (sync_block,))
                        user_result = cur.fetchone()
                        if not user_result:
                            print("Failed to create user")
                            return None
                        user_id = user_result[0]

                        # Create address
                        cur.execute(
                            "INSERT INTO addresses (address, user_id, is_primary, sync_block) VALUES (%s, %s, %s, %s) RETURNING id",
                            (address, user_id, True, sync_block)
                        )
                        address_result = cur.fetchone()
                        if not address_result:
                            print("Failed to create address")
                            return None
                        address_id = address_result[0]

                    # Upsert historical record
                    upsert_query = """
                        INSERT INTO user_lend_positions_historical 
                        (address_id, pool_nft, block_height, timestamp, position_tokens, position_value, sync_block)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (address_id, pool_nft, block_height)
                        DO UPDATE SET
                            timestamp = EXCLUDED.timestamp,
                            position_tokens = EXCLUDED.position_tokens,
                            position_value = EXCLUDED.position_value,
                            sync_block = EXCLUDED.sync_block
                        RETURNING id
                    """

                    params = (address_id, pool_nft, block_height, timestamp, position_tokens, position_value, sync_block)

                    cur.execute(upsert_query, params)
                    result = cur.fetchone()

                    conn.commit()
                    return result[0] if result else None

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
                                        total_withdrawn: float,
                                        sync_block: Optional[int] = None) -> Optional[int]:
        """
        Upsert a user deposits historical record.
        Updates if a record exists for this address/pool/transaction_id, otherwise inserts.

        Returns:
            The id of the upserted record if successful, None if failed
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # Get or create address_id in a single transaction
                    address_query = "SELECT id FROM addresses WHERE address = %s"
                    cur.execute(address_query, (address,))
                    address_result = cur.fetchone()

                    if address_result:
                        address_id = address_result[0]
                    else:
                        # Create user first
                        cur.execute("INSERT INTO users (sync_block) VALUES (%s) RETURNING id", (sync_block,))
                        user_result = cur.fetchone()
                        if not user_result:
                            print("Failed to create user")
                            return None
                        user_id = user_result[0]

                        # Create address
                        cur.execute(
                            "INSERT INTO addresses (address, user_id, is_primary, sync_block) VALUES (%s, %s, %s, %s) RETURNING id",
                            (address, user_id, True, sync_block)
                        )
                        address_result = cur.fetchone()
                        if not address_result:
                            print("Failed to create address")
                            return None
                        address_id = address_result[0]

                    # Upsert historical record
                    upsert_query = """
                        INSERT INTO user_deposits_historical 
                        (address_id, pool_nft, transaction_id, block_height, timestamp, total_deposited, total_withdrawn, sync_block)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (address_id, pool_nft, transaction_id)
                        DO UPDATE SET
                            block_height = EXCLUDED.block_height,
                            timestamp = EXCLUDED.timestamp,
                            total_deposited = EXCLUDED.total_deposited,
                            total_withdrawn = EXCLUDED.total_withdrawn,
                            sync_block = EXCLUDED.sync_block
                        RETURNING id
                    """

                    params = (
                        address_id, pool_nft, transaction_id, block_height, timestamp, total_deposited, total_withdrawn, sync_block)

                    cur.execute(upsert_query, params)
                    result = cur.fetchone()

                    conn.commit()
                    return result[0] if result else None

        except Exception as e:
            print(f"Error upserting user deposits historical: {e}")
            return None

    def upsert_user_portfolio_snapshot(self,
                                       address: str,
                                       pool_nft: str,
                                       block_height: int,
                                       timestamp: int,
                                       position_value: float,
                                       total_profit: float,
                                       sync_block: Optional[int] = None) -> Optional[int]:
        """
        Upsert a user portfolio snapshot record.
        Updates if a record exists for this address/pool/timestamp, otherwise inserts.

        Returns:
            The id of the upserted record if successful, None if failed
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # Get or create address_id in a single transaction
                    address_query = "SELECT id FROM addresses WHERE address = %s"
                    cur.execute(address_query, (address,))
                    address_result = cur.fetchone()

                    if address_result:
                        address_id = address_result[0]
                    else:
                        # Create user first
                        cur.execute("INSERT INTO users (sync_block) VALUES (%s) RETURNING id", (sync_block,))
                        user_result = cur.fetchone()
                        if not user_result:
                            print("Failed to create user")
                            return None
                        user_id = user_result[0]

                        # Create address
                        cur.execute(
                            "INSERT INTO addresses (address, user_id, is_primary, sync_block) VALUES (%s, %s, %s, %s) RETURNING id",
                            (address, user_id, True, sync_block)
                        )
                        address_result = cur.fetchone()
                        if not address_result:
                            print("Failed to create address")
                            return None
                        address_id = address_result[0]

                    # Upsert snapshot record
                    upsert_query = """
                        INSERT INTO user_portfolio_snapshots 
                        (address_id, pool_nft, block_height, timestamp, position_value, total_profit, sync_block)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (address_id, pool_nft, timestamp)
                        DO UPDATE SET
                            block_height = EXCLUDED.block_height,
                            position_value = EXCLUDED.position_value,
                            total_profit = EXCLUDED.total_profit,
                            sync_block = EXCLUDED.sync_block,
                            updated_at = CURRENT_TIMESTAMP
                        RETURNING id
                    """

                    params = (address_id, pool_nft, block_height, timestamp, position_value, total_profit, sync_block)

                    cur.execute(upsert_query, params)
                    result = cur.fetchone()

                    conn.commit()
                    return result[0] if result else None

        except Exception as e:
            print(f"Error upserting user portfolio snapshot: {e}")
            return None

    def get_pool_data_batch(self, pool_nft: str, block_heights: List[int]) -> Dict[int, float]:
        """
        Batch query to get lend_token_value for multiple block heights.
        Returns a dict mapping block_height to lend_token_value.
        """
        if not block_heights:
            return {}

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # Create a subquery for each block height to find the highest available block <= target
                    placeholders = ','.join(['%s'] * len(block_heights))
                    query = f"""
                        WITH block_values AS (
                            SELECT 
                                target_height,
                                COALESCE(
                                    (SELECT lend_token_value 
                                     FROM pool_data_historical 
                                     WHERE pool_nft = %s 
                                     AND block_height <= target_height 
                                     AND lend_token_value IS NOT NULL
                                     ORDER BY block_height DESC 
                                     LIMIT 1), 
                                    -1
                                ) as lend_token_value
                            FROM UNNEST(ARRAY[{placeholders}]) AS target_height
                        )
                        SELECT target_height, lend_token_value 
                        FROM block_values
                    """

                    params = [pool_nft] + block_heights
                    cur.execute(query, params)
                    results = cur.fetchall()

                    # Convert Decimal values to float for consistent typing
                    return {row[0]: float(row[1]) if row[1] != -1 else -1 for row in results}

        except Exception as e:
            print(f"Error fetching pool data batch: {e}")
            return {}

    def get_latest_positions_batch(self, address_pool_pairs: List[Tuple[str, str]]) -> Dict[Tuple[str, str], float]:
        """
        Batch query to get the latest position_tokens for multiple address/pool pairs.
        Returns a dict mapping (address, pool_nft) to position_tokens.
        """
        if not address_pool_pairs:
            return {}

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # Build a query to get latest position for each address/pool pair
                    case_conditions = []
                    params = []

                    for i, (address, pool_nft) in enumerate(address_pool_pairs):
                        case_conditions.append(
                            f"WHEN addresses.address = ${len(params) + 1} AND ulph.pool_nft = ${len(params) + 2}")
                        params.extend([address, pool_nft])

                    if not case_conditions:
                        return {}

                    # Use a different approach with joins
                    pairs_values = []
                    for address, pool_nft in address_pool_pairs:
                        pairs_values.append(f"('{address}', '{pool_nft}')")

                    query = f"""
                        WITH address_pool_pairs AS (
                            SELECT * FROM (VALUES {','.join(pairs_values)}) AS t(address, pool_nft)
                        ),
                        latest_positions AS (
                            SELECT 
                                app.address,
                                app.pool_nft,
                                COALESCE(
                                    (SELECT position_tokens 
                                     FROM user_lend_positions_historical ulph
                                     JOIN addresses a ON ulph.address_id = a.id
                                     WHERE a.address = app.address 
                                     AND ulph.pool_nft = app.pool_nft
                                     ORDER BY ulph.block_height DESC, ulph.timestamp DESC 
                                     LIMIT 1), 
                                    0
                                ) as position_tokens
                            FROM address_pool_pairs app
                        )
                        SELECT address, pool_nft, position_tokens 
                        FROM latest_positions
                    """

                    cur.execute(query)
                    results = cur.fetchall()

                    # Convert Decimal values to float for consistent typing
                    return {(row[0], row[1]): float(row[2]) for row in results}

        except Exception as e:
            print(f"Error fetching latest positions batch: {e}")
            return {}

    def batch_upsert_user_lend_positions_historical(self, batch_data: List[Tuple], sync_block: Optional[int] = None) -> int:
        """
        Batch upsert user lend position historical records.

        Args:
            batch_data: List of tuples containing (address, pool_nft, block_height, timestamp, position_tokens, position_value)
            sync_block: Block height when this data was synced (applied to all records if not provided in batch_data)

        Returns:
            Number of records successfully processed
        """
        if not batch_data:
            return 0

        successful_inserts = 0

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # First, ensure all addresses exist and get their IDs
                    unique_addresses = list(set(item[0] for item in batch_data))
                    address_id_map = {}

                    for address in unique_addresses:
                        # Get or create address_id
                        address_query = "SELECT id FROM addresses WHERE address = %s"
                        cur.execute(address_query, (address,))
                        address_result = cur.fetchone()

                        if address_result:
                            address_id_map[address] = address_result[0]
                        else:
                            # Create user first
                            cur.execute("INSERT INTO users (sync_block) VALUES (%s) RETURNING id", (sync_block,))
                            user_result = cur.fetchone()
                            if not user_result:
                                print(f"Failed to create user for address {address}")
                                continue
                            user_id = user_result[0]

                            # Create address
                            cur.execute(
                                "INSERT INTO addresses (address, user_id, is_primary, sync_block) VALUES (%s, %s, %s, %s) RETURNING id",
                                (address, user_id, True, sync_block)
                            )
                            address_result = cur.fetchone()
                            if not address_result:
                                print(f"Failed to create address {address}")
                                continue
                            address_id_map[address] = address_result[0]

                    # Convert to use address_ids and sort chronologically
                    processed_data = []
                    for item in batch_data:
                        if len(item) >= 6:  # address, pool_nft, block_height, timestamp, position_tokens, position_value
                            address, pool_nft, block_height, timestamp, position_tokens, position_value = item[:6]
                            # Check if sync_block is included in the tuple, otherwise use the passed parameter
                            item_sync_block = item[6] if len(item) > 6 else sync_block
                        else:
                            print(f"Invalid batch_data item: {item}")
                            continue

                        if address in address_id_map:
                            processed_data.append((
                                address_id_map[address],
                                pool_nft,
                                block_height,
                                timestamp,
                                position_tokens,
                                position_value,
                                item_sync_block
                            ))

                    # Sort by block_height, then timestamp to ensure chronological order
                    processed_data.sort(key=lambda x: (x[2], x[3]))

                    if processed_data:
                        # Batch upsert using execute_values for better performance
                        from psycopg2.extras import execute_values

                        upsert_query = """
                            INSERT INTO user_lend_positions_historical 
                            (address_id, pool_nft, block_height, timestamp, position_tokens, position_value, sync_block)
                            VALUES %s
                            ON CONFLICT (address_id, pool_nft, block_height)
                            DO UPDATE SET
                                timestamp = EXCLUDED.timestamp,
                                position_tokens = EXCLUDED.position_tokens,
                                position_value = EXCLUDED.position_value,
                                sync_block = EXCLUDED.sync_block
                        """

                        execute_values(
                            cur,
                            upsert_query,
                            processed_data,
                            template=None,
                            page_size=1000
                        )

                        successful_inserts = len(processed_data)

                    conn.commit()
                    return successful_inserts

        except Exception as e:
            print(f"Error in batch upsert user lend positions historical: {e}")
            return 0