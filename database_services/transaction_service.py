from typing import Optional

from consts import FEE_ADDRESS_LIST
from database.db_manager import DatabaseManager
from helpers.node_calls import tree_to_address
from helpers.platform_functions import fetch_transaction_data


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


def sync_transactions(db: DatabaseManager, pool, pool_boxes, min_height=0):
    """
    Sync transactions for boxes above min_height.

    :param db: Database manager instance
    :param pool: Pool configuration
    :param pool_boxes: List of pool boxes
    :param min_height: Minimum block height to process (default: 0)
    """
    for pool_box in pool_boxes:
        if pool_box["address"] != pool["pool"]:
            continue

        # Skip boxes below min_height
        if pool_box.get("settlementHeight", 0) <= min_height:
            continue

        tx_id = pool_box["transactionId"]
        tx = fetch_transaction_data(tx_id)

        if not tx or "inputs" not in tx:
            print(f"Failed to fetch transaction data for {tx_id}")
            continue

        # Extract block_height and timestamp from main transaction
        main_block_height = tx.get("inclusionHeight")
        main_timestamp = tx.get("timestamp")

        # Skip if main transaction is below min_height
        if main_block_height and main_block_height <= min_height:
            continue

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
            if input_address == pool["proxy_lend"]:
                transaction_type, address, amount, fee = determine_lend_transaction(input_box, tx, pool)
                break
            elif input_address == pool["proxy_withdraw"]:
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
            continue

        # Call upsert_transaction
        result = db.upsert_transaction(
            transaction_id=final_tx_id,  # Use inner transaction ID for repayments
            address=address or "unknown_address",  # Use extracted address or fallback
            pool_nft=pool["POOL_NFT"],  # Assuming pool has an 'nft' field
            transaction_type=transaction_type,
            amount=amount,
            fee_paid=fee,
            block_height=block_height,  # Use extracted block_height
            timestamp=timestamp  # Use extracted timestamp
        )

        if result:
            print(
                f"Successfully processed transaction {final_tx_id} of type {transaction_type} for address {address} with amount {amount}")
        else:
            print(f"Failed to upsert transaction {final_tx_id}")
