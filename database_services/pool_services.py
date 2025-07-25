from current_pools import current_pools
from database.db_manager import DatabaseManager
from database_services.data_aggregation.pool_stats import borrow_apy, total_borrowed, lend_apy, pool_utilization
from helpers.platform_functions import get_pool_box, get_transaction_timestamp


def update_pool(db: DatabaseManager, pool):
    # Business logic here
    pool_box = get_pool_box(pool["pool"], pool["POOL_NFT"])
    borrowed = total_borrowed(pool, pool_box)
    if pool["is_Erg"]:
        assets_in_Pool = pool_box["value"] - pool["InitializedPoolAmount"]
    else:
        assets_in_Pool = pool_box["assets"][3]["amount"] - pool["InitializedPoolAmount"]
    total_lent = borrowed + assets_in_Pool
    borrow_rate = borrow_apy(pool, pool_box)
    lend_rate = lend_apy(pool, pool_box)
    # Call raw DB function
    return db.upsert_pool(pool["POOL_NFT"], pool["CURRENCY_ID"], total_lent, borrowed, lend_rate, borrow_rate)


def sync_all_pools(db: DatabaseManager):
    # Higher-level service function
    for pool in current_pools:
        update_pool(db, pool)


def sync_pool_interest_data(db: DatabaseManager, pool, pool_boxes, min_height=0):
    """
    Sync pool interest data for boxes above min_height.

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

        borrowed = total_borrowed(pool, pool_box)
        if pool["is_Erg"]:
            assets_in_Pool = pool_box["value"] - pool["InitializedPoolAmount"]
        else:
            assets_in_Pool = pool_box["assets"][3]["amount"] - pool["InitializedPoolAmount"]
        total_lent = borrowed + assets_in_Pool
        lend_rate = lend_apy(pool, pool_box)
        borrow_rate = borrow_apy(pool, pool_box)
        utilization = pool_utilization(pool, pool_box)
        try:
            timestamp = get_transaction_timestamp(pool_box["transactionId"])
        except Exception:
            print("Error getting timestamp for pool box")
            continue
        print(pool_box)
        print(db.upsert_pool_data_historical(
            pool["POOL_NFT"],
            pool_box["settlementHeight"],
            pool_box["transactionId"],
            lend_rate,
            borrow_rate,
            utilization,
            total_lent,
            borrowed,
            timestamp
        ))


