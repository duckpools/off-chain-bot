from database.db_manager import DatabaseManager
from database_services.sync_services import sync_all, sync_from_last_update, sync_all_parallel
from database_services.verification_services import run_deep_verification, get_verification_status, run_light_verification
from database_services.shutdown_handler import (
    setup_signal_handlers,
    is_shutdown_requested,
    request_shutdown,
    clear_shutdown_state
)
from helpers.node_calls import current_height
from logger import set_logger
import time
import os

logger = set_logger('db_routine')


def startup_consistency_check(db: DatabaseManager) -> bool:
    """
    Check database consistency on startup.
    Detects if previous shutdown was ungraceful.

    Args:
        db: Database manager instance

    Returns:
        True if consistency check passed, False otherwise
    """
    print("Running startup consistency check...")
    logger.info("Running startup consistency check")

    passed = True

    # Check if shutdown.flag still exists (unclean shutdown)
    if os.path.exists('shutdown.flag'):
        print("WARNING: Found stale shutdown.flag - previous shutdown may have been unclean")
        logger.warning("Found stale shutdown.flag - previous shutdown may have been unclean")
        try:
            os.remove('shutdown.flag')
            print("Removed stale shutdown.flag")
            logger.info("Removed stale shutdown.flag")
        except Exception as e:
            print(f"Could not remove shutdown.flag: {e}")
            logger.error("Could not remove shutdown.flag: %s", e)

    # Check for sync_block inconsistencies
    try:
        summary = db.get_sync_block_summary()
        logger.debug("Sync block summary at startup: %s", summary)

        # Compare max sync_blocks across tables
        max_blocks = [
            info['max_sync_block']
            for info in summary.values()
            if info.get('max_sync_block') is not None
        ]

        if max_blocks:
            spread = max(max_blocks) - min(max_blocks)
            logger.debug("Sync block spread: %d (max=%d, min=%d)", spread, max(max_blocks), min(max_blocks))
            if spread > 100:  # More than 100 block difference
                print(f"WARNING: Sync block spread of {spread} blocks detected")
                print("This may indicate an interrupted sync")
                print("Consider running: python scripts/db_management.py verify deep")
                logger.warning("Sync block spread of %d blocks detected - possible interrupted sync", spread)
                passed = False
    except Exception as e:
        print(f"Could not check sync block summary: {e}")
        logger.error("Could not check sync block summary: %s", e)
        # Don't fail the check if we can't get the summary
        pass

    # Run light verification
    try:
        verification_passed, _ = run_light_verification(db)
        if not verification_passed:
            print("WARNING: Light verification failed on startup")
            logger.warning("Light verification failed on startup")
            passed = False
        else:
            logger.debug("Light verification passed on startup")
    except Exception as e:
        print(f"Could not run light verification: {e}")
        logger.error("Could not run light verification: %s", e)
        passed = False

    if passed:
        print("Startup consistency check PASSED")
        logger.info("Startup consistency check PASSED")
    else:
        print("Startup consistency check completed with WARNINGS")
        logger.warning("Startup consistency check completed with WARNINGS")

    return passed


def graceful_shutdown(db: DatabaseManager, current_block_height: int = None):
    """
    Run verification and cleanup before final shutdown.

    Args:
        db: Database manager instance
        current_block_height: Current blockchain height (optional)
    """
    print("\n" + "="*60)
    print("GRACEFUL SHUTDOWN - Running pre-exit verification")
    print("="*60)
    logger.info("GRACEFUL SHUTDOWN initiated - running pre-exit verification")

    # Get current height if not provided
    if current_block_height is None:
        try:
            current_block_height = db.get_highest_sync_block() or 0
        except Exception as e:
            print(f"Could not get current height: {e}")
            logger.error("Could not get current height during shutdown: %s", e)
            current_block_height = 0

    logger.debug("Shutdown at block height: %s", current_block_height)

    # Run light verification
    try:
        verification_passed, _ = run_light_verification(db)

        if verification_passed:
            # Set verified checkpoint at current height
            try:
                db.set_checkpoint('verified', None, current_block_height, 'Pre-shutdown verification passed')
                print(f"Verification PASSED - checkpoint saved at block {current_block_height}")
                logger.info("Pre-shutdown verification PASSED - checkpoint saved at block %d", current_block_height)
            except Exception as e:
                print(f"Could not set checkpoint: {e}")
                logger.error("Could not set checkpoint at shutdown: %s", e)
        else:
            print("WARNING: Verification FAILED")
            print("Run deep verification after restart: python scripts/db_management.py verify deep")
            logger.warning("Pre-shutdown verification FAILED")
    except Exception as e:
        print(f"Could not run verification: {e}")
        logger.error("Could not run pre-shutdown verification: %s", e)

    # Clean up shutdown flag if it exists
    if os.path.exists('shutdown.flag'):
        try:
            os.remove('shutdown.flag')
            print("Removed shutdown.flag")
            logger.info("Removed shutdown.flag")
        except Exception as e:
            print(f"Could not remove shutdown.flag: {e}")
            logger.error("Could not remove shutdown.flag: %s", e)

    # Clear the in-memory shutdown state
    clear_shutdown_state()

    print("="*60)
    print("Sync process terminated gracefully")
    print("="*60 + "\n")
    logger.info("Sync process terminated gracefully")


def db_routine(full_sync=False, parallel_sync=False, run_verification=True):
    """
    Run database sync routine.

    Args:
        full_sync: If True, calls sync_all for a complete sync.
                   If False (default), runs sync_from_last_update in a continuous loop,
                   with selective syncing:
                   - Currency rates: synced every 3rd loop
                   - Borrow debts info: synced every 5th loop
                   - Deep verification: run every 100th loop
        parallel_sync: If True, uses parallel pool processing for faster syncing.
                      Applies to both full_sync and incremental sync modes. (default: False)
        run_verification: If True, runs light verification after each sync loop
                         and deep verification periodically. (default: True)

    Graceful Shutdown:
        To gracefully exit the sync loop (completing the current iteration):
        - Press Ctrl+C (SIGINT signal)
        - Send SIGTERM signal (Unix only): kill -TERM <pid>
        - Create a file named 'shutdown.flag' in the project root directory
        The routine will detect it, complete the current loop, run verification, and exit cleanly.

    Note: For checksum verification, use the functions in checksum_services:
          - create_checksums_file() to scan DB and write checksums
          - verify_checksums() to compare two checksum files
    """
    # Setup signal handlers for graceful shutdown
    setup_signal_handlers()

    db = DatabaseManager()
    logger.info("DatabaseManager initialized")

    # Run startup consistency check
    if not startup_consistency_check(db):
        print("\n" + "="*60)
        print("DATABASE CONSISTENCY WARNING")
        print("="*60)
        print("The database may be in an inconsistent state.")
        print("Options:")
        print("  1. Continue anyway (data may be incorrect)")
        print("  2. Run: python scripts/db_management.py verify deep")
        print("  3. Run: python scripts/db_management.py recover --pool <nft>")
        print("="*60 + "\n")
        logger.warning("Database consistency check failed - continuing with warnings")

    current_block = None

    if full_sync:
        mode = "PARALLEL" if parallel_sync else "SEQUENTIAL"
        print("=" * 70)
        if parallel_sync:
            print("RUNNING FULL SYNC (PARALLEL MODE)")
        else:
            print("RUNNING FULL SYNC")
        print("=" * 70 + "\n")
        logger.info("Starting FULL SYNC (%s mode)", mode)

        try:
            current_block = current_height()
            logger.info("Current block height: %d", current_block)
            sync_start = time.time()

            if parallel_sync:
                sync_all_parallel(db, sync_block=current_block)
            else:
                sync_all(db, sync_block=current_block)

            sync_elapsed = time.time() - sync_start
            print("\n" + "=" * 70)
            print("FULL SYNC COMPLETE")
            print("=" * 70 + "\n")
            logger.info("FULL SYNC COMPLETE in %.1f seconds", sync_elapsed)
        except Exception as e:
            logger.error("FULL SYNC FAILED with exception: %s", e, exc_info=True)
            raise
        finally:
            # Always run graceful shutdown for full sync
            graceful_shutdown(db, current_block)
    else:
        mode = "PARALLEL" if parallel_sync else "SEQUENTIAL"
        print("=" * 70)
        if parallel_sync:
            print("STARTING CONTINUOUS INCREMENTAL SYNC (PARALLEL MODE)")
        else:
            print("STARTING CONTINUOUS INCREMENTAL SYNC")
        print("=" * 70)
        print("Currency rates: synced every 3rd loop")
        print("Borrow debts: synced every 5th loop")
        print("DEX pools: synced every 12th loop")
        print("Headline stats: synced every 30th loop")
        if run_verification:
            print("Light verification: every loop")
            print("Deep verification: every 100th loop")
        print("Graceful shutdown: Ctrl+C, SIGTERM, or create 'shutdown.flag' file")
        print("=" * 70 + "\n")
        logger.info("Starting CONTINUOUS INCREMENTAL SYNC (%s mode, verification=%s)", mode, run_verification)

        loop_counter = 0

        try:
            while True:
                # Check for shutdown at the start of each loop
                if is_shutdown_requested():
                    print("\n" + "=" * 70)
                    print("SHUTDOWN REQUESTED")
                    print("=" * 70)
                    print("Exiting main loop...")
                    logger.info("Shutdown requested - exiting main loop after %d loops", loop_counter)
                    break

                loop_counter += 1

                # Determine what to sync this loop
                sync_currency = (loop_counter % 3 == 0)
                sync_debts = (loop_counter % 5 == 0)
                sync_dex_pools = (loop_counter % 12 == 0)
                sync_headline = (loop_counter % 30 == 0)
                run_deep_verify = run_verification and (loop_counter % 100 == 0)

                print(f"\n{'='*70}")
                status_parts = [
                    f"Currency:{'YES' if sync_currency else 'NO'}",
                    f"Debts:{'YES' if sync_debts else 'NO'}",
                    f"DEX:{'YES' if sync_dex_pools else 'NO'}",
                    f"Stats:{'YES' if sync_headline else 'NO'}"
                ]
                if run_verification:
                    status_parts.append(f"DeepVerify:{'YES' if run_deep_verify else 'NO'}")
                print(f"LOOP #{loop_counter} | {' '.join(status_parts)}")
                print(f"{'='*70}")

                logger.info("Loop #%d starting | currency=%s debts=%s dex=%s stats=%s deep_verify=%s",
                           loop_counter, sync_currency, sync_debts, sync_dex_pools, sync_headline, run_deep_verify)

                # Get current block height
                current_block = current_height()
                logger.debug("Loop #%d block height: %d", loop_counter, current_block)

                loop_start = time.time()

                # Run sync with current block height
                success = sync_from_last_update(
                    db,
                    current_block_height=current_block,
                    sync_currency_rates=sync_currency,
                    sync_debts=sync_debts,
                    sync_dex_pools=sync_dex_pools,
                    sync_headline_stats=sync_headline,
                    parallel_sync=parallel_sync,
                    run_verification=run_verification
                )

                loop_elapsed = time.time() - loop_start

                if success:
                    print(f"\nLoop #{loop_counter} complete")
                    logger.info("Loop #%d completed successfully in %.1f seconds", loop_counter, loop_elapsed)

                    # Run deep verification periodically (every 100th loop)
                    if run_deep_verify:
                        print("\n=== Running Deep Verification (every 100th loop) ===")
                        logger.info("Running deep verification (loop #%d)", loop_counter)
                        deep_passed, deep_results = run_deep_verification(db)
                        if deep_passed:
                            print("Deep verification PASSED")
                            logger.info("Deep verification PASSED")
                        else:
                            print("Deep verification FAILED - manual intervention may be needed")
                            # Log verification status for monitoring
                            status = get_verification_status(db)
                            print(f"Verification status: {status}")
                            logger.error("Deep verification FAILED - status: %s", status)
                else:
                    print(f"\nLoop #{loop_counter} failed")
                    logger.error("Loop #%d FAILED after %.1f seconds", loop_counter, loop_elapsed)

                # Check for shutdown after the loop completes
                if is_shutdown_requested():
                    print("\n" + "=" * 70)
                    print("SHUTDOWN REQUESTED")
                    print("=" * 70)
                    print("Exiting after completing loop...")
                    logger.info("Shutdown requested after loop #%d - exiting", loop_counter)
                    break

        except KeyboardInterrupt:
            # This handles Ctrl+C if signal handler doesn't catch it
            print("\n" + "=" * 70)
            print("KEYBOARD INTERRUPT DETECTED")
            print("=" * 70)
            print("Initiating graceful shutdown...")
            logger.info("Keyboard interrupt detected after %d loops - initiating graceful shutdown", loop_counter)

        finally:
            # Always run graceful shutdown
            graceful_shutdown(db, current_block)
