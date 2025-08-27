from current_pools import current_pools
from database.db_manager import DatabaseManager
from database_services.pool_services import sync_pool_interest_data, sync_all_pools
from database_services.transaction_service import sync_transactions, sync_transactions_batched
from database_services.user_history_services import sync_user_lend_positions, sync_user_deposits_historical, \
    add_granular_user_lend_positions, sync_user_portfolio_snapshots
from helpers.platform_functions import get_all_boxes_by_token_id
from database_services.currency_services import sync_currency_rates as _sync_currency_rates


def sync_user_lend_data(db: DatabaseManager, pool, min_height=0):
    # Can only be called on up-to-date database
    sync_user_lend_positions(db, pool)
    add_granular_user_lend_positions(db, pool, 1000)
    sync_user_deposits_historical(db, pool)
    sync_user_portfolio_snapshots(db,pool)


def sync_all_historical_data(db: DatabaseManager, pool, min_height=0):
    print(f"Starting historical data sync from height {min_height}")
    pool_boxes = get_all_boxes_by_token_id(pool["POOL_NFT"], min_height=min_height)
    if pool_boxes:
        sync_transactions_batched(db, pool, pool_boxes, min_height=min_height)
        sync_pool_interest_data(db, pool, pool_boxes, min_height=min_height)
        pass
    else:
        print(f"No boxes found above height {min_height} for pool {pool['POOL_NFT']}")


def sync_currency_rates(db: DatabaseManager, pools):
    """Sync USD currency rates for all pooled assets using CoinGecko API."""
    return _sync_currency_rates(db, pools)

def sync_all(db: DatabaseManager, min_height=0):
    """
    Sync all pools and historical data.

    :param db: Database manager instance
    :param min_height: Minimum block height to sync historical data from (default: 0)
    """
    pools = current_pools[:]
    sync_all_pools(db)
    sync_currency_rates(db, pools)
    for pool in pools:
        sync_all_historical_data(db, pool, min_height=min_height)
        sync_user_lend_data(db, pool, min_height=min_height)

