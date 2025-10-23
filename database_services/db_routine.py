from database.db_manager import DatabaseManager
from database_services.sync_services import sync_all, sync_from_last_update
from database_services.checksum_services import ChecksumManager
from helpers.node_calls import current_height


def db_routine(verify=True):
    """
    Run database sync routine with optional integrity verification.

    Args:
        verify: If True, creates checksums before/after sync and verifies data integrity.
                This adds overhead but ensures old data wasn't corrupted during sync.
                Creates three files:
                  - checksums_before_sync.json
                  - checksums_after_sync.json
                  - sync_verification_report.json

    Raises:
        Exception: If verify=True and data integrity check fails
    """
    db = DatabaseManager()

    if verify:
        checksummer = ChecksumManager(db)

        # Get current sync state before running sync
        current_sync_block = db.get_highest_sync_block()
        print("=" * 70)
        print("CREATING PRE-SYNC CHECKSUMS")
        print("=" * 70)
        print(f"Capturing database state up to block {current_sync_block}...\n")

        # Create "before" checksums
        before_checksums = checksummer.create_checksums(sync_block=current_sync_block)
        checksummer.save_checksums(before_checksums, 'checksums_before_sync.json')

        print("\n" + "=" * 70)
        print("RUNNING SYNC")
        print("=" * 70 + "\n")

    # Run the actual sync
    sync_from_last_update(db, current_block_height=current_height())
    #sync_all(db, sync_block=current_height())

    if verify:
        # Create "after" checksums for the SAME block range
        # (This verifies old data wasn't modified)
        print("\n" + "=" * 70)
        print("CREATING POST-SYNC CHECKSUMS")
        print("=" * 70)
        print(f"Recapturing database state up to block {current_sync_block}...\n")

        after_checksums = checksummer.create_checksums(sync_block=current_sync_block)
        checksummer.save_checksums(after_checksums, 'checksums_after_sync.json')

        # Compare checksums
        print("\n" + "=" * 70)
        print("VERIFYING DATA INTEGRITY")
        print("=" * 70 + "\n")

        comparison = checksummer.compare_checksum_files(
            'checksums_before_sync.json',
            'checksums_after_sync.json',
            'sync_verification_report.json'
        )

        # Raise exception if verification failed
        if comparison['summary']['status'] != 'PASS':
            raise Exception(
                "Data integrity verification FAILED! "
                "Old data was modified during sync. "
                "Check sync_verification_report.json for details."
            )

        new_sync_block = db.get_highest_sync_block()
        print("\n" + "=" * 70)
        print("✓ DATA INTEGRITY VERIFICATION SUCCESSFUL")
        print("=" * 70)
        print(f"  Old data (blocks 0-{current_sync_block}) verified unchanged")
        print(f"  New data added (blocks {current_sync_block + 1}-{new_sync_block})")
        print("=" * 70 + "\n")
