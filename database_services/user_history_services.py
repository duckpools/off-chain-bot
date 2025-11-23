from database.db_manager import DatabaseManager
from helpers.node_calls import get_block_timestamp
from helpers.platform_functions import get_all_boxes_by_token_id, fetch_transaction_data
from collections import defaultdict, OrderedDict
from typing import Dict, List, Tuple, Optional


def sync_user_lend_positions(
        db: DatabaseManager,  # Assuming DatabaseManager includes SyncMixin
        pool: dict,
        full_scan: bool = True,
        sync_block: Optional[int] = None
):
    """
    Sync user lend positions by processing all boxes for a pool's lend token
    and updating position_tokens based on transaction inputs/outputs.

    Args:
        db: Database manager instance (with SyncMixin methods)
        pool: Pool dictionary containing LEND_TOKEN, POOL_NFT, and pool address
        full_scan: If True, always scan from height 0. If False, use sync_block from DB if consistent
        sync_block: Optional block height to mark as the sync point for this update
    """
    # Get the lend token ID and pool NFT from the pool dict
    lend_token_id = pool["LEND_TOKEN"]
    pool_nft = pool["POOL_NFT"]
    pool_address = pool["pool"]

    # Determine the starting height (min_height) based on full_scan parameter
    if full_scan:
        min_height = 0
    else:
        # Check sync_block consistency for this pool in user_lend_positions_historical
        consistent_sync_block = db.get_pool_sync_block_for_table('user_lend_positions_historical', pool_nft)

        if consistent_sync_block is None:
            # Inconsistent sync_blocks found, need to do full scan
            min_height = 0
        else:
            # Use the consistent sync_block as min_height
            min_height = consistent_sync_block

    # Call: get_all_boxes_by_token_id with min_height
    boxes_response = get_all_boxes_by_token_id(lend_token_id, min_height=min_height)

    if not boxes_response:
        return

    # Step 1: Collect all transaction data and sort chronologically
    transactions_data = []
    unique_block_heights = set()
    seen_transactions = set()  # Track processed transaction IDs
    max_block_height = min_height  # Track the maximum block height processed

    for box_item in boxes_response:
        transaction_id = box_item["transactionId"]

        # Skip if we've already processed this transaction
        if transaction_id in seen_transactions:
            continue
        seen_transactions.add(transaction_id)

        # Fetch transaction data
        transaction_data = fetch_transaction_data(transaction_id)

        if not transaction_data:
            print(f"Failed to fetch transaction data for {transaction_id}")
            continue

        block_height = transaction_data.get("inclusionHeight", 0)
        timestamp = transaction_data.get("timestamp", 0)

        # Skip transactions at or below min_height (already processed)
        if block_height <= min_height:
            continue

        # Track maximum block height for sync_block if not provided
        max_block_height = max(max_block_height, block_height)

        transactions_data.append({
            'transaction_id': transaction_id,
            'block_height': block_height,
            'timestamp': timestamp,
            'transaction_data': transaction_data
        })

        unique_block_heights.add(block_height)

    # Sort transactions chronologically
    transactions_data.sort(key=lambda x: (x['block_height'], x['timestamp']))

    # Determine the actual sync_block to use
    if sync_block is None:
        sync_block = max_block_height

    # Step 2: Batch query for pool data (lend token values)
    pool_data_map = db.get_pool_data_batch(pool_nft, list(unique_block_heights))

    # Step 3: Get initial positions for all addresses that will be affected
    all_affected_addresses = set()

    # First pass: collect all addresses that will be affected
    for tx_data in transactions_data:
        transaction_data = tx_data['transaction_data']

        # Process inputs and outputs to find affected addresses
        for input_box in transaction_data.get("inputs", []):
            address = input_box.get("address")
            if address and address != pool_address:
                # Check if this input has lend tokens
                for asset in input_box.get("assets", []):
                    if asset.get("tokenId") == lend_token_id:
                        all_affected_addresses.add(address)
                        break

        for output_box in transaction_data.get("outputs", []):
            address = output_box.get("address")
            if address and address != pool_address:
                # Check if this output has lend tokens
                for asset in output_box.get("assets", []):
                    if asset.get("tokenId") == lend_token_id:
                        all_affected_addresses.add(address)
                        break

    # Step 4: Get initial positions for all affected addresses
    address_pool_pairs = [(addr, pool_nft) for addr in all_affected_addresses]

    # FIX: Don't load positions from DB during full_scan to avoid corruption
    if full_scan or min_height == 0:
        # Full scan starts from 0, ignore existing DB data
        initial_positions = {}
    else:
        # Incremental sync: load existing positions from DB
        initial_positions = db.get_latest_positions_batch(address_pool_pairs)

    # Step 5: Process all transactions chronologically and build final dataset
    current_positions = defaultdict(float)  # {address: current_position_tokens}
    final_batch_data = []  # List of (address, pool_nft, block_height, timestamp, position_tokens, position_value, sync_block)

    # Initialize current positions with database values (or 0 for full_scan)
    for address in all_affected_addresses:
        initial_position = float(initial_positions.get((address, pool_nft), 0))
        current_positions[address] = initial_position

    for i, tx_data in enumerate(transactions_data):
        transaction_id = tx_data['transaction_id']
        block_height = tx_data['block_height']
        timestamp = tx_data['timestamp']
        transaction_data = tx_data['transaction_data']

        # Track position changes per address for this transaction
        address_inputs = defaultdict(float)  # {address: total_input_tokens}
        address_outputs = defaultdict(float)  # {address: total_output_tokens}

        # Process inputs - collect total input tokens per address
        for input_box in transaction_data.get("inputs", []):
            address = input_box.get("address")

            if not address or address == pool_address:
                continue

            # Sum up lend token amounts in this input box
            lend_token_amount = 0.0
            for asset in input_box.get("assets", []):
                if asset.get("tokenId") == lend_token_id:
                    amount = asset.get("amount", 0)
                    # Ensure amount is float regardless of input type
                    lend_token_amount += float(amount) if amount is not None else 0.0

            if lend_token_amount > 0:
                address_inputs[address] += lend_token_amount

        # Process outputs - collect total output tokens per address
        for output_box in transaction_data.get("outputs", []):
            address = output_box.get("address")

            if not address or address == pool_address:
                continue

            # Sum up lend token amounts in this output box
            lend_token_amount = 0.0
            for asset in output_box.get("assets", []):
                if asset.get("tokenId") == lend_token_id:
                    amount = asset.get("amount", 0)
                    # Ensure amount is float regardless of input type
                    lend_token_amount += float(amount) if amount is not None else 0.0

            if lend_token_amount > 0:
                address_outputs[address] += lend_token_amount

        # Calculate net changes: outputs - inputs for each address
        all_addresses_in_tx = set(address_inputs.keys()) | set(address_outputs.keys())
        address_changes = {}

        for address in all_addresses_in_tx:
            inputs = address_inputs.get(address, 0.0)
            outputs = address_outputs.get(address, 0.0)
            net_change = outputs - inputs
            if net_change != 0:
                address_changes[address] = net_change

        # Update positions for each affected address in this transaction
        for address, net_change in address_changes.items():
            if net_change == 0:
                continue

            # Update current position using local tracking
            current_positions[address] += net_change
            new_position_tokens = current_positions[address]

            # Divide position_tokens by lend token decimals (same as pool asset decimals)
            decimals = pool["decimals"]
            new_position_tokens_friendly = new_position_tokens / (10 ** decimals)

            # Get lend token value for this block height
            lend_token_value = pool_data_map.get(block_height, -1)

            if lend_token_value != -1:
                # Calculate position_value using friendly position_tokens
                position_value = new_position_tokens_friendly * float(lend_token_value)
            else:
                position_value = -1

            # Add to batch data - use the determined sync_block
            final_batch_data.append((
                address,
                pool_nft,
                block_height,
                timestamp,
                new_position_tokens_friendly,
                position_value,
                sync_block
            ))

    # Step 6: Consolidate duplicates before batch insert
    # Since constraint is (address_id, pool_nft, block_height), we need to keep only the latest
    # record for each address/pool/block combination
    if final_batch_data:
        # Group by (address, pool_nft, block_height) and keep the latest timestamp
        consolidated_data = {}
        for record in final_batch_data:
            address, pool_nft, block_height, timestamp, position_tokens, position_value, record_sync_block = record
            key = (address, pool_nft, block_height)

            # Keep the record with the latest timestamp (final state for that block)
            if key not in consolidated_data or timestamp >= consolidated_data[key][3]:
                consolidated_data[key] = record

        final_consolidated_data = list(consolidated_data.values())
        successful_inserts = db.batch_upsert_user_lend_positions_historical(final_consolidated_data, sync_block)


def sync_user_deposits_historical(db: DatabaseManager, pool, sync_block: Optional[int] = None, full_scan: int = False) -> bool:
    """
    Synchronize user deposits historical data for a specific pool.
    Processes all transactions for the pool in block height order and calculates
    cumulative deposit/withdrawal amounts for each user.
    Note: Transactions amounts and fees are already divided by decimals when stored.
    """
    pool_nft = pool["POOL_NFT"]

    try:
        min_height = 0
        if not full_scan:
            min_height = db.get_lowest_sync_block_for_pool(
                table_name="user_deposits_historical",
                pool_nft=pool_nft
            )

        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # 2) Pull transactions at/after that baseline min height
                transaction_query = """
                    SELECT t.id, t.address_id, t.type, t.amount, t.fee_paid,
                           t.block_height, t.timestamp, a.address
                    FROM transactions t
                    JOIN addresses a ON t.address_id = a.id
                    WHERE t.pool_nft = %s
                      AND t.block_height >= %s
                    ORDER BY t.block_height ASC, t.id ASC
                """

                cur.execute(transaction_query, (pool_nft, min_height))
                transactions = cur.fetchall()

                if not transactions:
                    return True

                # Track cumulative amounts per address
                user_totals = {}  # address -> {'deposited': float, 'withdrawn': float}

                # Process each transaction in chronological order
                for tx in transactions:
                    tx_id, address_id, tx_type, amount, fee_paid, block_height, timestamp, address = tx

                    # Initialize user totals if first time seeing this address
                    if address not in user_totals:
                        user_totals[address] = {'deposited': 0.0, 'withdrawn': 0.0}

                    # Handle different transaction types
                    # Note: amount and fee_paid are already user-friendly values (divided by decimals)
                    fee = fee_paid if fee_paid is not None else 0

                    if tx_type == 'lend':
                        # For lend transactions: deposited amount increases by amount + fee
                        user_totals[address]['deposited'] += float(amount) + float(fee)
                    elif tx_type == 'withdraw':
                        # For withdraw transactions: withdrawn amount increases by amount - fee
                        user_totals[address]['withdrawn'] += float(amount) - float(fee)
                    # Note: Other transaction types (borrow, repayment, etc.) don't affect deposit/withdrawal totals

                    # Only create historical entries for lend and withdraw transactions
                    if tx_type in ('lend', 'withdraw'):
                        result = db.upsert_user_deposits_historical(
                            address=address,
                            pool_nft=pool_nft,
                            transaction_id=tx_id,
                            block_height=block_height,
                            timestamp=timestamp,
                            total_deposited=user_totals[address]['deposited'],
                            total_withdrawn=user_totals[address]['withdrawn'],
                            sync_block=sync_block or block_height  # Use block_height as sync_block if not provided
                        )

                        if result is None:
                            print(f"Failed to upsert historical record for transaction {tx_id}")
                            return False

                print(f"Successfully synced {len(transactions)} transactions for pool {pool_nft} (from height {min_height})")
                return True

    except Exception as e:
        print(f"Error syncing user deposits historical for pool {pool_nft}: {e}")
        return False


def sync_user_portfolio_snapshots(db: DatabaseManager, pool, sync_block: Optional[int] = None) -> bool:
    """
    Alternative optimized version that does all the work in a single SQL operation.
    This is the fastest approach as it avoids Python loops entirely.

    Args:
        db: Database manager instance
        pool: Pool configuration dictionary
        sync_block: Block height when this data was synced

    Returns:
        True if sync was successful, False otherwise
    """
    pool_nft = pool["POOL_NFT"]

    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Single SQL operation that calculates and upserts all snapshots
                # Uses DISTINCT ON to handle duplicate (address_id, pool_nft, timestamp) combinations
                bulk_upsert_query = """
                    INSERT INTO user_portfolio_snapshots 
                    (address_id, pool_nft, block_height, timestamp, position_value, total_profit, sync_block)
                    SELECT DISTINCT ON (address_id, pool_nft, timestamp)
                        lp.address_id,
                        lp.pool_nft,
                        lp.block_height,
                        lp.timestamp,
                        lp.position_value,
                        lp.position_value + COALESCE(dh.total_withdrawn, 0) - COALESCE(dh.total_deposited, 0) as total_profit,
                        %s as sync_block
                    FROM user_lend_positions_historical lp
                    LEFT JOIN LATERAL (
                        SELECT 
                            total_deposited,
                            total_withdrawn
                        FROM user_deposits_historical udh
                        WHERE udh.address_id = lp.address_id 
                        AND udh.pool_nft = lp.pool_nft
                        AND udh.block_height <= lp.block_height
                        ORDER BY udh.block_height DESC, udh.id DESC
                        LIMIT 1
                    ) dh ON true
                    WHERE lp.pool_nft = %s
                    ORDER BY address_id, pool_nft, timestamp, lp.block_height DESC, lp.id DESC
                    ON CONFLICT (address_id, pool_nft, timestamp)
                    DO UPDATE SET
                        block_height = EXCLUDED.block_height,
                        position_value = EXCLUDED.position_value,
                        total_profit = EXCLUDED.total_profit,
                        sync_block = EXCLUDED.sync_block,
                        updated_at = CURRENT_TIMESTAMP
                """

                cur.execute(bulk_upsert_query, (sync_block, pool_nft))
                rows_affected = cur.rowcount
                conn.commit()

                return True

    except Exception as e:
        print(f"Error syncing user portfolio snapshots for pool {pool_nft}: {e}")
        return False


def get_pool_lend_token_value_map(db: DatabaseManager, pool_nft: str) -> dict:
    """
    Fetches all lend_token_value data from pool_data_historical for a specific pool.
    Returns a map of {block_height: lend_token_value} where the value is constant between updates.

    Args:
        db: Database manager instance
        pool_nft: The pool NFT identifier

    Returns:
        Dictionary mapping block heights to lend token values
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                query = """
                    SELECT block_height, lend_token_value
                    FROM pool_data_historical
                    WHERE pool_nft = %s
                    ORDER BY block_height ASC
                """

                cur.execute(query, (pool_nft,))
                results = cur.fetchall()

                if not results:
                    print(f"No pool data historical found for pool {pool_nft}")
                    return {}

                # Create a map where each block height maps to its lend token value
                value_map = {}
                for block_height, lend_token_value in results:
                    value_map[block_height] = float(lend_token_value)

                print(f"Retrieved lend token values for {len(value_map)} block heights for pool {pool_nft}")
                return value_map

    except Exception as e:
        print(f"Error fetching pool lend token value map for pool {pool_nft}: {e}")
        return {}


def get_lend_token_value_at_height(value_map: dict, target_height: int) -> float:
    """
    Gets the lend token value at a specific block height.
    Since values are constant between updates, finds the most recent value <= target_height.

    Args:
        value_map: Dictionary of {block_height: lend_token_value}
        target_height: The block height to get value for

    Returns:
        The lend token value at that height, or -1 if not found
    """
    if not value_map:
        return -1

    # Find the highest block height that is <= target_height
    valid_heights = [h for h in value_map.keys() if h <= target_height]

    if not valid_heights:
        return -1

    # Return the value at the most recent height
    most_recent_height = max(valid_heights)
    return value_map[most_recent_height]


def add_granular_user_lend_positions(
        db: DatabaseManager,
        pool: dict,
        interval_blocks: int = 5000,
        sync_block: int = 0,
        full_scan: bool = True,
) -> bool:
    """
    Add granular user positions using REAL block timestamps from the node API.
    Correctly handles positions that go 0 → positive → 0 throughout time.
    """
    pool_nft = pool["POOL_NFT"]

    try:
        # Step 1: Get the lend token value map
        print(f"Fetching lend token value map for pool {pool_nft}")
        value_map = get_pool_lend_token_value_map(db, pool_nft)
        if not value_map:
            print(f"No lend token value data available for pool {pool_nft}")
            return False

        # Step 2: Generate interval heights
        min_height = min(value_map.keys())
        if not full_scan:
            min_height = db.get_lowest_sync_block_for_pool("user_lend_positions_historical", pool_nft)
        print("Using min_height", min_height)

        max_height = max(max(value_map.keys()), sync_block)
        interval_heights = []
        current_height = min_height + interval_blocks
        while current_height <= max_height:
            interval_heights.append(current_height)
            current_height += interval_blocks

        print(f"Generated {len(interval_heights)} interval heights every {interval_blocks} blocks")

        if not interval_heights:
            return True

        with db.get_connection() as conn:
            with conn.cursor() as cur:
                batch_data = []

                for interval_height in interval_heights:
                    print(f"Processing interval height {interval_height}")

                    # Get REAL block timestamp from node API
                    block_timestamp = get_block_timestamp(interval_height)
                    if block_timestamp is None:
                        print(f"  Failed to get timestamp for block {interval_height}, skipping")
                        continue

                    # Get lend token value for this height
                    lend_token_value = get_lend_token_value_at_height(value_map, interval_height)
                    if lend_token_value == -1:
                        print(f"  No lend token value available for height {interval_height}, skipping")
                        continue

                    print(f"  Using lend_token_value: {lend_token_value}")
                    print(f"  Using REAL block_timestamp: {block_timestamp}")

                    # FIXED QUERY: Get truly latest position first, then filter for active positions
                    user_query = """
                    WITH latest_positions AS (
                        SELECT DISTINCT 
                            lp.address_id, 
                            a.address,
                            FIRST_VALUE(lp.position_tokens) OVER (
                                PARTITION BY lp.address_id 
                                ORDER BY lp.block_height DESC, lp.id DESC 
                                ROWS UNBOUNDED PRECEDING
                            ) as latest_position_tokens
                        FROM user_lend_positions_historical lp
                        JOIN addresses a ON lp.address_id = a.id
                        WHERE lp.pool_nft = %s AND lp.block_height <= %s
                    )
                    SELECT address_id, address, latest_position_tokens
                    FROM latest_positions
                    WHERE latest_position_tokens > 0
                    """

                    cur.execute(user_query, (pool_nft, interval_height))
                    user_positions = cur.fetchall()

                    print(f"  Found {len(user_positions)} users with active positions")

                    # Create position records with REAL node API timestamps
                    for address_id, address, position_tokens in user_positions:
                        position_tokens = float(position_tokens)
                        # position_tokens from DB is already divided by decimals, so position_value calculation stays the same
                        position_value = position_tokens * lend_token_value

                        batch_data.append((
                            address,
                            pool_nft,
                            interval_height,
                            block_timestamp,  # REAL timestamp from node API!
                            position_tokens,
                            position_value,
                            sync_block
                        ))

                print("This is my batch data", batch_data)
                print(f"Generated {len(batch_data)} granular position records with REAL timestamps")

                if batch_data:
                    print("Performing batch upsert of granular positions...")
                    successful_inserts = db.batch_upsert_user_lend_positions_historical(batch_data, sync_block)
                    print(f"Successfully inserted {successful_inserts} granular position records")
                    return successful_inserts == len(batch_data)
                else:
                    print("No granular records to insert")
                    return True

    except Exception as e:
        print(f"Error adding granular user lend positions for pool {pool_nft}: {e}")
        return False