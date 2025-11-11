from typing import Optional, List, Dict, Any

from consts import FEE_ADDRESS_LIST
from database.db_manager import DatabaseManager
from helpers.node_calls import tree_to_address
from helpers.platform_functions import fetch_transaction_data


def is_proxy_match(address: str, pool: dict, proxy_type: str) -> bool:
    """
    Check if an address matches current or legacy proxy address.
    Supports overlap period where both old and new proxies were valid.

    Args:
        address: Address to check
        pool: Pool configuration dict
        proxy_type: Type of proxy (e.g., 'proxy_lend', 'proxy_withdraw')

    Returns:
        True if address matches current or any legacy proxy of this type
    """
    # Check current proxy
    if address == pool.get(proxy_type):
        return True

    # Check legacy proxies (optional field)
    legacy_key = f"{proxy_type}_legacy"
    if legacy_key in pool:
        legacy_list = pool[legacy_key]
        if isinstance(legacy_list, list) and address in legacy_list:
            return True

    return False


def calculate_amount_difference(tx: dict, pool: dict) -> tuple[float, int]:
    """
    Calculates the amount difference between pool boxes in inputs and outputs.
    Also calculates the fee paid to any address in FEE_ADDRESS_LIST.
    Returns (amount, fee_amount) where:
    - amount: absolute difference based on pool["is_Erg"] setting
    - fee_amount: fee paid to fee addresses (0 if none found)
    """
    pool_address = pool["pool"]
    input_pool_box = None
    output_pool_box = None

    # Find pool box in inputs
    for input_box in tx.get("inputs", []):
        if input_box.get("address", "") == pool_address:
            input_pool_box = input_box
            break

    # Find pool box in outputs
    for output_box in tx.get("outputs", []):
        if output_box.get("address", "") == pool_address:
            output_pool_box = output_box
            break

    if not input_pool_box or not output_pool_box:
        print(f"Could not find pool boxes in inputs/outputs for pool address {pool_address}")
        return 0.0, 0

    # Calculate amount difference
    if pool.get("is_Erg", False):
        # Use box["value"] for ERG
        input_value = input_pool_box.get("value", 0)
        output_value = output_pool_box.get("value", 0)
        amount = abs(output_value - input_value)
    else:
        # Use box["assets"][3]["amount"] for tokens
        input_assets = input_pool_box.get("assets", [])
        output_assets = output_pool_box.get("assets", [])

        input_amount = 0
        output_amount = 0

        if len(input_assets) > 3:
            input_amount = input_assets[3].get("amount", 0)

        if len(output_assets) > 3:
            output_amount = output_assets[3].get("amount", 0)

        amount = abs(output_amount - input_amount)

    # Calculate fee amount
    fee_amount = 0

    # Look for fee addresses in outputs
    for output_box in tx.get("outputs", []):
        output_address = output_box.get("address", "")
        if output_address in FEE_ADDRESS_LIST:
            if pool.get("is_Erg", False):
                # For ERG pools, get box value
                fee_amount += output_box.get("value", 0)
            else:
                # For token pools, get box assets[0] amount
                assets = output_box.get("assets", [])
                if len(assets) > 0:
                    fee_amount += assets[0].get("amount", 0)

    return amount, fee_amount


def determine_lend_transaction(input_box: dict, tx: dict, pool: dict) -> tuple[str, Optional[str], float, int]:
    """
    Determines lend transaction and extracts address from R4 and calculates amount.
    Returns: ("lend", address, amount, fee)
    """
    transaction_type = "lend"
    address = None
    if "additionalRegisters" in input_box and "R4" in input_box["additionalRegisters"]:
        address = tree_to_address(input_box["additionalRegisters"]["R4"]["renderedValue"])

    amount, fee = calculate_amount_difference(tx, pool)
    return transaction_type, address, amount, fee


def determine_withdraw_transaction(input_box: dict, tx: dict, pool: dict) -> tuple[str, Optional[str], float, int]:
    """
    Determines withdraw transaction and extracts address from R4 and calculates amount.
    Returns: ("withdraw", address, amount, fee)
    """
    transaction_type = "withdraw"
    address = None
    if "additionalRegisters" in input_box and "R4" in input_box["additionalRegisters"]:
        address = tree_to_address(input_box["additionalRegisters"]["R4"]["renderedValue"])

    amount, fee = calculate_amount_difference(tx, pool)
    return transaction_type, address, amount, fee


def determine_borrow_transaction(input_box: dict, tx: dict, pool: dict) -> tuple[str, Optional[str], float]:
    """
    Determines borrow transaction and extracts address from R4 and calculates amount.
    Returns: ("borrow", address, amount)
    """
    transaction_type = "borrow"
    address = None
    if "additionalRegisters" in input_box and "R4" in input_box["additionalRegisters"]:
        address = tree_to_address(input_box["additionalRegisters"]["R4"]["renderedValue"])

    amount, fee = calculate_amount_difference(tx, pool)
    return transaction_type, address, amount


def determine_partial_repayment_transaction(input_box: dict, repayment_tx: dict, outer_tx: dict, pool: dict) -> tuple[
    str, Optional[str], float]:
    """
    Determines partial repayment transaction and extracts address from collateral box R4 and calculates amount.
    Returns: ("partial_repayment", address, amount)
    """
    transaction_type = "partial_repayment"
    address = None

    # Find the collateral box in inputs and read R4
    for input_box_inner in repayment_tx["inputs"]:
        if input_box_inner.get("address", "") == pool["collateral"]:
            if "additionalRegisters" in input_box_inner and "R4" in input_box_inner["additionalRegisters"]:
                address = tree_to_address(input_box_inner["additionalRegisters"]["R4"]["renderedValue"])
                break

    # Use outer transaction for amount calculation
    amount, fee = calculate_amount_difference(outer_tx, pool)
    return transaction_type, address, amount


def determine_full_repayment_transaction(input_box: dict, repayment_tx: dict, outer_tx: dict, pool: dict) -> tuple[
    str, Optional[str], float]:
    """
    Determines full repayment transaction and extracts address from R5 and calculates amount.
    Returns: ("repayment", address, amount)
    """
    transaction_type = "repayment"
    address = None
    if "additionalRegisters" in input_box and "R5" in input_box["additionalRegisters"]:
        address = tree_to_address(input_box["additionalRegisters"]["R5"]["renderedValue"])

    # Use outer transaction for amount calculation
    amount, fee = calculate_amount_difference(outer_tx, pool)
    return transaction_type, address, amount


def determine_liquidation_transaction(repayment_tx: dict, outer_tx: dict, pool: dict) -> tuple[
    str, Optional[str], float]:
    """
    Determines liquidation transaction by finding collateral box and extracting address from R4 and calculates amount.
    Returns: ("liquidation", address, amount)
    """
    transaction_type = "liquidation"
    address = None

    # Find the box with address pool["collateral"] and read R4
    for input_box in repayment_tx["inputs"]:
        if input_box.get("address", "") == pool["collateral"]:
            if "additionalRegisters" in input_box and "R4" in input_box["additionalRegisters"]:
                address = tree_to_address(input_box["additionalRegisters"]["R4"]["renderedValue"])
                break

    # Use outer transaction for amount calculation
    amount, fee = calculate_amount_difference(outer_tx, pool)
    return transaction_type, address, amount


def determine_repayment_type(repayment_box_tx_id: str, outer_tx: dict, pool: dict) -> tuple[
    Optional[str], Optional[str], float, Optional[int], Optional[int]]:
    """
    Determines the specific type of repayment transaction by analyzing the repayment box's transaction.
    Returns: (transaction_type, address, amount, block_height, timestamp) where transaction_type is 'partial_repayment', 'repayment', 'liquidation', or None
    """
    repayment_tx = fetch_transaction_data(repayment_box_tx_id)
    if not repayment_tx or "inputs" not in repayment_tx:
        print(f"Failed to fetch repayment transaction data for {repayment_box_tx_id}")
        return None, None, 0.0, None, None

    # Extract block_height and timestamp from repayment transaction
    block_height = repayment_tx.get("inclusionHeight")
    timestamp = repayment_tx.get("timestamp")

    # Check the inputs of the repayment transaction
    for repay_input in repayment_tx["inputs"]:
        repay_input_address = repay_input.get("address", "")

        # Check for partial repayment
        if repay_input_address == pool["proxy_partial_repay"]:
            transaction_type, address, amount = determine_partial_repayment_transaction(repay_input, repayment_tx,
                                                                                        outer_tx, pool)
            return transaction_type, address, amount, block_height, timestamp

        # Check for full repayment
        elif repay_input_address == pool["proxy_repay"]:
            transaction_type, address, amount = determine_full_repayment_transaction(repay_input, repayment_tx,
                                                                                     outer_tx, pool)
            return transaction_type, address, amount, block_height, timestamp

        # Check for liquidation by looking for collateral DEX NFTs
        else:
            if "assets" in repay_input and len(repay_input["assets"]) > 0:
                token_id = repay_input["assets"][0].get("tokenId", "")
                # Check if this token ID matches any collateral DEX NFT
                for collateral_key, collateral_info in pool.get("collateral_supported", {}).items():
                    if token_id == collateral_info.get("dex_nft"):
                        transaction_type, address, amount = determine_liquidation_transaction(repayment_tx, outer_tx,
                                                                                              pool)
                        return transaction_type, address, amount, block_height, timestamp

    return None, None, 0.0, None, None


def determine_repayment_transaction(input_box: dict, tx: dict, pool: dict) -> tuple[
    Optional[str], Optional[str], float, Optional[str], Optional[int], Optional[int]]:
    """
    Determines repayment transaction type and extracts address, amount, transaction_id, block_height, and timestamp.
    Returns: (transaction_type, address, amount, transaction_id, block_height, timestamp)
    """
    repayment_box_tx_id = input_box.get("outputTransactionId")
    if repayment_box_tx_id:
        transaction_type, address, amount, block_height, timestamp = determine_repayment_type(repayment_box_tx_id, tx,
                                                                                              pool)
        return transaction_type, address, amount, repayment_box_tx_id, block_height, timestamp
    else:
        print(f"No outputTransactionId found for repayment input box")
        return None, None, 0.0, None, None, None


def _process_single_transaction(pool_box: dict, pool: dict, sync_block: int, min_height: int = 0) -> Optional[Dict[str, Any]]:
    """
    Process a single pool box transaction and return transaction data or None if invalid.
    Shared logic between sync_transactions and sync_transactions_batched.

    :param pool_box: Pool box data
    :param pool: Pool configuration
    :param min_height: Minimum block height to process
    :param sync_block: Block height when this data was synced
    :return: Transaction data dictionary or None
    """
    if pool_box["address"] != pool["pool"]:
        return None

    # Skip boxes below min_height
    if pool_box.get("settlementHeight", 0) <= min_height:
        return None

    tx_id = pool_box["transactionId"]
    tx = fetch_transaction_data(tx_id)

    if not tx or "inputs" not in tx:
        print(f"Failed to fetch transaction data for {tx_id}")
        return None

    # Extract block_height and timestamp from main transaction
    main_block_height = tx.get("inclusionHeight")
    main_timestamp = tx.get("timestamp")

    # Skip if main transaction is below min_height
    if main_block_height and main_block_height <= min_height:
        return None

    # Determine transaction type by checking input addresses
    transaction_type = None
    address = None
    amount = 0.0
    fee = 0
    final_tx_id = tx_id  # Default to main transaction ID
    block_height = main_block_height
    timestamp = main_timestamp

    # Check each input to determine transaction type
    print(tx)
    for input_box in tx["inputs"]:
        input_address = input_box.get("address", "")
        fee = 0
        if is_proxy_match(input_address, pool, "proxy_lend"):
            transaction_type, address, amount, fee = determine_lend_transaction(input_box, tx, pool)
            break
        elif is_proxy_match(input_address, pool, "proxy_withdraw"):
            transaction_type, address, amount, fee = determine_withdraw_transaction(input_box, tx, pool)
            break
        elif input_address == pool["proxy_borrow"]:
            transaction_type, address, amount = determine_borrow_transaction(input_box, tx, pool)
            break
        elif input_address == pool["repayment"]:
            # For repayments, use inner transaction data
            transaction_type, address, amount, final_tx_id, block_height, timestamp = determine_repayment_transaction(
                input_box, tx, pool)
            if transaction_type:
                # Check if inner transaction is above min_height
                if block_height and block_height <= min_height:
                    transaction_type = None
                break

    if not transaction_type:
        print(f"Could not determine transaction type for {tx_id}")
        return None

    # Divide amount and fee by pool decimals to get user-friendly values
    decimals = pool["decimals"]
    amount_friendly = amount / (10 ** decimals)
    # Fees are in pool token, use pool decimals (ERG has decimals=9, tokens have their own)
    fee_friendly = fee / (10 ** decimals) if fee > 0 else 0

    return {
        'transaction_id': final_tx_id,
        'address': address or "unknown_address",
        'pool_nft': pool["POOL_NFT"],
        'transaction_type': transaction_type,
        'amount': amount_friendly,
        'fee_paid': fee_friendly,
        'block_height': block_height,
        'timestamp': timestamp,
        'sync_block': sync_block
    }


def sync_transactions(db: DatabaseManager, pool, pool_boxes, sync_block: int, min_height=0):
    """
    Sync transactions for boxes above min_height.

    :param db: Database manager instance
    :param pool: Pool configuration
    :param pool_boxes: List of pool boxes
    :param min_height: Minimum block height to process (default: 0)
    :param sync_block: Block height when this data was synced
    """
    for pool_box in pool_boxes:
        transaction_data = _process_single_transaction(pool_box, pool, sync_block, min_height)
        if not transaction_data:
            continue

        # Call upsert_transaction
        result = db.upsert_transaction(
            transaction_id=transaction_data['transaction_id'],
            address=transaction_data['address'],
            pool_nft=transaction_data['pool_nft'],
            transaction_type=transaction_data['transaction_type'],
            amount=transaction_data['amount'],
            fee_paid=transaction_data['fee_paid'],
            block_height=transaction_data['block_height'],
            timestamp=transaction_data['timestamp'],
            sync_block=transaction_data['sync_block']
        )

        if result:
            print(
                f"Successfully processed transaction {transaction_data['transaction_id']} of type {transaction_data['transaction_type']} for address {transaction_data['address']} with amount {transaction_data['amount']}")
        else:
            print(f"Failed to upsert transaction {transaction_data['transaction_id']}")


def sync_transactions_batched(db: DatabaseManager, pool, pool_boxes,  sync_block: int, min_height=0, batch_size=500):
    """
    Sync transactions for boxes above min_height using batched processing.
    Processes transactions locally in batches and inserts them in bulk to reduce database calls.

    :param db: Database manager instance
    :param pool: Pool configuration
    :param pool_boxes: List of pool boxes
    :param min_height: Minimum block height to process (default: 0)
    :param batch_size: Number of transactions to process in each batch (default: 500)
    :param sync_block: Block height when this data was synced
    """
    transactions_batch = []
    processed_count = 0

    for pool_box in pool_boxes:
        transaction_data = _process_single_transaction(pool_box, pool, sync_block, min_height)
        if not transaction_data:
            continue

        transactions_batch.append(transaction_data)
        processed_count += 1

        # Process batch when it reaches batch_size
        if len(transactions_batch) >= batch_size:
            success_count = db.batch_upsert_transactions(transactions_batch)
            print(f"Processed batch of {len(transactions_batch)} transactions, {success_count} successful")
            transactions_batch = []

    # Process any remaining transactions in the final batch
    if transactions_batch:
        success_count = db.batch_upsert_transactions(transactions_batch)
        print(f"Processed final batch of {len(transactions_batch)} transactions, {success_count} successful")

    print(f"Total transactions processed: {processed_count}")