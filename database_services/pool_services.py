from current_pools import current_pools
from database.db_manager import DatabaseManager
from database_services.data_aggregation.pool_stats import borrow_apy, total_borrowed, lend_apy
from helpers.platform_functions import get_pool_box


def update_pool(db: DatabaseManager, pool):
    # Business logic here
    pool_box = get_pool_box(pool["pool"], pool["POOL_NFT"])
    borrowed = total_borrowed(pool, pool_box)
    if pool["is_Erg"]:
        assets_in_Pool = pool_box["value"] - pool["InitializedPoolAmount"]
    else:
        assets_in_Pool = pool_box["value"] - pool["InitializedPoolAmount"]
    total_lent = borrowed + assets_in_Pool
    borrow_rate = borrow_apy(pool, pool_box)
    lend_rate = lend_apy(pool, pool_box)
    # Call raw DB function
    return db.upsert_pool(pool["POOL_NFT"], pool["CURRENCY_ID"], total_lent, borrowed, lend_rate, borrow_rate)


def sync_all_pools(db: DatabaseManager):
    # Higher-level service function
    for pool in current_pools:
        update_pool(db, pool)