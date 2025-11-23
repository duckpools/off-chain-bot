import json
from collections import defaultdict
from typing import List, Tuple, Optional

from database.db_manager import DatabaseManager
from helpers.explorer_calls import get_unspent_boxes_by_address
from helpers.platform_functions import total_owed, get_interest_box, get_children_boxes
from helpers.node_calls import tree_to_address
from helpers.serializer import extract_number
from consts import INTEREST_DENOMINATION, BORROW_TOKEN_DENOMINATION


def get_all_collateral_boxes(collateral_address: str, limit: int = 100) -> list:
    """
    Fetch all unspent collateral boxes for an address using pagination.

    Args:
        collateral_address: The collateral contract address
        limit: Number of boxes to fetch per request (default 100)

    Returns:
        List of all unspent boxes
    """
    all_boxes = []
    offset = 0

    while True:
        boxes = get_unspent_boxes_by_address(collateral_address, limit=limit, offset=offset)
        if not boxes:
            break

        all_boxes.extend(boxes)

        if len(boxes) < limit:  # Last page reached
            break

        offset += limit

    return all_boxes


def calculate_debt_v1(pool: dict, collateral_box: dict, parent_box: dict, head_child: dict, children: list) -> float:
    """
    Calculate total debt (principal + interest) for a V1 pool loan.

    Args:
        pool: Pool configuration dict
        collateral_box: The collateral box containing the loan
        parent_box: Parent interest box
        head_child: Head child interest box
        children: List of all children interest boxes

    Returns:
        Total amount owed (principal + accrued interest)
    """
    # Extract amount borrowed based on pool type
    if pool["is_Erg"]:
        # For ERG pools, borrowed amount is in second asset
        amount_borrowed = int(collateral_box["assets"][1]["amount"])
    else:
        # For token pools, borrowed amount is first asset
        amount_borrowed = int(collateral_box["assets"][0]["amount"])

    # Extract loan indexes from R5 register
    loan_indexes = json.loads(collateral_box["additionalRegisters"]["R5"]["renderedValue"])

    # Use existing total_owed function from platform_functions
    total_owed_value = total_owed(
        principal=amount_borrowed,
        loan_indexes=loan_indexes,
        parent_box=parent_box,
        head_child=head_child,
        children=children
    )

    # Apply decimal division to convert raw value to human-readable amount
    decimals = pool.get("decimals", 9)  # Default to 9 if not specified
    total_owed_adjusted = total_owed_value / (10 ** decimals)

    return float(total_owed_adjusted)


def calculate_debt_v2(pool: dict, collateral_box: dict, interest_box: dict) -> float:
    """
    Calculate total debt (principal + interest) for a V2 pool loan.

    Args:
        pool: Pool configuration dict
        collateral_box: The collateral box containing the loan
        interest_box: Interest box containing borrow token value

    Returns:
        Total amount owed (principal + accrued interest)
    """
    # Extract borrow tokens from first asset
    borrow_tokens = int(collateral_box["assets"][0]["amount"])

    # Get borrowTokenValue from interest box R5 register
    borrow_token_value = extract_number(interest_box["additionalRegisters"]["R5"]["renderedValue"])

    # Calculate total owed: (borrow_tokens * borrow_token_value) / BORROW_TOKEN_DENOMINATION + 1
    total_owed_value = (borrow_tokens * borrow_token_value) // BORROW_TOKEN_DENOMINATION + 1

    # Apply decimal division to convert raw value to human-readable amount
    decimals = pool.get("decimals", 9)  # Default to 9 if not specified
    total_owed_adjusted = total_owed_value / (10 ** decimals)

    return float(total_owed_adjusted)


def get_user_debts_for_pool(pool: dict) -> List[Tuple[str, str, float]]:
    """
    Calculate all user debts for a specific pool.

    Args:
        pool: Pool configuration dict

    Returns:
        List of tuples: [(address, pool_nft, total_debt), ...]
    """
    pool_nft = pool["POOL_NFT"]
    collateral_address = pool["collateral"]
    version = pool["version"]

    # Step 1: Fetch all collateral boxes (active loans) using pagination
    try:
        collateral_boxes = get_all_collateral_boxes(collateral_address)
    except Exception as e:
        print(f"Error fetching collateral boxes for pool {pool_nft}: {e}")
        return []

    if not collateral_boxes:
        return []

    # Step 2: Fetch shared data once per pool based on version
    parent_box = None
    head_child = None
    children = None
    interest_box = None

    try:
        if version == 1:
            # V1: Get parent and children boxes
            parent_nft = pool["PARENT_NFT"]
            parent_address = pool["parent"]
            child_nft = pool["CHILD_NFT"]
            child_address = pool["child"]

            # Fetch parent box
            parent_boxes = get_unspent_boxes_by_address(parent_address)
            for box in parent_boxes:
                if box.get("assets") and box["assets"][0]["tokenId"] == parent_nft:
                    parent_box = box
                    break

            if not parent_box:
                print(f"Parent box not found for pool {pool_nft}")
                return []

            # Fetch children boxes
            children = get_children_boxes(child_address, child_nft)
            if not children:
                print(f"No children boxes found for pool {pool_nft}")
                return []

            # Get head child
            parent_interest_rates = json.loads(parent_box["additionalRegisters"]["R4"]["renderedValue"])
            num_children = len(parent_interest_rates)

            for child in children:
                child_index = int(child["additionalRegisters"]["R6"]["renderedValue"])
                if child_index == num_children:
                    head_child = child
                    break

            if not head_child:
                print(f"Head child not found for pool {pool_nft}")
                return []

        elif version == 2:
            # V2: Get interest box
            interest_nft = pool["INTEREST_NFT"]
            interest_address = pool["interest"]
            interest_box = get_interest_box(interest_address, interest_nft)

            if not interest_box:
                print(f"Interest box not found for pool {pool_nft}")
                return []
        else:
            print(f"Unknown pool version {version} for pool {pool_nft}")
            return []

    except Exception as e:
        print(f"Error fetching pool data for {pool_nft}: {e}")
        return []

    # Step 3: Process each collateral box and calculate debts
    debts = defaultdict(float)

    for collateral_box in collateral_boxes:
        try:
            # Extract user address from R4 register
            address = tree_to_address(collateral_box["additionalRegisters"]["R4"]["renderedValue"])

            # Calculate debt based on version
            if version == 1:
                debt = calculate_debt_v1(pool, collateral_box, parent_box, head_child, children)
            elif version == 2:
                debt = calculate_debt_v2(pool, collateral_box, interest_box)
            else:
                continue

            # Accumulate debt (handles multiple loans per user)
            debts[(address, pool_nft)] += debt

        except Exception as e:
            box_id = collateral_box.get("boxId", "unknown")
            print(f"Error processing collateral box {box_id}: {e}")
            continue

    # Step 4: Convert to list of tuples
    debts_list = [(addr, pool, debt) for (addr, pool), debt in debts.items()]

    return debts_list


def sync_user_pool_debts(db: DatabaseManager, pool: dict, sync_block: Optional[int] = None) -> int:
    """
    Sync user pool debts for a single pool to the database.

    Args:
        db: Database manager instance
        pool: Pool configuration dict
        sync_block: Block height to mark as sync point

    Returns:
        Number of records upserted
    """
    pool_nft = pool["POOL_NFT"]

    # Step 1: Clear all existing debt entries for this pool
    # This ensures repaid loans are removed from the database
    rows_deleted = db.delete_pool_debts(pool_nft)

    # Step 2: Get all current active debts for this pool
    debts_data = get_user_debts_for_pool(pool)

    if not debts_data:
        return 0

    # Step 3: Batch insert fresh debt data
    num_upserted = db.batch_upsert_user_pool_debts(debts_data, sync_block)

    return num_upserted


def sync_all_user_pool_debts(db: DatabaseManager, pools: list, sync_block: Optional[int] = None) -> int:
    """
    Sync user pool debts for all pools to the database.

    Args:
        db: Database manager instance
        pools: List of pool configuration dicts
        sync_block: Block height to mark as sync point

    Returns:
        Total number of records upserted across all pools
    """
    total_upserted = 0

    for i, pool in enumerate(pools, 1):
        pool_nft = pool.get("POOL_NFT", "unknown")
        pool_nft_short = pool_nft[:8] + "..."

        try:
            num_upserted = sync_user_pool_debts(db, pool, sync_block)
            total_upserted += num_upserted
            print(f"  Pool {i}/{len(pools)} ({pool_nft_short}): {num_upserted} debts ✓")
        except Exception as e:
            print(f"  Pool {i}/{len(pools)} ({pool_nft_short}): ERROR - {e}")
            continue

    print(f"  Total debt records: {total_upserted} ✓")

    return total_upserted
