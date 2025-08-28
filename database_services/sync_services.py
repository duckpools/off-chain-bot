from current_pools import current_pools
from database.db_manager import DatabaseManager
from database_services.pool_services import sync_pool_interest_data, sync_all_pools, sync_all_pools_batched, \
    sync_pool_interest_data_batched
from database_services.transaction_service import sync_transactions, sync_transactions_batched
from database_services.user_history_services import sync_user_lend_positions, sync_user_deposits_historical, \
    add_granular_user_lend_positions, sync_user_portfolio_snapshots
from helpers.platform_functions import get_all_boxes_by_token_id
from database_services.currency_services import sync_currency_rates as _sync_currency_rates, sync_currency_rates_batched


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


def sync_all_optimized(db: DatabaseManager, min_height=0):
    """
    Optimized sync routine using batch processing throughout.

    :param db: Database manager instance
    :param min_height: Minimum block height to sync historical data from
    """
    print(f"Starting optimized full sync from height {min_height}")

    pools = current_pools[:]

    # Step 1: Sync all pools in batch
    print("\n=== Step 1: Syncing all pools ===")
    sync_all_pools_batched(db)

    # Step 2: Sync currency rates in batch
    print("\n=== Step 2: Syncing currency rates ===")
    sync_currency_rates_batched(db, pools)

    # Step 3: Process historical data for each pool
    print("\n=== Step 3: Syncing historical data ===")
    for i, pool in enumerate(pools, 1):
        print(f"\nProcessing pool {i}/{len(pools)}: {pool['POOL_NFT']}")

        # Get all boxes once
        pool_boxes = get_all_boxes_by_token_id(pool["POOL_NFT"], min_height=min_height)

        if not pool_boxes:
            print(f"No boxes found above height {min_height} for pool {pool['POOL_NFT']}")
            continue

        print(f"Found {len(pool_boxes)} boxes to process")

        # Use batched versions for everything
        sync_transactions_batched(db, pool, pool_boxes, min_height=min_height, batch_size=500)
        sync_pool_interest_data_batched(db, pool, pool_boxes, min_height=min_height, batch_size=500)

        # User lend data - already optimized with batching
        sync_user_lend_positions(db, pool)
        add_granular_user_lend_positions(db, pool, 1000)
        sync_user_deposits_historical(db, pool)
        sync_user_portfolio_snapshots(db, pool)

    print("\n=== Full sync complete ===")


def sync_all(db: DatabaseManager, min_height=0, optimized=True):
    """
    Sync all pools and historical data.

    :param db: Database manager instance
    :param min_height: Minimum block height to sync historical data from (default: 0)
    """
    if optimized:
        return sync_all_optimized(db, min_height)
    else:
        pools = current_pools[:]
        sync_all_pools(db)
        sync_currency_rates(db, pools)
        for pool in pools:
            sync_all_historical_data(db, pool, min_height=min_height)
            sync_user_lend_data(db, pool, min_height=min_height)

