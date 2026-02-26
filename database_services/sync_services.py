import time as _time
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
from database_services.position_verification_services import sync_all_user_current_positions
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
from logger import set_logger

logger = set_logger('sync_services', log_file='sync_services.log')


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
    logger.debug("%s: starting batch processing of %d items (batch_size=%d)", operation_name, total, batch_size)

    for i, item in enumerate(items):
        # Check for shutdown at batch boundaries
        if i > 0 and i % batch_size == 0:
            if is_shutdown_requested():
                print(f"{operation_name}: Interrupted at {completed}/{total} items")
                logger.warning("%s: interrupted at %d/%d items (shutdown requested)", operation_name, completed, total)
                interrupted = True
                break
            # Progress update every batch
            print(f"{operation_name}: Progress {completed}/{total}")
            logger.debug("%s: progress %d/%d", operation_name, completed, total)

        try:
            sync_func(db, item)
            completed += 1
        except Exception as e:
            print(f"{operation_name}: Error on item {i}: {e}")
            logger.error("%s: error on item %d: %s", operation_name, i, e)

    logger.debug("%s: finished - %d/%d completed, interrupted=%s", operation_name, completed, total, interrupted)
    return completed, interrupted


def sync_user_lend_data(db: DatabaseManager, pool, min_height=0, sync_block: Optional[int] = None):
    # Can only be called on up-to-date database
    sync_user_lend_positions(db, pool, sync_block=sync_block)
    add_granular_user_lend_positions(db, pool, 1000, sync_block=sync_block)
    sync_user_deposits_historical(db, pool, sync_block=sync_block)
    sync_user_portfolio_snapshots(db, pool, sync_block=sync_block)


def sync_all_historical_data(db: DatabaseManager, pool, min_height=0, sync_block: Optional[int] = None):
    pool_boxes = get_all_boxes_by_token_id(pool["POOL_NFT"], min_height=min_height)
    pool_boxes = [b for b in pool_boxes if b.get("address") == pool["pool"]]
    if pool_boxes:
        sync_transactions_batched(db, pool, pool_boxes, sync_block=sync_block, min_height=min_height)
        sync_pool_interest_data(db, pool, pool_boxes, min_height=min_height, sync_block=sync_block)


def sync_currency_rates(db: DatabaseManager, pools, sync_block: Optional[int] = None, min_height: int = 0):
    """Sync USD currency rates for all pooled assets using CoinGecko API."""
    return _sync_currency_rates(db, pools, sync_block=sync_block, min_height=min_height)


def sync_all_optimized(db: DatabaseManager, min_height=0, sync_block: Optional[int] = None,
                       sync_currency_rates: bool = True, sync_debts: bool = True,
                       sync_dex_pools: bool = True, sync_headline_stats: bool = True,
                       run_verification: bool = False, sync_positions: bool = True):
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
    :param sync_positions: Whether to sync on-chain positions (default: True)
    """
    print(f"Starting optimized full sync from height {min_height}")
    logger.info("Starting optimized sync from height %d (currency=%s, debts=%s, dex=%s, headline=%s)",
                min_height, sync_currency_rates, sync_debts, sync_dex_pools, sync_headline_stats)
    sync_start = _time.time()

    # Insert headline stats at the start of sync
    if sync_headline_stats:
        print("\n=== Step 0: Recording headline stats ===")
        logger.info("Step 0: Recording headline stats")
        t0 = _time.time()
        insert_headline_stats(db, sync_block=sync_block)
        logger.debug("Step 0 completed in %.2fs", _time.time() - t0)

    pools = current_pools[:]
    full_scan = False
    if min_height == 0:
        full_scan = True
    logger.debug("Processing %d pools (full_scan=%s)", len(pools), full_scan)

    # Step 1: Sync all pools in batch
    print("\n=== Step 1: Syncing all pools ===")
    logger.info("Step 1: Syncing all pools (batch)")
    t1 = _time.time()
    sync_all_pools_batched(db, sync_block=sync_block)
    logger.info("Step 1 completed in %.2fs", _time.time() - t1)

    # Step 2: Sync currency rates in batch (optional)
    if sync_currency_rates:
        print("\n=== Step 2: Syncing currency rates ===")
        logger.info("Step 2: Syncing currency rates")
        t2 = _time.time()
        sync_currency_rates_batched(db, pools, sync_block=sync_block, sync_dex_pools=sync_dex_pools)
        logger.info("Step 2 completed in %.2fs", _time.time() - t2)
    else:
        print("\n=== Step 2: Skipping currency rates (not scheduled this loop) ===")
        logger.debug("Step 2: Skipping currency rates")

    # Step 3: Process historical data for each pool
    print("\n=== Step 3: Syncing historical data ===")
    logger.info("Step 3: Syncing historical data for %d pools", len(pools))
    t3 = _time.time()
    pools_completed = 0
    for i, pool in enumerate(pools, 1):
        # Check for shutdown before each pool
        if is_shutdown_requested():
            print(f"\nShutdown requested, stopping after {i-1}/{len(pools)} pools")
            logger.warning("Step 3: Shutdown requested after %d/%d pools", i - 1, len(pools))
            break

        pool_nft_short = pool['POOL_NFT'][:8] + "..."
        print(f"\nPool {i}/{len(pools)} ({pool_nft_short}):", end=" ", flush=True)
        pool_start = _time.time()

        # Get all boxes once
        pool_boxes = get_all_boxes_by_token_id(pool["POOL_NFT"], min_height=min_height)
        pool_boxes = [b for b in pool_boxes if b.get("address") == pool["pool"]]

        pool_failed = False

        if not pool_boxes:
            print(f"No boxes found", end=" ", flush=True)
            logger.info("Pool %d/%d (%s): no boxes found", i, len(pools), pool_nft_short)
        else:
            logger.info("Pool %d/%d (%s): found %d boxes", i, len(pools), pool_nft_short, len(pool_boxes))
            # Use batched versions for everything
            try:
                logger.info("Pool %d/%d (%s): syncing transactions", i, len(pools), pool_nft_short)
                t_sub = _time.time()
                sync_transactions_batched(db, pool, pool_boxes, sync_block=sync_block, min_height=min_height, batch_size=500)
                logger.info("Pool %d/%d (%s): transactions done in %.2fs", i, len(pools), pool_nft_short, _time.time() - t_sub)
            except Exception as e:
                logger.error("Pool %s: transactions FAILED: %s", pool_nft_short, e, exc_info=True)
                print(f"ERROR in transactions: {e}", end=" ", flush=True)
                pool_failed = True

            try:
                logger.info("Pool %d/%d (%s): syncing interest data", i, len(pools), pool_nft_short)
                t_sub = _time.time()
                sync_pool_interest_data_batched(db, pool, pool_boxes, min_height=min_height, batch_size=500,
                                                sync_block=sync_block)
                logger.info("Pool %d/%d (%s): interest data done in %.2fs", i, len(pools), pool_nft_short, _time.time() - t_sub)
                print("Interest ✓", end=" ", flush=True)
            except Exception as e:
                logger.error("Pool %s: interest data FAILED: %s", pool_nft_short, e, exc_info=True)
                print(f"ERROR in interest data: {e}", end=" ", flush=True)
                pool_failed = True

        # User lend data - already optimized with batching
        try:
            logger.info("Pool %d/%d (%s): syncing user lend positions", i, len(pools), pool_nft_short)
            t_sub = _time.time()
            sync_user_lend_positions(db, pool, sync_block=sync_block, full_scan=full_scan)
            logger.info("Pool %d/%d (%s): user lend positions done in %.2fs", i, len(pools), pool_nft_short, _time.time() - t_sub)
        except Exception as e:
            logger.error("Pool %s: user lend positions FAILED: %s", pool_nft_short, e, exc_info=True)
            print(f"ERROR in user lend positions: {e}", end=" ", flush=True)
            pool_failed = True

        try:
            logger.info("Pool %d/%d (%s): syncing granular lend positions", i, len(pools), pool_nft_short)
            t_sub = _time.time()
            add_granular_user_lend_positions(db, pool, 1000, sync_block=sync_block, full_scan=full_scan)
            logger.info("Pool %d/%d (%s): granular lend positions done in %.2fs", i, len(pools), pool_nft_short, _time.time() - t_sub)
        except Exception as e:
            logger.error("Pool %s: granular lend positions FAILED: %s", pool_nft_short, e, exc_info=True)
            print(f"ERROR in granular lend positions: {e}", end=" ", flush=True)
            pool_failed = True

        try:
            logger.info("Pool %d/%d (%s): syncing user deposits historical", i, len(pools), pool_nft_short)
            t_sub = _time.time()
            sync_user_deposits_historical(db, pool, sync_block=sync_block, full_scan=full_scan)
            logger.info("Pool %d/%d (%s): user deposits historical done in %.2fs", i, len(pools), pool_nft_short, _time.time() - t_sub)
            print("Positions ✓", end=" ", flush=True)
        except Exception as e:
            logger.error("Pool %s: user deposits historical FAILED: %s", pool_nft_short, e, exc_info=True)
            print(f"ERROR in user deposits: {e}", end=" ", flush=True)
            pool_failed = True

        try:
            logger.info("Pool %d/%d (%s): syncing portfolio snapshots", i, len(pools), pool_nft_short)
            t_sub = _time.time()
            sync_user_portfolio_snapshots(db, pool, sync_block=sync_block)
            logger.info("Pool %d/%d (%s): portfolio snapshots done in %.2fs", i, len(pools), pool_nft_short, _time.time() - t_sub)
        except Exception as e:
            logger.error("Pool %s: portfolio snapshots FAILED: %s", pool_nft_short, e, exc_info=True)
            print(f"ERROR in portfolio snapshots: {e}", end=" ", flush=True)
            pool_failed = True

        if pool_failed:
            print("PARTIAL ✗")
            logger.warning("Pool %d/%d (%s) completed with errors in %.2fs", i, len(pools), pool_nft_short, _time.time() - pool_start)
        else:
            print("Complete ✓")
            logger.info("Pool %d/%d (%s) completed in %.2fs", i, len(pools), pool_nft_short, _time.time() - pool_start)
        pools_completed += 1

    logger.info("Step 3 completed: %d/%d pools in %.2fs", pools_completed, len(pools), _time.time() - t3)

    # Check for shutdown before Step 4
    if is_shutdown_requested():
        print("\n=== Shutdown requested, skipping remaining steps ===")
        logger.warning("Shutdown requested - skipping remaining steps")
        return

    # Step 4: Sync user pool debts (optional)
    if sync_debts:
        print("\n=== Step 4: Syncing user pool debts ===")
        logger.info("Step 4: Syncing user pool debts")
        t4 = _time.time()
        sync_all_user_pool_debts(db, pools, sync_block=sync_block)
        logger.info("Step 4 completed in %.2fs", _time.time() - t4)
    else:
        print("\n=== Step 4: Skipping user pool debts (not scheduled this loop) ===")
        logger.debug("Step 4: Skipping user pool debts")

    # Check for shutdown before Step 5
    if is_shutdown_requested():
        print("\n=== Shutdown requested, skipping remaining steps ===")
        logger.warning("Shutdown requested - skipping remaining steps after Step 4")
        return

    # Step 5: Sync on-chain positions (optional)
    if sync_positions:
        print("\n=== Step 5: Syncing on-chain positions ===")
        logger.info("Step 5: Syncing on-chain positions")
        t5 = _time.time()
        sync_all_user_current_positions(db, pools, sync_block=sync_block)
        logger.info("Step 5 completed in %.2fs", _time.time() - t5)
    else:
        print("\n=== Step 5: Skipping on-chain positions (not scheduled this loop) ===")
        logger.debug("Step 5: Skipping on-chain positions")

    total_elapsed = _time.time() - sync_start
    print("\n=== Full sync complete ===")
    logger.info("Optimized sync complete in %.2fs", total_elapsed)


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
    pool_start = _time.time()

    try:
        print(f"[Thread {pool_index}/{total_pools}] {pool_nft_short}:", end=" ", flush=True)
        logger.debug("[Thread %d/%d] Processing pool %s", pool_index, total_pools, pool_nft_short)

        # Get all boxes once
        pool_boxes = get_all_boxes_by_token_id(pool["POOL_NFT"], min_height=min_height)
        pool_boxes = [b for b in pool_boxes if b.get("address") == pool["pool"]]

        pool_failed = False

        if not pool_boxes:
            print(f"No boxes found", end=" ", flush=True)
            logger.info("[Thread %d/%d] Pool %s: no boxes found", pool_index, total_pools, pool_nft_short)
        else:
            logger.info("[Thread %d/%d] Pool %s: found %d boxes", pool_index, total_pools, pool_nft_short, len(pool_boxes))
            # Use batched versions for everything
            try:
                logger.info("[Thread %d/%d] Pool %s: syncing transactions", pool_index, total_pools, pool_nft_short)
                t_sub = _time.time()
                sync_transactions_batched(db, pool, pool_boxes, sync_block=sync_block, min_height=min_height, batch_size=500)
                logger.info("[Thread %d/%d] Pool %s: transactions done in %.2fs", pool_index, total_pools, pool_nft_short, _time.time() - t_sub)
            except Exception as e:
                logger.error("[Thread %d/%d] Pool %s: transactions FAILED: %s", pool_index, total_pools, pool_nft_short, e, exc_info=True)
                print(f"ERROR in transactions: {e}", end=" ", flush=True)
                pool_failed = True

            try:
                logger.info("[Thread %d/%d] Pool %s: syncing interest data", pool_index, total_pools, pool_nft_short)
                t_sub = _time.time()
                sync_pool_interest_data_batched(db, pool, pool_boxes, min_height=min_height, batch_size=500,
                                                sync_block=sync_block)
                logger.info("[Thread %d/%d] Pool %s: interest data done in %.2fs", pool_index, total_pools, pool_nft_short, _time.time() - t_sub)
                print("Interest ✓", end=" ", flush=True)
            except Exception as e:
                logger.error("[Thread %d/%d] Pool %s: interest data FAILED: %s", pool_index, total_pools, pool_nft_short, e, exc_info=True)
                print(f"ERROR in interest data: {e}", end=" ", flush=True)
                pool_failed = True

        # Acquire advisory lock before user data writes
        # This prevents interleaved writes from parallel workers
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
                try:
                    # User lend data - protected by lock
                    try:
                        logger.info("[Thread %d/%d] Pool %s: syncing user lend positions", pool_index, total_pools, pool_nft_short)
                        t_sub = _time.time()
                        sync_user_lend_positions(db, pool, sync_block=sync_block, full_scan=full_scan)
                        logger.info("[Thread %d/%d] Pool %s: user lend positions done in %.2fs", pool_index, total_pools, pool_nft_short, _time.time() - t_sub)
                    except Exception as e:
                        logger.error("[Thread %d/%d] Pool %s: user lend positions FAILED: %s", pool_index, total_pools, pool_nft_short, e, exc_info=True)
                        print(f"ERROR in user lend positions: {e}", end=" ", flush=True)
                        pool_failed = True

                    try:
                        logger.info("[Thread %d/%d] Pool %s: syncing granular lend positions", pool_index, total_pools, pool_nft_short)
                        t_sub = _time.time()
                        add_granular_user_lend_positions(db, pool, 1000, sync_block=sync_block, full_scan=full_scan)
                        logger.info("[Thread %d/%d] Pool %s: granular lend positions done in %.2fs", pool_index, total_pools, pool_nft_short, _time.time() - t_sub)
                    except Exception as e:
                        logger.error("[Thread %d/%d] Pool %s: granular lend positions FAILED: %s", pool_index, total_pools, pool_nft_short, e, exc_info=True)
                        print(f"ERROR in granular lend positions: {e}", end=" ", flush=True)
                        pool_failed = True

                    try:
                        logger.info("[Thread %d/%d] Pool %s: syncing user deposits historical", pool_index, total_pools, pool_nft_short)
                        t_sub = _time.time()
                        sync_user_deposits_historical(db, pool, sync_block=sync_block, full_scan=full_scan)
                        logger.info("[Thread %d/%d] Pool %s: user deposits historical done in %.2fs", pool_index, total_pools, pool_nft_short, _time.time() - t_sub)
                        print("Positions ✓", end=" ", flush=True)
                    except Exception as e:
                        logger.error("[Thread %d/%d] Pool %s: user deposits historical FAILED: %s", pool_index, total_pools, pool_nft_short, e, exc_info=True)
                        print(f"ERROR in user deposits: {e}", end=" ", flush=True)
                        pool_failed = True

                    try:
                        logger.info("[Thread %d/%d] Pool %s: syncing portfolio snapshots", pool_index, total_pools, pool_nft_short)
                        t_sub = _time.time()
                        sync_user_portfolio_snapshots(db, pool, sync_block=sync_block)
                        logger.info("[Thread %d/%d] Pool %s: portfolio snapshots done in %.2fs", pool_index, total_pools, pool_nft_short, _time.time() - t_sub)
                    except Exception as e:
                        logger.error("[Thread %d/%d] Pool %s: portfolio snapshots FAILED: %s", pool_index, total_pools, pool_nft_short, e, exc_info=True)
                        print(f"ERROR in portfolio snapshots: {e}", end=" ", flush=True)
                        pool_failed = True
                finally:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))

        elapsed = _time.time() - pool_start
        if pool_failed:
            print("PARTIAL ✗")
            logger.warning("[Thread %d/%d] Pool %s completed with errors in %.2fs", pool_index, total_pools, pool_nft_short, elapsed)
            return (pool_nft, False, f"Pool {pool_nft_short} completed with sub-step errors")
        else:
            print("Complete ✓")
            logger.info("[Thread %d/%d] Pool %s completed in %.2fs", pool_index, total_pools, pool_nft_short, elapsed)
            return (pool_nft, True, None)

    except Exception as e:
        error_msg = f"Error processing pool {pool_nft}: {str(e)}"
        print(f"\n[Thread {pool_index}/{total_pools}] ERROR: {error_msg}")
        logger.error("[Thread %d/%d] %s", pool_index, total_pools, error_msg, exc_info=True)
        return (pool_nft, False, error_msg)


def sync_all_parallel(db: DatabaseManager, min_height=0, sync_block: Optional[int] = None,
                      sync_currency_rates: bool = True, sync_debts: bool = True,
                      sync_dex_pools: bool = True, sync_headline_stats: bool = True,
                      max_workers: int = 6, run_verification: bool = False,
                      sync_positions: bool = True):
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
    :param sync_positions: Whether to sync on-chain positions (default: True)
    """
    print(f"Starting PARALLEL sync from height {min_height} with {max_workers} workers")
    logger.info("Starting PARALLEL sync from height %d with %d workers (currency=%s, debts=%s, dex=%s, headline=%s)",
                min_height, max_workers, sync_currency_rates, sync_debts, sync_dex_pools, sync_headline_stats)
    sync_start = _time.time()

    # Insert headline stats at the start of sync
    if sync_headline_stats:
        print("\n=== Step 0: Recording headline stats ===")
        logger.info("Step 0: Recording headline stats")
        t0 = _time.time()
        insert_headline_stats(db, sync_block=sync_block)
        logger.debug("Step 0 completed in %.2fs", _time.time() - t0)

    pools = current_pools[:]
    full_scan = False
    if min_height == 0:
        full_scan = True
    logger.debug("Processing %d pools (full_scan=%s)", len(pools), full_scan)

    # Step 1: Sync all pools in batch
    print("\n=== Step 1: Syncing all pools ===")
    logger.info("Step 1: Syncing all pools (batch)")
    t1 = _time.time()
    sync_all_pools_batched(db, sync_block=sync_block)
    logger.info("Step 1 completed in %.2fs", _time.time() - t1)

    # Step 2: Sync currency rates in batch (optional)
    if sync_currency_rates:
        print("\n=== Step 2: Syncing currency rates ===")
        logger.info("Step 2: Syncing currency rates")
        t2 = _time.time()
        sync_currency_rates_batched(db, pools, sync_block=sync_block, sync_dex_pools=sync_dex_pools)
        logger.info("Step 2 completed in %.2fs", _time.time() - t2)
    else:
        print("\n=== Step 2: Skipping currency rates (not scheduled this loop) ===")
        logger.debug("Step 2: Skipping currency rates")

    # Step 3: Process historical data for each pool IN PARALLEL
    print(f"\n=== Step 3: Syncing historical data (PARALLEL with {max_workers} workers) ===")
    logger.info("Step 3: Syncing historical data (PARALLEL, %d workers, %d pools)", max_workers, len(pools))
    t3 = _time.time()

    # Check for shutdown before starting parallel processing
    if is_shutdown_requested():
        print("Shutdown requested, skipping parallel pool sync")
        logger.warning("Shutdown requested before Step 3 - skipping parallel pool sync")
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
        logger.debug("Submitted %d pool tasks to thread pool", len(pool_tasks))

        try:
            # Process completed tasks as they finish
            for future in as_completed(future_to_pool, timeout=600):
                # Check shutdown between completions
                if is_shutdown_requested():
                    print("\nShutdown requested, cancelling remaining pool syncs...")
                    logger.warning("Shutdown requested during parallel processing - cancelling remaining tasks")
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
                    logger.warning("Pool %s sync cancelled", pool_nft[:16])
                    cancelled_pools.append(pool_nft)
                except Exception as e:
                    pool_nft = pool['POOL_NFT']
                    error_msg = f"Unhandled exception: {str(e)}"
                    failed_pools.append((pool_nft, error_msg))
                    print(f"ERROR: Pool {pool_nft} raised exception: {e}")
                    logger.error("Pool %s raised unhandled exception: %s", pool_nft[:16], e, exc_info=True)

        except KeyboardInterrupt:
            print("\nKeyboardInterrupt - initiating graceful shutdown...")
            logger.info("KeyboardInterrupt during parallel sync - initiating graceful shutdown")
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
            logger.error("Timeout (600s) waiting for parallel pool syncs to complete")
            # Cancel remaining futures
            for f in future_to_pool:
                if not f.done():
                    f.cancel()
                    pool = future_to_pool[f]
                    cancelled_pools.append(pool['POOL_NFT'])

    # Report results
    step3_elapsed = _time.time() - t3
    print(f"\n=== Step 3 Complete: {len(successful_pools)} successful, {len(failed_pools)} failed, {len(cancelled_pools)} cancelled ===")
    logger.info("Step 3 completed in %.2fs: %d successful, %d failed, %d cancelled",
                step3_elapsed, len(successful_pools), len(failed_pools), len(cancelled_pools))
    if failed_pools:
        print("Failed pools:")
        for pool_nft, error in failed_pools:
            print(f"  - {pool_nft}: {error}")
            logger.error("Failed pool %s: %s", pool_nft[:16], error)
    if cancelled_pools:
        print(f"Cancelled pools: {len(cancelled_pools)}")

    # Check for shutdown before Step 4
    if is_shutdown_requested():
        print("\n=== Shutdown requested, skipping remaining steps ===")
        logger.warning("Shutdown requested - skipping remaining steps after Step 3")
        return len(failed_pools) == 0 and len(cancelled_pools) == 0

    # Step 4: Sync user pool debts (optional)
    if sync_debts:
        print("\n=== Step 4: Syncing user pool debts ===")
        logger.info("Step 4: Syncing user pool debts")
        t4 = _time.time()
        sync_all_user_pool_debts(db, pools, sync_block=sync_block)
        logger.info("Step 4 completed in %.2fs", _time.time() - t4)
    else:
        print("\n=== Step 4: Skipping user pool debts (not scheduled this loop) ===")
        logger.debug("Step 4: Skipping user pool debts")

    # Check for shutdown before Step 5
    if is_shutdown_requested():
        print("\n=== Shutdown requested, skipping remaining steps ===")
        logger.warning("Shutdown requested - skipping remaining steps after Step 4")
        return len(failed_pools) == 0 and len(cancelled_pools) == 0

    # Step 5: Sync on-chain positions (optional)
    if sync_positions:
        print("\n=== Step 5: Syncing on-chain positions ===")
        logger.info("Step 5: Syncing on-chain positions")
        t5 = _time.time()
        sync_all_user_current_positions(db, pools, sync_block=sync_block)
        logger.info("Step 5 completed in %.2fs", _time.time() - t5)
    else:
        print("\n=== Step 5: Skipping on-chain positions (not scheduled this loop) ===")
        logger.debug("Step 5: Skipping on-chain positions")

    total_elapsed = _time.time() - sync_start
    print("\n=== Full PARALLEL sync complete ===")
    logger.info("PARALLEL sync complete in %.2fs", total_elapsed)

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
        pools = current_pools[-1:]
        sync_all_pools(db, sync_block=sync_block)
        sync_currency_rates(db, pools, sync_block=sync_block, min_height=min_height)
        for pool in pools:
            sync_all_historical_data(db, pool, min_height=min_height, sync_block=sync_block)
            sync_user_lend_data(db, pool, min_height=min_height, sync_block=sync_block)


def sync_from_last_update(db: DatabaseManager, current_block_height: Optional[int] = None,
                         sync_currency_rates: bool = True, sync_debts: bool = True,
                         sync_dex_pools: bool = True, sync_headline_stats: bool = True,
                         parallel_sync: bool = False, run_verification: bool = True,
                         sync_positions: bool = True) -> bool:
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
        sync_positions: Whether to sync on-chain positions (default: True)

    Returns:
        True if sync was successful, False otherwise
    """
    try:
        print("=== Starting Sync From Last Update ===")
        logger.info("Starting sync from last update (currency=%s, debts=%s, dex=%s, headline=%s, parallel=%s, verification=%s)",
                    sync_currency_rates, sync_debts, sync_dex_pools, sync_headline_stats, parallel_sync, run_verification)
        overall_start = _time.time()

        # Step 1: Get the lowest sync_block across all tables
        min_height = db.get_lowest_sync_block()

        if min_height is None:
            print("No previous sync_block found, performing full sync from height 0")
            logger.info("No previous sync_block found - full sync from height 0")
            min_height = 0
        else:
            print(f"Starting incremental sync from block height: {min_height}")
            logger.info("Incremental sync from block height: %d", min_height)

        # Step 2: Get current block height if not provided
        if current_block_height is None:
            print("Warning: No current_block_height provided, using min_height + 1 as sync_block")
            logger.warning("No current_block_height provided, using min_height + 1")
            current_block_height = min_height + 1

        print(f"Using sync_block: {current_block_height}")
        logger.info("Sync block range: %d -> %d (delta: %d blocks)", min_height, current_block_height, current_block_height - min_height)

        # Step 3: Get sync summary for monitoring
        sync_summary = db.get_sync_block_summary()
        print(f"Sync summary before update: {sync_summary}")
        logger.debug("Sync summary before update: %s", sync_summary)

        # Step 4: Perform incremental sync using existing optimized sync
        success = True
        try:
            if parallel_sync:
                sync_all_parallel(db, min_height=min_height, sync_block=current_block_height,
                                sync_currency_rates=sync_currency_rates, sync_debts=sync_debts,
                                sync_dex_pools=sync_dex_pools, sync_headline_stats=sync_headline_stats,
                                sync_positions=sync_positions)
            else:
                sync_all_optimized(db, min_height=min_height, sync_block=current_block_height,
                                 sync_currency_rates=sync_currency_rates, sync_debts=sync_debts,
                                 sync_dex_pools=sync_dex_pools, sync_headline_stats=sync_headline_stats,
                                 sync_positions=sync_positions)
        except Exception as e:
            print(f"Error during sync: {e}")
            logger.error("Error during sync: %s", e, exc_info=True)
            success = False

        # Step 5: Update all sync_blocks to the new current_block_height
        if success:
            print("\n=== Updating Sync Blocks ===")
            logger.info("Updating all sync blocks to %d", current_block_height)
            update_results = db.update_all_sync_blocks(current_block_height)
            print(f"Sync block update results: {update_results}")
            logger.debug("Sync block update results: %s", update_results)

        # Step 6: Get updated sync summary
        if success:
            updated_summary = db.get_sync_block_summary()
            print(f"Sync summary after update: {updated_summary}")
            logger.debug("Sync summary after update: %s", updated_summary)

            # Step 7: Run verification and set checkpoints
            if run_verification:
                logger.debug("Running post-sync verification")
                verification_passed = verify_and_checkpoint(db, current_block_height)
                if not verification_passed:
                    print("WARNING: Sync completed but verification failed!")
                    logger.warning("Sync completed but verification failed at block %d", current_block_height)
                    success = False
                else:
                    logger.debug("Post-sync verification passed")

            elapsed = _time.time() - overall_start
            print("=== Incremental Sync Complete ===")
            logger.info("Incremental sync complete in %.2fs (block %d)", elapsed, current_block_height)
        else:
            elapsed = _time.time() - overall_start
            print("=== Incremental Sync Failed ===")
            logger.error("Incremental sync FAILED after %.2fs", elapsed)

        return success

    except Exception as e:
        print(f"Error in sync_from_last_update: {e}")
        logger.error("Unhandled error in sync_from_last_update: %s", e, exc_info=True)
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
        logger.info("Starting re-sync from block %d", from_block)
        resync_start = _time.time()

        # Insert headline stats at the start of resync
        print("\n=== Step 0: Recording headline stats ===")
        logger.info("Step 0: Recording headline stats")
        insert_headline_stats(db, sync_block=current_block_height)

        # Step 1: Clear sync_blocks before the target block
        cleared_summary = db.clear_sync_blocks_before(from_block)
        print(f"Cleared sync_blocks before {from_block}: {cleared_summary}")
        logger.info("Cleared sync_blocks before %d: %s", from_block, cleared_summary)

        # Step 2: Perform full sync from the target block
        if current_block_height is None:
            current_block_height = from_block + 1
            print(f"Using sync_block: {current_block_height}")
            logger.debug("Using sync_block: %d", current_block_height)

        success = True
        try:
            sync_all_optimized(db, min_height=from_block, sync_block=current_block_height)
        except Exception as e:
            print(f"Error during resync: {e}")
            logger.error("Error during resync from block %d: %s", from_block, e, exc_info=True)
            success = False

        # Update all sync_blocks after successful resync
        if success:
            print("\n=== Updating Sync Blocks ===")
            logger.info("Updating all sync blocks to %d", current_block_height)
            update_results = db.update_all_sync_blocks(current_block_height)
            print(f"Sync block update results: {update_results}")
            logger.debug("Sync block update results: %s", update_results)

        elapsed = _time.time() - resync_start
        if success:
            print("=== Re-sync Complete ===")
            logger.info("Re-sync from block %d complete in %.2fs", from_block, elapsed)
        else:
            print("=== Re-sync Failed ===")
            logger.error("Re-sync from block %d FAILED after %.2fs", from_block, elapsed)

        return success

    except Exception as e:
        print(f"Error in resync_from_block: {e}")
        logger.error("Unhandled error in resync_from_block: %s", e, exc_info=True)
        return False
