from database.db_manager import DatabaseManager
from helpers.platform_functions import get_all_boxes_by_token_id, fetch_transaction_data


def sync_user_lend_positions(
        db: DatabaseManager,
        pool: dict,
        min_height: int = 0  # we will ignore this for now and implement the height logic later
):
    """
    Sync user lend positions by processing all boxes for a pool's lend token
    and updating position_tokens based on transaction inputs/outputs.
    """
    # Get the lend token ID and pool NFT from the pool dict
    lend_token_id = pool["LEND_TOKEN"]
    pool_nft = pool["POOL_NFT"]

    # Call: get_all_boxes_by_token_id(pool["LEND_TOKEN"])
    boxes_response = get_all_boxes_by_token_id(lend_token_id)

    if not boxes_response:
        print("No boxes found or invalid response")
        return

    # Process each box
    for box_item in boxes_response:
        transaction_id = box_item["transactionId"]

        # Fetch transaction data
        transaction_data = fetch_transaction_data(transaction_id)

        if not transaction_data:
            print(f"Failed to fetch transaction data for {transaction_id}")
            continue

        block_height = transaction_data.get("inclusionHeight", 0)
        timestamp = transaction_data.get("timestamp", 0)

        # Track position changes per address for this transaction
        address_changes = {}  # {address: net_token_change}

        # Process inputs (subtract tokens from addresses)
        for input_box in transaction_data.get("inputs", []):
            address = input_box.get("address")
            if not address:
                continue

            # Sum up lend token amounts in this input box
            lend_token_amount = 0
            for asset in input_box.get("assets", []):
                if asset.get("tokenId") == lend_token_id:
                    lend_token_amount += asset.get("amount", 0)

            if lend_token_amount > 0:
                if address not in address_changes:
                    address_changes[address] = 0
                address_changes[address] -= lend_token_amount

        # Process outputs (add tokens to addresses)
        for output_box in transaction_data.get("outputs", []):
            address = output_box.get("address")
            if not address:
                continue

            # Sum up lend token amounts in this output box
            lend_token_amount = 0
            for asset in output_box.get("assets", []):
                if asset.get("tokenId") == lend_token_id:
                    lend_token_amount += asset.get("amount", 0)

            if lend_token_amount > 0:
                if address not in address_changes:
                    address_changes[address] = 0
                address_changes[address] += lend_token_amount

        # Update positions for each affected address in this transaction
        for address, net_change in address_changes.items():
            if net_change == 0 or address == pool["pool"]:
                continue

            # Get the latest position_tokens for this address from DB
            query = """
            SELECT position_tokens 
            FROM user_lend_positions_historical 
            WHERE address_id = (SELECT id FROM addresses WHERE address = %s) 
            AND pool_nft = %s 
            ORDER BY block_height DESC, timestamp DESC 
            LIMIT 1
            """

            result = db.execute_query(query, (address, pool_nft))
            current_position_tokens = result[0]["position_tokens"] if result else 0

            # Calculate new position
            new_position_tokens = current_position_tokens + net_change

            # Get the lend_token_value from pool_data_historical
            # Find the highest block_height <= current block_height for this pool
            lend_value_query = """
            SELECT lend_token_value 
            FROM pool_data_historical 
            WHERE pool_nft = %s 
            AND block_height <= %s 
            ORDER BY block_height DESC 
            LIMIT 1
            """

            lend_value_result = db.execute_query(lend_value_query, (pool_nft, block_height))

            if lend_value_result and lend_value_result[0]["lend_token_value"] is not None:
                lend_token_value = lend_value_result[0]["lend_token_value"]
                position_value = new_position_tokens * lend_token_value
            else:
                position_value = -1

            # Update the position
            db.upsert_user_lend_position_historical(
                address=address,
                pool_nft=pool_nft,
                block_height=block_height,
                timestamp=timestamp,
                position_tokens=new_position_tokens,
                position_value=position_value
            )

            print(
                f"Updated position for {address} at block {block_height}: {current_position_tokens} -> {new_position_tokens} (change: {net_change}), position_value: {position_value}")