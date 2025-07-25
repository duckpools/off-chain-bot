from current_pools import current_pools
from database.db_manager import DatabaseManager
from database_services.pool_services import sync_pool_interest_data, sync_all_pools
from database_services.transaction_service import sync_transactions
from database_services.user_history_services import sync_user_lend_positions
from helpers.platform_functions import get_all_boxes_by_token_id


def sync_all_historical_data(db: DatabaseManager, min_height=0):
    """
    Sync all historical data for transactions and pool interest data above min_height.

    :param db: Database manager instance
    :param min_height: Minimum block height to sync from (default: 0)
    """
    # Higher-level service function
    print(f"Starting historical data sync from height {min_height}")

    for pool in current_pools:
        #sync_user_lend_positions(db, pool)
        print(f"Processing pool: {pool['POOL_NFT']}")
        pool_boxes = get_all_boxes_by_token_id(pool["POOL_NFT"], min_height=min_height)

        if pool_boxes:
            sync_transactions(db, pool, pool_boxes, min_height=min_height)
            sync_pool_interest_data(db, pool, pool_boxes, min_height=min_height)
        else:
            print(f"No boxes found above height {min_height} for pool {pool['POOL_NFT']}")


def sync_all(db: DatabaseManager, min_height=0):
    """
    Sync all pools and historical data.

    :param db: Database manager instance
    :param min_height: Minimum block height to sync historical data from (default: 0)
    """
    sync_all_historical_data(db, min_height=min_height)
    sync_all_pools(db)
