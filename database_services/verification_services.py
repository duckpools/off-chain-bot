"""
Verification Services for Database Integrity

Phase 3 implementation from DATABASE_BEST_PRACTICES.md:
- Light checks (run every sync loop, <1 second)
- Deep checks (hourly or on-demand)
- Auto-repair routine for derived tables
"""

from typing import List, Dict, Tuple, Optional
from database.db_manager import DatabaseManager


# ========================================
# LIGHT VERIFICATION CHECKS (Every Sync)
# ========================================

def check_no_negative_amounts(db: DatabaseManager) -> Tuple[bool, Dict[str, int]]:
    """
    Check that no tables have negative amounts (data corruption signal).

    Returns:
        Tuple of (passed: bool, details: Dict with bad_rows counts per table)
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                query = """
                    SELECT 'transactions' as tbl, COUNT(*) as bad_rows
                    FROM transactions WHERE amount < 0
                    UNION ALL
                    SELECT 'positions', COUNT(*)
                    FROM user_lend_positions_historical WHERE position_tokens < 0
                    UNION ALL
                    SELECT 'pool_data', COUNT(*)
                    FROM pool_data_historical WHERE total_lent < 0 OR total_borrowed < 0
                """
                cur.execute(query)
                results = cur.fetchall()

                details = {}
                total_bad = 0
                for row in results:
                    tbl, bad_rows = row
                    details[tbl] = bad_rows
                    total_bad += bad_rows

                passed = total_bad == 0
                if not passed:
                    print(f"VERIFICATION FAILED: Negative amounts found: {details}")

                return passed, details

    except Exception as e:
        print(f"Error in check_no_negative_amounts: {e}")
        return False, {'error': str(e)}


def check_referential_integrity(db: DatabaseManager) -> Tuple[bool, Dict[str, int]]:
    """
    Check referential integrity - no orphaned records.

    Returns:
        Tuple of (passed: bool, details: Dict with orphan counts)
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Check for orphaned transactions (address_id not in addresses)
                cur.execute("""
                    SELECT COUNT(*) as orphaned
                    FROM transactions t
                    LEFT JOIN addresses a ON t.address_id = a.id
                    WHERE a.id IS NULL
                """)
                orphaned_transactions = cur.fetchone()[0]

                # Check for orphaned user_lend_positions
                cur.execute("""
                    SELECT COUNT(*) as orphaned
                    FROM user_lend_positions_historical ulp
                    LEFT JOIN addresses a ON ulp.address_id = a.id
                    WHERE a.id IS NULL
                """)
                orphaned_positions = cur.fetchone()[0]

                # Check for orphaned user_deposits
                cur.execute("""
                    SELECT COUNT(*) as orphaned
                    FROM user_deposits_historical udh
                    LEFT JOIN addresses a ON udh.address_id = a.id
                    WHERE a.id IS NULL
                """)
                orphaned_deposits = cur.fetchone()[0]

                details = {
                    'orphaned_transactions': orphaned_transactions,
                    'orphaned_positions': orphaned_positions,
                    'orphaned_deposits': orphaned_deposits
                }

                total_orphans = sum(details.values())
                passed = total_orphans == 0

                if not passed:
                    print(f"VERIFICATION FAILED: Orphaned records found: {details}")

                return passed, details

    except Exception as e:
        print(f"Error in check_referential_integrity: {e}")
        return False, {'error': str(e)}


def check_block_height_consistency(db: DatabaseManager, max_allowed_diff: int = 10) -> Tuple[bool, List[Dict]]:
    """
    Check that block heights are consistent across related tables for each pool.

    Args:
        db: Database manager instance
        max_allowed_diff: Maximum allowed difference in block heights between tables

    Returns:
        Tuple of (passed: bool, details: List of pools with inconsistent heights)
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                query = """
                    SELECT
                        t.pool_nft,
                        MAX(t.block_height) as max_tx_height,
                        MAX(pdh.block_height) as max_pool_height,
                        ABS(COALESCE(MAX(t.block_height), 0) - COALESCE(MAX(pdh.block_height), 0)) as height_diff
                    FROM transactions t
                    LEFT JOIN pool_data_historical pdh ON t.pool_nft = pdh.pool_nft
                    GROUP BY t.pool_nft
                    HAVING ABS(COALESCE(MAX(t.block_height), 0) - COALESCE(MAX(pdh.block_height), 0)) > %s
                """
                cur.execute(query, (max_allowed_diff,))
                results = cur.fetchall()

                inconsistent_pools = []
                for row in results:
                    pool_nft, max_tx, max_pool, diff = row
                    inconsistent_pools.append({
                        'pool_nft': pool_nft,
                        'max_transaction_height': max_tx,
                        'max_pool_data_height': max_pool,
                        'height_difference': diff
                    })

                passed = len(inconsistent_pools) == 0

                if not passed:
                    print(f"VERIFICATION FAILED: Block height inconsistency in {len(inconsistent_pools)} pools")
                    for pool in inconsistent_pools:
                        print(f"  - {pool['pool_nft'][:16]}...: diff={pool['height_difference']}")

                return passed, inconsistent_pools

    except Exception as e:
        print(f"Error in check_block_height_consistency: {e}")
        return False, [{'error': str(e)}]


def run_light_verification(db: DatabaseManager) -> Tuple[bool, Dict]:
    """
    Run all light verification checks. These should complete in <1 second.

    Returns:
        Tuple of (all_passed: bool, details: Dict with results of each check)
    """
    print("\n=== Running Light Verification Checks ===")

    results = {}
    all_passed = True

    # Check 1: No negative amounts
    passed, details = check_no_negative_amounts(db)
    results['no_negative_amounts'] = {'passed': passed, 'details': details}
    if not passed:
        all_passed = False

    # Check 2: Referential integrity
    passed, details = check_referential_integrity(db)
    results['referential_integrity'] = {'passed': passed, 'details': details}
    if not passed:
        all_passed = False

    # Check 3: Block height consistency
    passed, details = check_block_height_consistency(db)
    results['block_height_consistency'] = {'passed': passed, 'details': details}
    if not passed:
        all_passed = False

    if all_passed:
        print("=== All Light Verification Checks PASSED ===")
    else:
        print("=== Light Verification FAILED ===")
        failed_checks = [k for k, v in results.items() if not v['passed']]
        print(f"Failed checks: {failed_checks}")

    return all_passed, results


# ========================================
# DEEP VERIFICATION CHECKS (Hourly/On-Demand)
# ========================================

def check_deposits_never_decrease(db: DatabaseManager, pool_nft: Optional[str] = None) -> Tuple[bool, List[Dict]]:
    """
    Verify that cumulative deposits never decrease over time.
    This is a deep check that can take longer.

    Args:
        db: Database manager instance
        pool_nft: Optional pool NFT to check (None for all pools)

    Returns:
        Tuple of (passed: bool, details: List of records where deposits decreased)
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                pool_filter = ""
                params = ()
                if pool_nft:
                    pool_filter = "WHERE udh.pool_nft = %s"
                    params = (pool_nft,)

                query = f"""
                    WITH ordered_deposits AS (
                        SELECT
                            address_id, pool_nft, block_height, total_deposited,
                            LAG(total_deposited) OVER (
                                PARTITION BY address_id, pool_nft ORDER BY block_height
                            ) as prev_deposited
                        FROM user_deposits_historical udh
                        {pool_filter}
                    )
                    SELECT address_id, pool_nft, block_height, total_deposited, prev_deposited
                    FROM ordered_deposits
                    WHERE total_deposited < prev_deposited
                    LIMIT 100
                """
                cur.execute(query, params)
                results = cur.fetchall()

                bad_records = []
                for row in results:
                    addr_id, pnft, height, total, prev = row
                    bad_records.append({
                        'address_id': addr_id,
                        'pool_nft': pnft,
                        'block_height': height,
                        'total_deposited': float(total),
                        'prev_deposited': float(prev),
                        'decrease': float(prev) - float(total)
                    })

                passed = len(bad_records) == 0

                if not passed:
                    print(f"DEEP VERIFICATION FAILED: Found {len(bad_records)} records where deposits decreased")

                return passed, bad_records

    except Exception as e:
        print(f"Error in check_deposits_never_decrease: {e}")
        return False, [{'error': str(e)}]


def check_profit_formula_consistency(db: DatabaseManager, pool_nft: Optional[str] = None,
                                     tolerance: float = 0.01) -> Tuple[bool, List[Dict]]:
    """
    Verify that total_profit = position_value + total_withdrawn - total_deposited.

    Args:
        db: Database manager instance
        pool_nft: Optional pool NFT to check (None for all pools)
        tolerance: Allowed drift from expected value

    Returns:
        Tuple of (passed: bool, details: List of records with drift)
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                pool_filter = ""
                params = (tolerance,)
                if pool_nft:
                    pool_filter = "AND ups.pool_nft = %s"
                    params = (tolerance, pool_nft)

                query = f"""
                    SELECT
                        ups.address_id, ups.pool_nft, ups.block_height,
                        ups.total_profit as stored,
                        (ups.position_value + COALESCE(udh.total_withdrawn, 0) - COALESCE(udh.total_deposited, 0)) as calculated,
                        ABS(ups.total_profit - (ups.position_value + COALESCE(udh.total_withdrawn, 0) - COALESCE(udh.total_deposited, 0))) as drift
                    FROM user_portfolio_snapshots ups
                    LEFT JOIN LATERAL (
                        SELECT total_deposited, total_withdrawn
                        FROM user_deposits_historical
                        WHERE address_id = ups.address_id
                          AND pool_nft = ups.pool_nft
                          AND block_height <= ups.block_height
                        ORDER BY block_height DESC, id DESC
                        LIMIT 1
                    ) udh ON true
                    WHERE ABS(ups.total_profit - (ups.position_value + COALESCE(udh.total_withdrawn, 0) - COALESCE(udh.total_deposited, 0))) > %s
                    {pool_filter}
                    ORDER BY drift DESC
                    LIMIT 100
                """
                cur.execute(query, params)
                results = cur.fetchall()

                drifted_records = []
                for row in results:
                    addr_id, pnft, height, stored, calculated, drift = row
                    drifted_records.append({
                        'address_id': addr_id,
                        'pool_nft': pnft,
                        'block_height': height,
                        'stored_profit': float(stored) if stored else 0,
                        'calculated_profit': float(calculated) if calculated else 0,
                        'drift': float(drift) if drift else 0
                    })

                passed = len(drifted_records) == 0

                if not passed:
                    print(f"DEEP VERIFICATION FAILED: Found {len(drifted_records)} records with profit drift > {tolerance}")

                return passed, drifted_records

    except Exception as e:
        print(f"Error in check_profit_formula_consistency: {e}")
        return False, [{'error': str(e)}]


def check_pool_totals_vs_positions(db: DatabaseManager, tolerance: float = 1.0) -> Tuple[bool, List[Dict]]:
    """
    Verify that pool total_lent matches sum of user positions.

    Args:
        db: Database manager instance
        tolerance: Allowed difference between pool total and sum of positions

    Returns:
        Tuple of (passed: bool, details: List of pools with mismatches)
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                query = """
                    SELECT
                        p.nft,
                        p.total_lent as pool_total,
                        COALESCE(SUM(ulp.position_value), 0) as sum_positions,
                        ABS(p.total_lent - COALESCE(SUM(ulp.position_value), 0)) as difference
                    FROM pools p
                    LEFT JOIN v_user_latest_positions ulp ON p.nft = ulp.pool_nft
                    GROUP BY p.nft, p.total_lent
                    HAVING ABS(p.total_lent - COALESCE(SUM(ulp.position_value), 0)) > %s
                """
                cur.execute(query, (tolerance,))
                results = cur.fetchall()

                mismatched_pools = []
                for row in results:
                    nft, pool_total, sum_pos, diff = row
                    mismatched_pools.append({
                        'pool_nft': nft,
                        'pool_total_lent': float(pool_total) if pool_total else 0,
                        'sum_positions': float(sum_pos) if sum_pos else 0,
                        'difference': float(diff) if diff else 0
                    })

                passed = len(mismatched_pools) == 0

                if not passed:
                    print(f"DEEP VERIFICATION FAILED: Found {len(mismatched_pools)} pools with total mismatch > {tolerance}")

                return passed, mismatched_pools

    except Exception as e:
        print(f"Error in check_pool_totals_vs_positions: {e}")
        return False, [{'error': str(e)}]


def check_positions_vs_chain(db: DatabaseManager, tolerance: float = 0.01) -> Tuple[bool, List[Dict]]:
    """
    Verify derived positions (from tx replay) match on-chain positions (from UTXOs).

    Uses raw subquery from user_lend_positions_historical (not the view) so we
    catch negative position_tokens that the view filters out.

    Args:
        db: Database manager instance
        tolerance: Allowed difference between derived and chain position tokens

    Returns:
        Tuple of (passed: bool, details: List of mismatched records)
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                query = """
                    WITH derived_latest AS (
                        SELECT DISTINCT ON (address_id, pool_nft)
                            address_id,
                            pool_nft,
                            position_tokens as derived_tokens,
                            position_value as derived_value
                        FROM user_lend_positions_historical
                        ORDER BY address_id, pool_nft, block_height DESC, id DESC
                    )
                    SELECT
                        a.address,
                        COALESCE(d.pool_nft, c.pool_nft) as pool_nft,
                        COALESCE(d.derived_tokens, 0) as derived_tokens,
                        COALESCE(c.position_tokens, 0) as chain_tokens,
                        ABS(COALESCE(d.derived_tokens, 0) - COALESCE(c.position_tokens, 0)) as token_diff
                    FROM derived_latest d
                    FULL OUTER JOIN user_current_positions c
                        ON d.address_id = c.address_id AND d.pool_nft = c.pool_nft
                    JOIN addresses a ON a.id = COALESCE(d.address_id, c.address_id)
                    WHERE ABS(COALESCE(d.derived_tokens, 0) - COALESCE(c.position_tokens, 0)) > %s
                    ORDER BY ABS(COALESCE(d.derived_tokens, 0) - COALESCE(c.position_tokens, 0)) DESC
                """
                cur.execute(query, (tolerance,))
                results = cur.fetchall()

                mismatches = []
                for row in results:
                    address, pnft, derived_tokens, chain_tokens, diff = row
                    mismatches.append({
                        'address': address,
                        'pool_nft': pnft,
                        'derived_tokens': float(derived_tokens) if derived_tokens else 0,
                        'chain_tokens': float(chain_tokens) if chain_tokens else 0,
                        'difference': float(diff) if diff else 0
                    })

                passed = len(mismatches) == 0

                if not passed:
                    print(f"DEEP VERIFICATION FAILED: Found {len(mismatches)} position mismatches vs chain (tolerance={tolerance})")
                    for m in mismatches[:10]:
                        print(f"  {m['address'][:16]}... pool={m['pool_nft'][:16]}... "
                              f"derived={m['derived_tokens']:.4f} chain={m['chain_tokens']:.4f} "
                              f"diff={m['difference']:.4f}")

                return passed, mismatches

    except Exception as e:
        print(f"Error in check_positions_vs_chain: {e}")
        return False, [{'error': str(e)}]


def run_deep_verification(db: DatabaseManager, pool_nft: Optional[str] = None) -> Tuple[bool, Dict]:
    """
    Run all deep verification checks. These can take minutes.

    Args:
        db: Database manager instance
        pool_nft: Optional pool NFT to limit checks to a specific pool

    Returns:
        Tuple of (all_passed: bool, details: Dict with results of each check)
    """
    print("\n=== Running Deep Verification Checks ===")
    if pool_nft:
        print(f"Checking pool: {pool_nft}")
    else:
        print("Checking all pools")

    results = {}
    all_passed = True

    # Check 1: Deposits never decrease
    print("  Running: deposits_never_decrease...")
    passed, details = check_deposits_never_decrease(db, pool_nft)
    results['deposits_never_decrease'] = {'passed': passed, 'bad_records_count': len(details)}
    if not passed:
        all_passed = False
        results['deposits_never_decrease']['sample'] = details[:5]  # First 5 examples

    # Check 2: Profit formula consistency
    print("  Running: profit_formula_consistency...")
    passed, details = check_profit_formula_consistency(db, pool_nft)
    results['profit_formula_consistency'] = {'passed': passed, 'drifted_records_count': len(details)}
    if not passed:
        all_passed = False
        results['profit_formula_consistency']['sample'] = details[:5]

    # Check 3: Pool totals vs positions (global check)
    if pool_nft is None:
        print("  Running: pool_totals_vs_positions...")
        passed, details = check_pool_totals_vs_positions(db)
        results['pool_totals_vs_positions'] = {'passed': passed, 'mismatched_pools_count': len(details)}
        if not passed:
            all_passed = False
            results['pool_totals_vs_positions']['details'] = details

    # Check 4: Derived positions vs on-chain positions
    if pool_nft is None:
        print("  Running: positions_vs_chain...")
        passed, details = check_positions_vs_chain(db)
        results['positions_vs_chain'] = {'passed': passed, 'mismatched_count': len(details)}
        if not passed:
            all_passed = False
            results['positions_vs_chain']['sample'] = details[:10]

    if all_passed:
        print("=== All Deep Verification Checks PASSED ===")
    else:
        print("=== Deep Verification FAILED ===")
        failed_checks = [k for k, v in results.items() if not v['passed']]
        print(f"Failed checks: {failed_checks}")

    return all_passed, results


# ========================================
# AUTO-REPAIR ROUTINE
# ========================================

def auto_repair_routine(db: DatabaseManager, pool_nft: str, failed_checks: List[str],
                        sync_user_deposits_historical_func=None,
                        sync_user_portfolio_snapshots_func=None,
                        pool_config: Optional[Dict] = None) -> bool:
    """
    Attempt automatic repair of derived tables when verification fails.
    Falls back to safe point if repair fails.

    Args:
        db: Database manager instance
        pool_nft: Pool NFT to repair
        failed_checks: List of check names that failed
        sync_user_deposits_historical_func: Function to rebuild deposits (from user_history_services)
        sync_user_portfolio_snapshots_func: Function to rebuild snapshots (from user_history_services)
        pool_config: Pool configuration dict

    Returns:
        True if repair was successful, False otherwise
    """
    print(f"\n=== Auto-Repair Triggered for {pool_nft[:16]}... ===")
    print(f"Failed checks: {failed_checks}")

    # Step 1: Try rebuilding derived tables (fast, non-destructive to facts)
    derived_table_issues = ['deposits_never_decrease', 'profit_formula_consistency']

    if any(check in failed_checks for check in derived_table_issues):
        print("Attempting to rebuild derived tables...")

        # Get current max height from facts
        max_height = db.get_max_block_height_for_pool('transactions', pool_nft)
        if max_height is None:
            print(f"ERROR: No transactions found for pool {pool_nft}")
            return False

        try:
            # Delete existing derived data for this pool
            print(f"  Deleting user_deposits_historical for pool...")
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM user_deposits_historical WHERE pool_nft = %s",
                        (pool_nft,)
                    )
                    deleted_deposits = cur.rowcount

                    cur.execute(
                        "DELETE FROM user_portfolio_snapshots WHERE pool_nft = %s",
                        (pool_nft,)
                    )
                    deleted_snapshots = cur.rowcount

                    conn.commit()

            print(f"  Deleted {deleted_deposits} deposit records and {deleted_snapshots} snapshot records")

            # Rebuild with full_scan=True if functions are provided
            if sync_user_deposits_historical_func and pool_config:
                print(f"  Rebuilding user_deposits_historical with full_scan...")
                sync_user_deposits_historical_func(db, pool_config, sync_block=max_height, full_scan=True)

            if sync_user_portfolio_snapshots_func and pool_config:
                print(f"  Rebuilding user_portfolio_snapshots...")
                sync_user_portfolio_snapshots_func(db, pool_config, sync_block=max_height)

            # Re-run verification to check if repair worked
            print("  Re-running verification checks...")
            passed, _ = check_deposits_never_decrease(db, pool_nft)
            if passed:
                passed2, _ = check_profit_formula_consistency(db, pool_nft)
                if passed2:
                    print("=== Repair Successful! ===")
                    return True

            print("Derived table rebuild did not fix the issue")

        except Exception as e:
            print(f"ERROR during repair: {e}")

    # Step 2: If derived rebuild didn't help, suggest manual intervention
    print("Derived rebuild insufficient or not applicable.")

    safe_height = db.get_safe_point(pool_nft)
    if safe_height > 0:
        print(f"Safe point available at block {safe_height}")
        print(f"MANUAL INTERVENTION NEEDED:")
        print(f"  1. Review the failed checks and determine root cause")
        print(f"  2. Consider resyncing from safe point: {safe_height}")
        print(f"  3. Run: resync_from_block(db, {safe_height})")
    else:
        print("No safe point set for this pool.")
        print("MANUAL INTERVENTION NEEDED:")
        print("  1. Review the failed checks and determine root cause")
        print("  2. Consider setting a safe point after manual verification")
        print("  3. Run full resync if needed")

    return False


def alert_operator(message: str):
    """
    Alert the operator about an issue that needs manual intervention.
    This could be extended to send emails, Slack messages, etc.

    Args:
        message: Alert message
    """
    print("\n" + "=" * 70)
    print("⚠️  OPERATOR ALERT ⚠️")
    print("=" * 70)
    print(message)
    print("=" * 70 + "\n")

    # TODO: Add integrations for:
    # - Email notifications
    # - Slack/Discord webhooks
    # - PagerDuty/OpsGenie
    # For now, just logs to console


# ========================================
# VERIFICATION INTEGRATION HELPERS
# ========================================

def verify_and_checkpoint(db: DatabaseManager, current_block: int,
                          pool_nft: Optional[str] = None) -> bool:
    """
    Run light verification and set checkpoint if successful.
    This should be called after each sync loop.

    Args:
        db: Database manager instance
        current_block: Current block height
        pool_nft: Optional pool NFT (None for global checkpoint)

    Returns:
        True if verification passed and checkpoint was set, False otherwise
    """
    passed, results = run_light_verification(db)

    if passed:
        # Set verified checkpoint
        db.set_checkpoint('verified', pool_nft, current_block,
                         notes=f'Light verification passed')

        # Also set ingested checkpoint
        db.set_checkpoint('ingested', pool_nft, current_block,
                         notes=f'Data ingested successfully')

        print(f"Checkpoints set at block {current_block}")
        return True
    else:
        # Don't update verified checkpoint on failure
        failed_checks = [k for k, v in results.items() if not v['passed']]
        print(f"Verification failed, checkpoints NOT updated. Failed: {failed_checks}")
        return False


def get_verification_status(db: DatabaseManager, pool_nft: Optional[str] = None) -> Dict:
    """
    Get the current verification status for monitoring.

    Args:
        db: Database manager instance
        pool_nft: Optional pool NFT (None for global status)

    Returns:
        Dict with verification status info
    """
    ingested = db.get_checkpoint('ingested', pool_nft)
    verified = db.get_checkpoint('verified', pool_nft)
    safe_point = db.get_safe_point(pool_nft)

    # Calculate lag between ingested and verified
    lag = 0
    if ingested and verified:
        lag = ingested - verified

    return {
        'pool_nft': pool_nft or 'global',
        'ingested_height': ingested,
        'verified_height': verified,
        'safe_point_height': safe_point,
        'verification_lag': lag,
        'status': 'healthy' if lag == 0 else ('warning' if lag < 1000 else 'critical')
    }
