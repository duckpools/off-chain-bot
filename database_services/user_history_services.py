from database.db_manager import DatabaseManager
from helpers.platform_functions import get_all_boxes_by_token_id, fetch_transaction_data
from collections import defaultdict, OrderedDict
from typing import Dict, List, Tuple


def sync_user_lend_positions(
        db: DatabaseManager,
        pool: dict,
        min_height: int = 0  # we will ignore this for now and implement the height logic later
):
    """
    Sync user lend positions by processing all boxes for a pool's lend token
    and updating position_tokens based on transaction inputs/outputs.
    Now with batch processing for maximum efficiency.
    """
    # Get the lend token ID and pool NFT from the pool dict
    lend_token_id = pool["LEND_TOKEN"]
    pool_nft = pool["POOL_NFT"]
    pool_address = pool["pool"]

    print(f"Starting sync for pool {pool_nft} with lend token {lend_token_id}")
    print(f"Pool address: {pool_address}")
    print(f"Pool address length: {len(pool_address)}")

    # Call: get_all_boxes_by_token_id(pool["LEND_TOKEN"])
    boxes_response = get_all_boxes_by_token_id(lend_token_id)

    if not boxes_response:
        print("No boxes found or invalid response")
        return

    print(f"Found {len(boxes_response)} boxes to process")

    # Step 1: Collect all transaction data and sort chronologically
    transactions_data = []
    unique_block_heights = set()
    seen_transactions = set()  # Track processed transaction IDs

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

        transactions_data.append({
            'transaction_id': transaction_id,
            'block_height': block_height,
            'timestamp': timestamp,
            'transaction_data': transaction_data
        })

        unique_block_heights.add(block_height)

    # Sort transactions chronologically
    transactions_data.sort(key=lambda x: (x['block_height'], x['timestamp']))

    print(f"Collected {len(transactions_data)} transactions, {len(unique_block_heights)} unique block heights")

    # Step 2: Batch query for pool data (lend token values)
    pool_data_map = db.get_pool_data_batch(pool_nft, list(unique_block_heights))
    print(f"Retrieved lend token values for {len(pool_data_map)} block heights")

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

    print(f"Found {len(all_affected_addresses)} addresses affected by transactions")

    # Step 4: Get initial positions for all affected addresses
    address_pool_pairs = [(addr, pool_nft) for addr in all_affected_addresses]
    initial_positions = db.get_latest_positions_batch(address_pool_pairs)

    # Step 5: Process all transactions chronologically and build final dataset
    current_positions = defaultdict(float)  # {address: current_position_tokens}
    final_batch_data = []  # List of (address, pool_nft, block_height, timestamp, position_tokens, position_value)

    # Initialize current positions with database values
    for address in all_affected_addresses:
        current_positions[address] = float(initial_positions.get((address, pool_nft), 0))

    print("Processing transactions chronologically...")

    for i, tx_data in enumerate(transactions_data):
        transaction_id = tx_data['transaction_id']
        block_height = tx_data['block_height']
        timestamp = tx_data['timestamp']
        transaction_data = tx_data['transaction_data']

        if i % 100 == 0:
            print(f"Processing transaction {i + 1}/{len(transactions_data)} - {transaction_id}")

        # Track position changes per address for this transaction
        address_inputs = defaultdict(float)  # {address: total_input_tokens}
        address_outputs = defaultdict(float)  # {address: total_output_tokens}

        # Debug: Track all addresses in this transaction
        tx_addresses = set()

        # Process inputs - collect total input tokens per address
        for input_box in transaction_data.get("inputs", []):
            address = input_box.get("address")
            tx_addresses.add(address)

            if not address or address == pool_address:
                if address == pool_address:
                    print(f"  SKIPPING pool address in inputs: {address[:50]}...")
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
                print(f"  INPUT: {address[:20]}... = {lend_token_amount}")

        # Process outputs - collect total output tokens per address
        for output_box in transaction_data.get("outputs", []):
            address = output_box.get("address")
            tx_addresses.add(address)

            if not address or address == pool_address:
                if address == pool_address:
                    print(f"  SKIPPING pool address in outputs: {address[:50]}...")
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
                print(f"  OUTPUT: {address[:20]}... = {lend_token_amount}")

        # Debug: Print all unique addresses in this transaction
        print(f"  All addresses in tx: {[addr[:20] + '...' if addr else 'None' for addr in tx_addresses]}")
        print(f"  Pool address matches: {[addr == pool_address for addr in tx_addresses]}")

        # Calculate net changes: outputs - inputs for each address
        all_addresses_in_tx = set(address_inputs.keys()) | set(address_outputs.keys())
        address_changes = {}

        for address in all_addresses_in_tx:
            inputs = address_inputs.get(address, 0.0)
            outputs = address_outputs.get(address, 0.0)
            net_change = outputs - inputs
            if net_change != 0:
                address_changes[address] = net_change
                print(f"  NET CHANGE: {address[:20]}... = {net_change} (inputs: {inputs}, outputs: {outputs})")

        # Update positions for each affected address in this transaction
        for address, net_change in address_changes.items():
            if net_change == 0:
                continue

            # Update current position using local tracking
            current_positions[address] += net_change
            new_position_tokens = current_positions[address]

            # Get lend token value for this block height
            lend_token_value = pool_data_map.get(block_height, -1)

            if lend_token_value != -1:
                # Ensure both values are float for multiplication
                position_value = new_position_tokens * float(lend_token_value)
            else:
                position_value = -1

            # Add to batch data
            final_batch_data.append((
                address,
                pool_nft,
                block_height,
                timestamp,
                new_position_tokens,
                position_value
            ))

    print(f"Generated {len(final_batch_data)} position updates")

    # Step 6: Consolidate duplicates before batch insert
    # Since constraint is (address_id, pool_nft, block_height), we need to keep only the latest
    # record for each address/pool/block combination
    if final_batch_data:
        print("Consolidating duplicate records...")

        # Group by (address, pool_nft, block_height) and keep the latest timestamp
        consolidated_data = {}
        for record in final_batch_data:
            address, pool_nft, block_height, timestamp, position_tokens, position_value = record
            key = (address, pool_nft, block_height)

            # Keep the record with the latest timestamp (final state for that block)
            if key not in consolidated_data or timestamp >= consolidated_data[key][3]:
                consolidated_data[key] = record

        final_consolidated_data = list(consolidated_data.values())
        print(f"Consolidated to {len(final_consolidated_data)} unique records")

        print("Performing batch upsert...")
        successful_inserts = db.batch_upsert_user_lend_positions_historical(final_consolidated_data)
        print(f"Successfully inserted/updated {successful_inserts} position records")
    else:
        print("No position updates to perform")

    print("Sync completed")