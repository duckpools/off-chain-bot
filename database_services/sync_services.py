from typing import Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed, CancelledError
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
from database_services.verification_services import (
    run_light_verification,
    verify_and_checkpoint,
    auto_repair_routine
)
from database_services.shutdown_handler import is_shutdown_requested, request_shutdown


def get_pool_lock_id(pool_nft: str) -> int:
    """Generate a consistent lock ID from pool NFT string."""
    return hash(pool_nft) & 0x7FFFFFFF  # Positive 32-bit integer


def sync_with_checkpoints(db: DatabaseManager, items: list, sync_func, batch_size: int = 100,
                          operation_name: str = "sync") -> Tuple[int, bool]:
    """
    Process items in batches with shutdown checks between batches.

    This allows long-running sync operations to be interrupted gracefully
    at batch boundaries rather than mid-operation.

    Args:
        db: Database connection
        items: Items to process
        sync_func: Function to call for each item - signature: sync_func(db, item)
        batch_size: Check shutdown every N items
        operation_name: For logging

    Returns:
        Tuple of (completed_count, was_interrupted)
    """
    completed = 0
    interrupted = False
    total = len(items)

    for i, item in enumerate(items):
        # Check for shutdown at batch boundaries
        if i > 0 and i % batch_size == 0:
            if is_shutdown_requested():
                print(f"{operation_name}: Interrupted at {completed}/{total} items")
                interrupted = True
                break
            # Progress update every batch
            print(f"{operation_name}: Progress {completed}/{total}")

        try:
            sync_func(db, item)
            completed += 1
        except Exception as e:
            print(f"{operation_name}: Error on item {i}: {e}")

    return completed, interrupted


def sync_user_lend_data(db: DatabaseManager, pool, min_height=0, sync_block: Optional[int] = None):
    # Can only be called on up-to-date database
    sync_user_lend_positions(db, pool, sync_block=sync_block)
    add_granular_user_lend_positions(db, pool, 1000, sync_block=sync_block)
    sync_user_deposits_historical(db, pool, sync_block=sync_block)
    sync_user_portfolio_snapshots(db, pool, sync_block=sync_block)


def sync_all_historical_data(db: DatabaseManager, pool, min_height=0, sync_block: Optional[int] = None):
    pool_boxes = get_all_boxes_by_token_id(pool["POOL_NFT"], min_height=min_height)
    if pool_boxes:
        sync_transactions_batched(db, pool, pool_boxes, sync_block=sync_block, min_height=min_height)
        sync_pool_interest_data(db, pool, pool_boxes, min_height=min_height, sync_block=sync_block)


def sync_currency_rates(db: DatabaseManager, pools, sync_block: Optional[int] = None, min_height: int = 0):
    """Sync USD currency rates for all pooled assets using CoinGecko API."""
    return _sync_currency_rates(db, pools, sync_block=sync_block, min_height=min_height)


def sync_all_optimized(db: DatabaseManager, min_height=0, sync_block: Optional[int] = None,
                       sync_currency_rates: bool = True, sync_debts: bool = True,
                       sync_dex_pools: bool = True, sync_headline_stats: bool = True,
                       run_verification: bool = False):
    """
    Optimized sync routine using batch processing throughout.

    :param db: Database manager instance
    :param min_height: Minimum block height to sync historical data from
    :param sync_block: Block height when this sync was performed
    :param sync_currency_rates: Whether to sync currency rates (default: True)
    :param sync_debts: Whether to sync user pool debts (default: True)
    :param sync_dex_pools: Whether to sync DEX pool prices (default: True)
    :param sync_headline_stats: Whether to sync headline stats (default: True)
    :param run_verification: Whether to run verification after sync (default: False, handled by caller)
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
        # Check for shutdown before each pool
        if is_shutdown_requested():
            print(f"\nShutdown requested, stopping after {i-1}/{len(pools)} pools")
            break

        pool_nft_short = pool['POOL_NFT'][:8] + "..."
        print(f"\nPool {i}/{len(pools)} ({pool_nft_short}):", end=" ", flush=True)

        # Get all boxes once
        pool_boxes = get_all_boxes_by_token_id(pool["POOL_NFT"], min_height=min_height)

        if not pool_boxes:
            print(f"No boxes found")
        else:
            # Use batched versions for everything
            sync_transactions_batched(db, pool, pool_boxes, sync_block=sync_block, min_height=min_height, batch_size=500)
            sync_pool_interest_data_batched(db, pool, pool_boxes, min_height=min_height, batch_size=500,
                                            sync_block=sync_block)
            print("Interest ✓", end=" ", flush=True)

        # User lend data - already optimized with batching
        sync_user_lend_positions(db, pool, sync_block=sync_block, full_scan=full_scan)
        add_granular_user_lend_positions(db, pool, 1000, sync_block=sync_block, full_scan=full_scan)
        sync_user_deposits_historical(db, pool, sync_block=sync_block, full_scan=full_scan)
        print("Positions ✓", end=" ", flush=True)
        sync_user_portfolio_snapshots(db, pool, sync_block=sync_block)
        print("Complete ✓")

    # Check for shutdown before Step 4
    if is_shutdown_requested():
        print("\n=== Shutdown requested, skipping remaining steps ===")
        return

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
    pool_nft_short = pool_nft[:8] + "..."
    lock_id = get_pool_lock_id(pool_nft)

    try:
        print(f"[Thread {pool_index}/{total_pools}] {pool_nft_short}:", end=" ", flush=True)

        # Get all boxes once
        pool_boxes = get_all_boxes_by_token_id(pool["POOL_NFT"], min_height=min_height)

        if not pool_boxes:
            print(f"No boxes found")
        else:
            # Use batched versions for everything
            sync_transactions_batched(db, pool, pool_boxes, sync_block=sync_block, min_height=min_height, batch_size=500)
            sync_pool_interest_data_batched(db, pool, pool_boxes, min_height=min_height, batch_size=500,
                                            sync_block=sync_block)
            print("Interest ✓", end=" ", flush=True)

        # Acquire advisory lock before user data writes
        # This prevents interleaved writes from parallel workers
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
                try:
                    # User lend data - protected by lock
                    sync_user_lend_positions(db, pool, sync_block=sync_block, full_scan=full_scan)
                    add_granular_user_lend_positions(db, pool, 1000, sync_block=sync_block, full_scan=full_scan)
                    sync_user_deposits_historical(db, pool, sync_block=sync_block, full_scan=full_scan)
                    print("Positions ✓", end=" ", flush=True)
                    sync_user_portfolio_snapshots(db, pool, sync_block=sync_block)
                finally:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))

        print("Complete ✓")
        return (pool_nft, True, None)

    except Exception as e:
        error_msg = f"Error processing pool {pool_nft}: {str(e)}"
        print(f"\n[Thread {pool_index}/{total_pools}] ERROR: {error_msg}")
        return (pool_nft, False, error_msg)


def sync_all_parallel(db: DatabaseManager, min_height=0, sync_block: Optional[int] = None,
                      sync_currency_rates: bool = True, sync_debts: bool = True,
                      sync_dex_pools: bool = True, sync_headline_stats: bool = True,
                      max_workers: int = 6, run_verification: bool = False):
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
    :param run_verification: Whether to run verification after sync (default: False, handled by caller)
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

    # Check for shutdown before starting parallel processing
    if is_shutdown_requested():
        print("Shutdown requested, skipping parallel pool sync")
        return False

    # Prepare work items for each pool
    pool_tasks = [
        (db, pool, min_height, sync_block, full_scan, i, len(pools))
        for i, pool in enumerate(pools, 1)
    ]

    # Execute pool processing in parallel
    failed_pools = []
    successful_pools = []
    cancelled_pools = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_pool = {executor.submit(_process_single_pool, task): task[1] for task in pool_tasks}

        try:
            # Process completed tasks as they finish
            for future in as_completed(future_to_pool, timeout=600):
                # Check shutdown between completions
                if is_shutdown_requested():
                    print("\nShutdown requested, cancelling remaining pool syncs...")
                    # Cancel pending futures
                    for f in future_to_pool:
                        if not f.done():
                            f.cancel()
                            pool = future_to_pool[f]
                            cancelled_pools.append(pool['POOL_NFT'])
                    break

                pool = future_to_pool[future]
                try:
                    pool_nft, success, error_msg = future.result()
                    if success:
                        successful_pools.append(pool_nft)
                    else:
                        failed_pools.append((pool_nft, error_msg))
                except CancelledError:
                    pool_nft = pool['POOL_NFT']
                    print(f"Pool {pool_nft[:16]}... sync cancelled")
                    cancelled_pools.append(pool_nft)
                except Exception as e:
                    pool_nft = pool['POOL_NFT']
                    error_msg = f"Unhandled exception: {str(e)}"
                    failed_pools.append((pool_nft, error_msg))
                    print(f"ERROR: Pool {pool_nft} raised exception: {e}")

        except KeyboardInterrupt:
            print("\nKeyboardInterrupt - initiating graceful shutdown...")
            request_shutdown("KeyboardInterrupt in parallel sync")
            # Cancel all pending futures
            for f in future_to_pool:
                if not f.done():
                    f.cancel()
                    pool = future_to_pool[f]
                    cancelled_pools.append(pool['POOL_NFT'])
            raise

        except TimeoutError:
            print("\nTimeout waiting for pool syncs to complete")
            # Cancel remaining futures
            for f in future_to_pool:
                if not f.done():
                    f.cancel()
                    pool = future_to_pool[f]
                    cancelled_pools.append(pool['POOL_NFT'])

    # Report results
    print(f"\n=== Step 3 Complete: {len(successful_pools)} successful, {len(failed_pools)} failed, {len(cancelled_pools)} cancelled ===")
    if failed_pools:
        print("Failed pools:")
        for pool_nft, error in failed_pools:
            print(f"  - {pool_nft}: {error}")
    if cancelled_pools:
        print(f"Cancelled pools: {len(cancelled_pools)}")

    # Check for shutdown before Step 4
    if is_shutdown_requested():
        print("\n=== Shutdown requested, skipping remaining steps ===")
        return len(failed_pools) == 0 and len(cancelled_pools) == 0

    # Step 4: Sync user pool debts (optional)
    if sync_debts:
        print("\n=== Step 4: Syncing user pool debts ===")
        sync_all_user_pool_debts(db, pools, sync_block=sync_block)
    else:
        print("\n=== Step 4: Skipping user pool debts (not scheduled this loop) ===")

    print("\n=== Full PARALLEL sync complete ===")

    # Return True only if all pools succeeded and none were cancelled
    return len(failed_pools) == 0 and len(cancelled_pools) == 0


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
                         parallel_sync: bool = False, run_verification: bool = True) -> bool:
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
        run_verification: If True, runs light verification after sync (default: True)

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

            # Step 7: Run verification and set checkpoints
            if run_verification:
                verification_passed = verify_and_checkpoint(db, current_block_height)
                if not verification_passed:
                    print("WARNING: Sync completed but verification failed!")
                    # Optionally trigger auto-repair for specific pools
                    # For now, just log the failure - manual intervention may be needed
                    success = False  # Mark sync as failed if verification fails

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