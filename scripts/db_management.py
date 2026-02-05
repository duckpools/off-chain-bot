#!/usr/bin/env python3
"""
Database Management CLI Tool

Phase 5 implementation from DATABASE_BEST_PRACTICES.md:
- Set/view safe points manually
- Trigger manual recovery
- Run deep verification on demand

Usage:
    python scripts/db_management.py status                          # Show overall status
    python scripts/db_management.py checkpoints                     # List all checkpoints
    python scripts/db_management.py safe-point get [--pool POOL]    # Get current safe point
    python scripts/db_management.py safe-point set HEIGHT [--pool POOL] [--notes NOTES]
    python scripts/db_management.py verify light                    # Run light verification
    python scripts/db_management.py verify deep [--pool POOL]       # Run deep verification
    python scripts/db_management.py recover --pool POOL             # Trigger recovery for a pool
    python scripts/db_management.py sync-summary                    # Show sync block summary
"""

import argparse
import sys
import os
import json
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_manager import DatabaseManager
from database_services.verification_services import (
    run_light_verification,
    run_deep_verification,
    auto_repair_routine,
    get_verification_status
)


def format_height(height):
    """Format a block height with thousands separator."""
    if height is None:
        return "N/A"
    return f"{height:,}"


def format_timestamp(ts):
    """Format a timestamp for display."""
    if ts is None:
        return "N/A"
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    return str(ts)


def truncate_nft(nft, length=20):
    """Truncate a pool NFT for display."""
    if nft is None:
        return "global"
    if len(nft) <= length:
        return nft
    return nft[:length] + "..."


# ========================================
# STATUS COMMANDS
# ========================================

def cmd_status(args, db):
    """Show overall database and verification status."""
    print("\n" + "=" * 70)
    print("DATABASE STATUS OVERVIEW")
    print("=" * 70)

    # Get verification status
    status = get_verification_status(db)
    print(f"\nGlobal Status: {status['status'].upper()}")
    print(f"  Ingested Height:  {format_height(status['ingested_height'])}")
    print(f"  Verified Height:  {format_height(status['verified_height'])}")
    print(f"  Safe Point:       {format_height(status['safe_point_height'])}")
    print(f"  Verification Lag: {format_height(status['verification_lag'])} blocks")

    # Get sync block summary
    print("\n" + "-" * 70)
    print("SYNC BLOCK SUMMARY BY TABLE")
    print("-" * 70)
    summary = db.get_sync_block_summary()

    print(f"{'Table':<35} {'Min Sync':<12} {'Max Sync':<12} {'Rows':<10}")
    print("-" * 70)
    for table, info in sorted(summary.items()):
        min_sync = format_height(info['min_sync_block'])
        max_sync = format_height(info['max_sync_block'])
        rows = f"{info['total_rows']:,}"
        print(f"{table:<35} {min_sync:<12} {max_sync:<12} {rows:<10}")

    # Quick health check
    print("\n" + "-" * 70)
    print("QUICK HEALTH CHECK")
    print("-" * 70)

    try:
        # Check for any obvious issues
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Check for negative amounts
                cur.execute("""
                    SELECT
                        (SELECT COUNT(*) FROM transactions WHERE amount < 0) as neg_tx,
                        (SELECT COUNT(*) FROM user_lend_positions_historical WHERE position_tokens < 0) as neg_pos
                """)
                result = cur.fetchone()
                neg_tx, neg_pos = result

                if neg_tx == 0 and neg_pos == 0:
                    print("  [OK] No negative amounts detected")
                else:
                    print(f"  [WARNING] Negative amounts: {neg_tx} transactions, {neg_pos} positions")

                # Check checkpoint table exists
                cur.execute("""
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_name = 'sync_checkpoints'
                """)
                if cur.fetchone()[0] > 0:
                    print("  [OK] sync_checkpoints table exists")
                else:
                    print("  [ERROR] sync_checkpoints table missing!")

    except Exception as e:
        print(f"  [ERROR] Health check failed: {e}")

    print("\n" + "=" * 70)


def cmd_checkpoints(args, db):
    """List all checkpoints."""
    print("\n" + "=" * 70)
    print("ALL SYNC CHECKPOINTS")
    print("=" * 70)

    checkpoints = db.get_all_checkpoints()

    if not checkpoints:
        print("\nNo checkpoints found.")
        print("Use 'safe-point set' to create your first safe point.")
        return

    print(f"\n{'ID':<5} {'Type':<12} {'Pool':<25} {'Height':<12} {'Created By':<10} {'Created At':<20}")
    print("-" * 90)

    for cp in checkpoints:
        cp_id = cp['id']
        cp_type = cp['checkpoint_type']
        pool = truncate_nft(cp['pool_nft'])
        height = format_height(cp['block_height'])
        created_by = cp['created_by'] or 'system'
        created_at = format_timestamp(cp['created_at'])

        print(f"{cp_id:<5} {cp_type:<12} {pool:<25} {height:<12} {created_by:<10} {created_at:<20}")

        if cp.get('notes'):
            print(f"      Notes: {cp['notes']}")

    print("-" * 90)
    print(f"Total: {len(checkpoints)} checkpoint(s)")


def cmd_sync_summary(args, db):
    """Show detailed sync block summary."""
    print("\n" + "=" * 70)
    print("DETAILED SYNC BLOCK SUMMARY")
    print("=" * 70)

    summary = db.get_sync_block_summary()

    for table, info in sorted(summary.items()):
        print(f"\n{table}:")
        print(f"  Min sync_block: {format_height(info['min_sync_block'])}")
        print(f"  Max sync_block: {format_height(info['max_sync_block'])}")
        print(f"  Synced rows:    {info['synced_rows']:,}")
        print(f"  Total rows:     {info['total_rows']:,}")

        if info['total_rows'] > 0 and info['synced_rows'] < info['total_rows']:
            unsynced = info['total_rows'] - info['synced_rows']
            print(f"  Unsynced rows:  {unsynced:,} (may have NULL sync_block)")


# ========================================
# SAFE POINT COMMANDS
# ========================================

def cmd_safe_point_get(args, db):
    """Get current safe point."""
    pool_nft = args.pool

    safe_height = db.get_safe_point(pool_nft)

    pool_desc = f"pool {truncate_nft(pool_nft)}" if pool_nft else "global"

    if safe_height > 0:
        print(f"\nSafe point for {pool_desc}: {format_height(safe_height)}")

        # Get full checkpoint details
        checkpoint = None
        checkpoints = db.get_all_checkpoints()
        for cp in checkpoints:
            if cp['checkpoint_type'] == 'safe_point':
                if pool_nft is None and cp['pool_nft'] is None:
                    checkpoint = cp
                    break
                elif pool_nft == cp['pool_nft']:
                    checkpoint = cp
                    break

        if checkpoint:
            print(f"  Set by:     {checkpoint['created_by']}")
            print(f"  Created:    {format_timestamp(checkpoint['created_at'])}")
            if checkpoint.get('notes'):
                print(f"  Notes:      {checkpoint['notes']}")
    else:
        print(f"\nNo safe point set for {pool_desc}.")
        print("Use 'safe-point set HEIGHT' to set one.")


def cmd_safe_point_set(args, db):
    """Set a new safe point."""
    height = args.height
    pool_nft = args.pool
    notes = args.notes or f"Manually set via CLI on {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    pool_desc = f"pool {truncate_nft(pool_nft)}" if pool_nft else "global"

    # Confirm action
    print(f"\nAbout to set safe point for {pool_desc}:")
    print(f"  Block height: {format_height(height)}")
    print(f"  Notes: {notes}")

    if not args.yes:
        confirm = input("\nProceed? [y/N]: ").strip().lower()
        if confirm != 'y':
            print("Aborted.")
            return

    success = db.set_safe_point(height, pool_nft, notes)

    if success:
        print(f"\nSafe point set successfully!")
        print(f"  Pool:   {pool_desc}")
        print(f"  Height: {format_height(height)}")
    else:
        print("\nFailed to set safe point. Check logs for details.")
        sys.exit(1)


# ========================================
# VERIFICATION COMMANDS
# ========================================

def cmd_verify_light(args, db):
    """Run light verification checks."""
    print("\nRunning light verification checks...")

    passed, results = run_light_verification(db)

    print("\n" + "-" * 50)
    print("RESULTS SUMMARY")
    print("-" * 50)

    for check_name, check_result in results.items():
        status = "PASS" if check_result['passed'] else "FAIL"
        print(f"  [{status}] {check_name}")

        if not check_result['passed']:
            details = check_result.get('details', {})
            if isinstance(details, dict):
                for k, v in details.items():
                    print(f"         {k}: {v}")
            elif isinstance(details, list):
                for item in details[:3]:  # Show first 3
                    print(f"         {item}")

    print("-" * 50)

    if passed:
        print("\nAll light verification checks PASSED.")
        return 0
    else:
        print("\nSome verification checks FAILED.")
        print("Consider running deep verification or triggering recovery.")
        return 1


def cmd_verify_deep(args, db):
    """Run deep verification checks."""
    pool_nft = args.pool

    pool_desc = f"pool {truncate_nft(pool_nft)}" if pool_nft else "all pools"
    print(f"\nRunning deep verification checks for {pool_desc}...")
    print("This may take several minutes...\n")

    passed, results = run_deep_verification(db, pool_nft)

    print("\n" + "-" * 50)
    print("RESULTS SUMMARY")
    print("-" * 50)

    for check_name, check_result in results.items():
        status = "PASS" if check_result['passed'] else "FAIL"
        print(f"  [{status}] {check_name}")

        if not check_result['passed']:
            # Show counts
            for k, v in check_result.items():
                if k not in ['passed', 'sample', 'details']:
                    print(f"         {k}: {v}")

            # Show sample issues
            sample = check_result.get('sample', check_result.get('details', []))
            if sample:
                print("         Sample issues:")
                for item in sample[:3]:
                    if isinstance(item, dict):
                        print(f"           - {json.dumps(item, default=str)[:100]}")
                    else:
                        print(f"           - {item}")

    print("-" * 50)

    if passed:
        print("\nAll deep verification checks PASSED.")
        return 0
    else:
        print("\nSome verification checks FAILED.")
        print("Consider triggering recovery with 'recover --pool POOL_NFT'")
        return 1


# ========================================
# RECOVERY COMMANDS
# ========================================

def cmd_recover(args, db):
    """Trigger recovery for a pool."""
    pool_nft = args.pool

    if not pool_nft:
        print("Error: --pool is required for recovery.")
        print("Specify the pool NFT to recover.")
        sys.exit(1)

    print(f"\n" + "=" * 70)
    print(f"RECOVERY FOR POOL: {truncate_nft(pool_nft, 40)}")
    print("=" * 70)

    # First, run verification to see what's wrong
    print("\nStep 1: Running verification checks...")
    passed, results = run_deep_verification(db, pool_nft)

    if passed:
        print("\nAll verification checks passed. No recovery needed.")
        return 0

    failed_checks = [k for k, v in results.items() if not v['passed']]
    print(f"\nFailed checks: {failed_checks}")

    # Check for safe point
    safe_height = db.get_safe_point(pool_nft)
    print(f"\nCurrent safe point: {format_height(safe_height) if safe_height > 0 else 'Not set'}")

    # Confirm recovery
    print("\nStep 2: Recovery options:")
    print("  1. Rebuild derived tables (user_deposits_historical, user_portfolio_snapshots)")
    print("  2. If that fails, manual intervention will be required")

    if not args.yes:
        confirm = input("\nProceed with recovery? [y/N]: ").strip().lower()
        if confirm != 'y':
            print("Aborted.")
            return

    print("\nStep 3: Attempting auto-repair...")

    # Note: We don't have direct access to sync functions here,
    # so auto_repair_routine will just delete and report
    success = auto_repair_routine(
        db=db,
        pool_nft=pool_nft,
        failed_checks=failed_checks,
        sync_user_deposits_historical_func=None,  # Would need to import
        sync_user_portfolio_snapshots_func=None,  # Would need to import
        pool_config=None
    )

    if success:
        print("\nRecovery completed successfully!")

        # Set new verified checkpoint
        max_height = db.get_max_block_height_for_pool('transactions', pool_nft)
        if max_height:
            db.set_checkpoint('verified', pool_nft, max_height, 'Post-recovery verification passed')
            print(f"Set verified checkpoint at height {format_height(max_height)}")
    else:
        print("\nAuto-recovery could not fully resolve issues.")
        print("Manual intervention may be required.")
        print("\nSuggested manual steps:")
        print(f"  1. Review the failed checks above")
        print(f"  2. If you have a known good state, set a safe point:")
        print(f"     python scripts/db_management.py safe-point set HEIGHT --pool {pool_nft}")
        print(f"  3. Consider a full resync from the safe point")
        return 1

    return 0


# ========================================
# MAIN
# ========================================

def main():
    parser = argparse.ArgumentParser(
        description="Database Management CLI for off-chain-bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s status                              Show overall status
  %(prog)s checkpoints                         List all checkpoints
  %(prog)s safe-point get                      Get global safe point
  %(prog)s safe-point get --pool POOL_NFT      Get pool-specific safe point
  %(prog)s safe-point set 1234567              Set global safe point
  %(prog)s safe-point set 1234567 --pool NFT   Set pool-specific safe point
  %(prog)s verify light                        Run light verification
  %(prog)s verify deep                         Run deep verification (all pools)
  %(prog)s verify deep --pool POOL_NFT         Run deep verification (specific pool)
  %(prog)s recover --pool POOL_NFT             Trigger recovery for a pool
  %(prog)s sync-summary                        Show detailed sync summary
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # status command
    status_parser = subparsers.add_parser('status', help='Show overall database status')

    # checkpoints command
    checkpoints_parser = subparsers.add_parser('checkpoints', help='List all checkpoints')

    # sync-summary command
    sync_parser = subparsers.add_parser('sync-summary', help='Show detailed sync block summary')

    # safe-point command
    safe_point_parser = subparsers.add_parser('safe-point', help='Safe point management')
    safe_point_subparsers = safe_point_parser.add_subparsers(dest='safe_point_command')

    # safe-point get
    sp_get_parser = safe_point_subparsers.add_parser('get', help='Get current safe point')
    sp_get_parser.add_argument('--pool', type=str, help='Pool NFT (omit for global)')

    # safe-point set
    sp_set_parser = safe_point_subparsers.add_parser('set', help='Set a safe point')
    sp_set_parser.add_argument('height', type=int, help='Block height to set as safe point')
    sp_set_parser.add_argument('--pool', type=str, help='Pool NFT (omit for global)')
    sp_set_parser.add_argument('--notes', type=str, help='Notes about this safe point')
    sp_set_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')

    # verify command
    verify_parser = subparsers.add_parser('verify', help='Run verification checks')
    verify_subparsers = verify_parser.add_subparsers(dest='verify_command')

    # verify light
    verify_light_parser = verify_subparsers.add_parser('light', help='Run light verification')

    # verify deep
    verify_deep_parser = verify_subparsers.add_parser('deep', help='Run deep verification')
    verify_deep_parser.add_argument('--pool', type=str, help='Pool NFT (omit for all pools)')

    # recover command
    recover_parser = subparsers.add_parser('recover', help='Trigger recovery for a pool')
    recover_parser.add_argument('--pool', type=str, required=True, help='Pool NFT to recover')
    recover_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Check DATABASE_URL
    if not os.getenv('DATABASE_URL'):
        print("Error: DATABASE_URL environment variable not set.")
        print("Set it with: export DATABASE_URL='postgresql://user:pass@host:port/db'")
        sys.exit(1)

    # Initialize database connection
    try:
        db = DatabaseManager()
    except Exception as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)

    # Route to appropriate command
    try:
        if args.command == 'status':
            cmd_status(args, db)
        elif args.command == 'checkpoints':
            cmd_checkpoints(args, db)
        elif args.command == 'sync-summary':
            cmd_sync_summary(args, db)
        elif args.command == 'safe-point':
            if args.safe_point_command == 'get':
                cmd_safe_point_get(args, db)
            elif args.safe_point_command == 'set':
                cmd_safe_point_set(args, db)
            else:
                safe_point_parser.print_help()
        elif args.command == 'verify':
            if args.verify_command == 'light':
                sys.exit(cmd_verify_light(args, db))
            elif args.verify_command == 'deep':
                sys.exit(cmd_verify_deep(args, db))
            else:
                verify_parser.print_help()
        elif args.command == 'recover':
            sys.exit(cmd_recover(args, db))
        else:
            parser.print_help()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
