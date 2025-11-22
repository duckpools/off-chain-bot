from database.db_manager import DatabaseManager
from database_services.sync_services import sync_all, sync_from_last_update, sync_all_parallel
from helpers.node_calls import current_height
import time
import os


def db_routine(full_sync=False, parallel_sync=False):
    """
    Run database sync routine.

    Args:
        full_sync: If True, calls sync_all for a complete sync.
                   If False (default), runs sync_from_last_update in a continuous loop,
                   with selective syncing:
                   - Currency rates: synced every 3rd loop
                   - Borrow debts info: synced every 5th loop
        parallel_sync: If True, uses parallel pool processing for faster syncing.
                      Only applies to full_sync mode. (default: False)

    Graceful Shutdown:
        To gracefully exit the sync loop (completing the current iteration):
        - Create a file named 'shutdown.flag' in the project root directory
        - The routine will detect it, complete the current loop, and exit cleanly
        - Example: touch shutdown.flag
        - Note: Ctrl+C will still immediately terminate if needed

    Note: For checksum verification, use the functions in checksum_services:
          - create_checksums_file() to scan DB and write checksums
          - verify_checksums() to compare two checksum files
    """
    db = DatabaseManager()

    if full_sync:
        print("=" * 70)
        if parallel_sync:
            print("RUNNING FULL SYNC (PARALLEL MODE)")
        else:
            print("RUNNING FULL SYNC")
        print("=" * 70 + "\n")

        if parallel_sync:
            sync_all_parallel(db, sync_block=current_height())
        else:
            sync_all(db, sync_block=current_height())

        print("\n" + "=" * 70)
        print("✓ FULL SYNC COMPLETE")
        print("=" * 70 + "\n")
    else:
        print("=" * 70)
        print("STARTING CONTINUOUS INCREMENTAL SYNC")
        print("=" * 70)
        print("Currency rates: synced every 3rd loop")
        print("Borrow debts: synced every 5th loop")
        print("DEX pools: synced every 12th loop")
        print("Graceful shutdown: create 'shutdown.flag' file")
        print("=" * 70 + "\n")

        shutdown_flag_path = 'shutdown.flag'
        loop_counter = -1
        while True:
            loop_counter += 1
            print(f"\n{'='*70}")
            print(f"SYNC LOOP #{loop_counter}")
            print(f"{'='*70}")

            # Determine what to sync this loop
            sync_currency = (loop_counter % 3 == 0)
            sync_debts = (loop_counter % 5 == 0)
            sync_dex_pools = (loop_counter % 12 == 0)

            print(f"Currency rates: {'YES' if sync_currency else 'NO'}")
            print(f"Borrow debts: {'YES' if sync_debts else 'NO'}")
            print(f"DEX pools: {'YES' if sync_dex_pools else 'NO'}")
            print()

            # Run sync with current block height
            success = sync_from_last_update(
                db,
                current_block_height=current_height(),
                sync_currency_rates=sync_currency,
                sync_debts=sync_debts,
                sync_dex_pools=sync_dex_pools
            )

            if success:
                print(f"\n✓ Loop #{loop_counter} complete")
            else:
                print(f"\n✗ Loop #{loop_counter} failed")

            # Check for graceful shutdown flag
            if os.path.exists(shutdown_flag_path):
                print("\n" + "=" * 70)
                print("🛑 SHUTDOWN FLAG DETECTED")
                print("=" * 70)
                print("Gracefully exiting after completing loop...")
                try:
                    os.remove(shutdown_flag_path)
                    print(f"Removed {shutdown_flag_path}")
                except Exception as e:
                    print(f"Warning: Could not remove shutdown flag: {e}")
                print("=" * 70 + "\n")
                break

