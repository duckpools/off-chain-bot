from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from current_pools import current_pools
from database.db_manager import DatabaseManager
from database_services.pool_services import sync_pool_interest_data, sync_all_pools, sync_all_pools_batched, \
    sync_pool_interest_data_batched
from database_services.transaction_service import sync_transactions_batched
from database_services.user_history_services import sync_user_lend_positions, sync_user_deposits_historical, \
    add_granular_user_lend_positions, sync_user_portfolio_snapshots
from database_services.debt_services import sync_all_user_pool_debts
from helpers.platform_functions import get_all_boxes_by_token_id
from database_services.currency_services import sync_currency_rates as _sync_currency_rates, \
    sync_currency_rates_batched
from database_services.headline_stats_services import insert_headline_stats


def sync_user_lend_data(db: DatabaseManager, pool, min_height=0, sync_block: Optional[int] = None):
    # Can only be called on up-to-date database
    sync_user_lend_positions(db, pool, sync_block=sync_block)
    add_granular_user_lend_positions(db, pool, 1000, sync_block=sync_block)
    sync_user_deposits_historical(db, pool, sync_block=sync_block)
    sync_user_portfolio_snapshots(db, pool, sync_block=sync_block)


def sync_all_historical_data(db: DatabaseManager, pool, min_height=0, sync_block: Optional[int] = None):
    print(f"Starting historical data sync from height {min_height}")
    pool_boxes = get_all_boxes_by_token_id(pool["POOL_NFT"], min_height=min_height)
    if pool_boxes:
        sync_transactions_batched(db, pool, pool_boxes, sync_block=sync_block, min_height=min_height)
        sync_pool_interest_data(db, pool, pool_boxes, min_height=min_height, sync_block=sync_block)
        pass
    else:
        print(f"No boxes found above height {min_height} for pool {pool['POOL_NFT']}")


def sync_currency_rates(db: DatabaseManager, pools, sync_block: Optional[int] = None, min_height: int = 0):
    """Sync USD currency rates for all pooled assets using CoinGecko API."""
    return _sync_currency_rates(db, pools, sync_block=sync_block, min_height=min_height)


def sync_all_optimized(db: DatabaseManager, min_height=0, sync_block: Optional[int] = None,
                       sync_currency_rates: bool = True, sync_debts: bool = True,
                       sync_dex_pools: bool = True, sync_headline_stats: bool = True):
    """
    Optimized sync routine using batch processing throughout.

    :param db: Database manager instance
    :param min_height: Minimum block height to sync historical data from
    :param sync_block: Block height when this sync was performed
    :param sync_currency_rates: Whether to sync currency rates (default: True)
    :param sync_debts: Whether to sync user pool debts (default: True)
    :param sync_dex_pools: Whether to sync DEX pool prices (default: True)
    :param sync_headline_stats: Whether to sync headline stats (default: True)
    """
    print(f"Starting optimized full sync from height {min_height}")

    # Insert headline stats at the start of sync
    if sync_headline_stats:
        print("\n=== Step 0: Recording headline stats ===")
        insert_headline_stats(db, sync_block=sync_block)

    pools = current_pools[:]
    full_scan = False
    if min_height == 0:
        full_scan = True

    # Step 1: Sync all pools in batch
    print("\n=== Step 1: Syncing all pools ===")
    sync_all_pools_batched(db, sync_block=sync_block)

    # Step 2: Sync currency rates in batch (optional)
    if sync_currency_rates:
        print("\n=== Step 2: Syncing currency rates ===")
        sync_currency_rates_batched(db, pools, sync_block=sync_block, sync_dex_pools=sync_dex_pools)
    else:
        print("\n=== Step 2: Skipping currency rates (not scheduled this loop) ===")

    # Step 3: Process historical data for each pool
    print("\n=== Step 3: Syncing historical data ===")
    for i, pool in enumerate(pools, 1):
        print(f"\nProcessing pool {i}/{len(pools)}: {pool['POOL_NFT']}")

        # Get all boxes once
        pool_boxes = get_all_boxes_by_token_id(pool["POOL_NFT"], min_height=min_height)

        if not pool_boxes:
            print(f"No boxes found above height {min_height} for pool {pool['POOL_NFT']}")
        else:
            print(f"Found {len(pool_boxes)} boxes to process")
            # Use batched versions for everything
            sync_transactions_batched(db, pool, pool_boxes, sync_block=sync_block, min_height=min_height, batch_size=500)
            sync_pool_interest_data_batched(db, pool, pool_boxes, min_height=min_height, batch_size=500,
                                            sync_block=sync_block)

        # User lend data - already optimized with batching
        sync_user_lend_positions(db, pool, sync_block=sync_block, full_scan=full_scan)
        add_granular_user_lend_positions(db, pool, 1000, sync_block=sync_block, full_scan=full_scan)
        sync_user_deposits_historical(db, pool, sync_block=sync_block, full_scan=full_scan)
        sync_user_portfolio_snapshots(db, pool, sync_block=sync_block)

    # Step 4: Sync user pool debts (optional)
    if sync_debts:
        print("\n=== Step 4: Syncing user pool debts ===")
        sync_all_user_pool_debts(db, pools, sync_block=sync_block)
    else:
        print("\n=== Step 4: Skipping user pool debts (not scheduled this loop) ===")

    print("\n=== Full sync complete ===")


def _process_single_pool(pool_info):
    """
    Process a single pool's historical data in parallel.

    :param pool_info: Tuple of (db, pool, min_height, sync_block, full_scan, pool_index, total_pools)
    :return: Tuple of (pool_nft, success, error_message)
    """
    db, pool, min_height, sync_block, full_scan, pool_index, total_pools = pool_info
    pool_nft = pool['POOL_NFT']

    try:
        print(f"\n[Thread {pool_index}/{total_pools}] Processing pool: {pool_nft}")

        # Get all boxes once
        pool_boxes = get_all_boxes_by_token_id(pool["POOL_NFT"], min_height=min_height)

        if not pool_boxes:
            print(f"[Thread {pool_index}/{total_pools}] No boxes found above height {min_height} for pool {pool_nft}")
        else:
            print(f"[Thread {pool_index}/{total_pools}] Found {len(pool_boxes)} boxes to process")
            # Use batched versions for everything
            sync_transactions_batched(db, pool, pool_boxes, sync_block=sync_block, min_height=min_height, batch_size=500)
            sync_pool_interest_data_batched(db, pool, pool_boxes, min_height=min_height, batch_size=500,
                                            sync_block=sync_block)

        # User lend data - already optimized with batching
        sync_user_lend_positions(db, pool, sync_block=sync_block, full_scan=full_scan)
        add_granular_user_lend_positions(db, pool, 1000, sync_block=sync_block, full_scan=full_scan)
        sync_user_deposits_historical(db, pool, sync_block=sync_block, full_scan=full_scan)
        sync_user_portfolio_snapshots(db, pool, sync_block=sync_block)

        print(f"[Thread {pool_index}/{total_pools}] Completed pool: {pool_nft}")
        return (pool_nft, True, None)

    except Exception as e:
        error_msg = f"Error processing pool {pool_nft}: {str(e)}"
        print(f"[Thread {pool_index}/{total_pools}] {error_msg}")
        return (pool_nft, False, error_msg)


def sync_all_parallel(db: DatabaseManager, min_height=0, sync_block: Optional[int] = None,
                      sync_currency_rates: bool = True, sync_debts: bool = True,
                      sync_dex_pools: bool = True, sync_headline_stats: bool = True,
                      max_workers: int = 6):
    """
    Parallel sync routine using ThreadPoolExecutor for pool processing.

    :param db: Database manager instance
    :param min_height: Minimum block height to sync historical data from
    :param sync_block: Block height when this sync was performed
    :param sync_currency_rates: Whether to sync currency rates (default: True)
    :param sync_debts: Whether to sync user pool debts (default: True)
    :param sync_dex_pools: Whether to sync DEX pool prices (default: True)
    :param sync_headline_stats: Whether to sync headline stats (default: True)
    :param max_workers: Maximum number of parallel workers (default: 6)
    """
    print(f"Starting PARALLEL sync from height {min_height} with {max_workers} workers")

    # Insert headline stats at the start of sync
    if sync_headline_stats:
        print("\n=== Step 0: Recording headline stats ===")
        insert_headline_stats(db, sync_block=sync_block)

    pools = current_pools[:]
    full_scan = False
    if min_height == 0:
        full_scan = True

    # Step 1: Sync all pools in batch
    print("\n=== Step 1: Syncing all pools ===")
    sync_all_pools_batched(db, sync_block=sync_block)

    # Step 2: Sync currency rates in batch (optional)
    if sync_currency_rates:
        print("\n=== Step 2: Syncing currency rates ===")
        sync_currency_rates_batched(db, pools, sync_block=sync_block, sync_dex_pools=sync_dex_pools)
    else:
        print("\n=== Step 2: Skipping currency rates (not scheduled this loop) ===")

    # Step 3: Process historical data for each pool IN PARALLEL
    print(f"\n=== Step 3: Syncing historical data (PARALLEL with {max_workers} workers) ===")

    # Prepare work items for each pool
    pool_tasks = [
        (db, pool, min_height, sync_block, full_scan, i, len(pools))
        for i, pool in enumerate(pools, 1)
    ]

    # Execute pool processing in parallel
    failed_pools = []
    successful_pools = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_pool = {executor.submit(_process_single_pool, task): task[1] for task in pool_tasks}

        # Process completed tasks as they finish
        for future in as_completed(future_to_pool):
            pool = future_to_pool[future]
            try:
                pool_nft, success, error_msg = future.result()
                if success:
                    successful_pools.append(pool_nft)
                else:
                    failed_pools.append((pool_nft, error_msg))
            except Exception as e:
                pool_nft = pool['POOL_NFT']
                error_msg = f"Unhandled exception: {str(e)}"
                failed_pools.append((pool_nft, error_msg))
                print(f"ERROR: Pool {pool_nft} raised exception: {e}")

    # Report results
    print(f"\n=== Step 3 Complete: {len(successful_pools)} successful, {len(failed_pools)} failed ===")
    if failed_pools:
        print("Failed pools:")
        for pool_nft, error in failed_pools:
            print(f"  - {pool_nft}: {error}")

    # Step 4: Sync user pool debts (optional)
    if sync_debts:
        print("\n=== Step 4: Syncing user pool debts ===")
        sync_all_user_pool_debts(db, pools, sync_block=sync_block)
    else:
        print("\n=== Step 4: Skipping user pool debts (not scheduled this loop) ===")

    print("\n=== Full PARALLEL sync complete ===")

    # Return True only if all pools succeeded
    return len(failed_pools) == 0


def sync_all(db: DatabaseManager, min_height=0, optimized=True, sync_block: Optional[int] = None):
    """
    Sync all pools and historical data.

    :param db: Database manager instance
    :param min_height: Minimum block height to sync historical data from (default: 0)
    :param optimized: Whether to use optimized sync (default: True)
    :param sync_block: Block height when this sync was performed
    """
    if optimized:
        return sync_all_optimized(db, min_height, sync_block)
    else:
        pools = current_pools[:]
        sync_all_pools(db, sync_block=sync_block)
        sync_currency_rates(db, pools, sync_block=sync_block, min_height=min_height)
        for pool in pools:
            sync_all_historical_data(db, pool, min_height=min_height, sync_block=sync_block)
            sync_user_lend_data(db, pool, min_height=min_height, sync_block=sync_block)


def sync_from_last_update(db: DatabaseManager, current_block_height: Optional[int] = None,
                         sync_currency_rates: bool = True, sync_debts: bool = True,
                         sync_dex_pools: bool = True, sync_headline_stats: bool = True,
                         parallel_sync: bool = False) -> bool:
    """
    Perform incremental sync starting from the lowest sync_block in the database.
    This allows for efficient incremental updates without re-processing all historical data.

    Args:
        db: Database manager instance
        current_block_height: Current blockchain block height to use as sync_block
        sync_currency_rates: Whether to sync currency rates (default: True)
        sync_debts: Whether to sync user pool debts (default: True)
        sync_dex_pools: Whether to sync DEX pool prices (default: True)
        sync_headline_stats: Whether to sync headline stats (default: True)
        parallel_sync: If True, uses parallel pool processing for faster syncing (default: False)

    Returns:
        True if sync was successful, False otherwise
    """
    try:
        print("=== Starting Sync From Last Update ===")

        # Step 1: Get the lowest sync_block across all tables
        min_height = db.get_lowest_sync_block()

        if min_height is None:
            print("No previous sync_block found, performing full sync from height 0")
            min_height = 0
        else:
            print(f"Starting incremental sync from block height: {min_height}")

        # Step 2: Get current block height if not provided
        if current_block_height is None:
            # You might want to add a function to get current block height from the blockchain
            # For now, we'll use a high number or fetch it from somewhere
            print("Warning: No current_block_height provided, using min_height + 1 as sync_block")
            current_block_height = min_height + 1

        print(f"Using sync_block: {current_block_height}")

        # Step 3: Get sync summary for monitoring
        sync_summary = db.get_sync_block_summary()
        print(f"Sync summary before update: {sync_summary}")

        # Step 4: Perform incremental sync using existing optimized sync
        success = True
        try:
            if parallel_sync:
                sync_all_parallel(db, min_height=min_height, sync_block=current_block_height,
                                sync_currency_rates=sync_currency_rates, sync_debts=sync_debts,
                                sync_dex_pools=sync_dex_pools, sync_headline_stats=sync_headline_stats)
            else:
                sync_all_optimized(db, min_height=min_height, sync_block=current_block_height,
                                 sync_currency_rates=sync_currency_rates, sync_debts=sync_debts,
                                 sync_dex_pools=sync_dex_pools, sync_headline_stats=sync_headline_stats)
        except Exception as e:
            print(f"Error during sync: {e}")
            success = False

        # Step 5: Update all sync_blocks to the new current_block_height
        # This ensures all tables have consistent sync_block values
        if success:
            print("\n=== Updating Sync Blocks ===")
            update_results = db.update_all_sync_blocks(current_block_height)
            print(f"Sync block update results: {update_results}")

        # Step 6: Get updated sync summary
        if success:
            updated_summary = db.get_sync_block_summary()
            print(f"Sync summary after update: {updated_summary}")
            print("=== Incremental Sync Complete ===")
        else:
            print("=== Incremental Sync Failed ===")

        return success

    except Exception as e:
        print(f"Error in sync_from_last_update: {e}")
        return False


def resync_from_block(db: DatabaseManager, from_block: int, current_block_height: Optional[int] = None) -> bool:
    """
    Re-sync all data starting from a specific block height.
    Clears sync_blocks before the specified height and performs full sync.

    Args:
        db: Database manager instance
        from_block: Block height to start re-sync from
        current_block_height: Current blockchain block height to use as sync_block

    Returns:
        True if resync was successful, False otherwise
    """
    try:
        print(f"=== Starting Re-sync From Block {from_block} ===")

        # Insert headline stats at the start of resync
        print("\n=== Step 0: Recording headline stats ===")
        insert_headline_stats(db, sync_block=current_block_height)

        # Step 1: Clear sync_blocks before the target block
        cleared_summary = db.clear_sync_blocks_before(from_block)
        print(f"Cleared sync_blocks before {from_block}: {cleared_summary}")

        # Step 2: Perform full sync from the target block
        if current_block_height is None:
            current_block_height = from_block + 1
            print(f"Using sync_block: {current_block_height}")

        success = True
        try:
            sync_all_optimized(db, min_height=from_block, sync_block=current_block_height)
        except Exception as e:
            print(f"Error during resync: {e}")
            success = False

        # Update all sync_blocks after successful resync
        if success:
            print("\n=== Updating Sync Blocks ===")
            update_results = db.update_all_sync_blocks(current_block_height)
            print(f"Sync block update results: {update_results}")

        if success:
            print("=== Re-sync Complete ===")
        else:
            print("=== Re-sync Failed ===")

        return success

    except Exception as e:
        print(f"Error in resync_from_block: {e}")
        return False