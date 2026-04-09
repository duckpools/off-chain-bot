#!/usr/bin/env python3
"""
Standalone verification script for portfolio/profit snapshots (Pipeline 3).

Checks:
  1) Profit formula consistency: total_profit == position_value + total_withdrawn - total_deposited
  2) Position alignment: position_value in snapshots matches user_lend_positions_historical
  3) Deposit alignment: total_deposited/withdrawn matches the most recent user_deposits_historical
  4) Terminal state: detects cases where position goes to 0 but later deposits exist (the 2-step proxy bug)

Usage:
    python3 verify_portfolio.py [--address ADDRESS] [--pool POOL_NFT]
    python3 verify_portfolio.py --no-split   # reuse already-split logs
"""

import argparse
import os
import re
import sys
from decimal import Decimal
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.db_manager import DatabaseManager
from current_pools import current_pools

# ── Constants ────────────────────────────────────────────────────────────────

PORTFOLIO_LOG = os.path.join(os.path.dirname(__file__), "logs", "stage5_portfolio.log")
SYNC_LOG = os.path.join(os.path.dirname(__file__), "sync_services.log")
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")

# Tolerance for floating point comparisons
TOLERANCE = Decimal("0.0001")

# ── Parsing ──────────────────────────────────────────────────────────────────

SNAPSHOT_RE = re.compile(
    r"\[PORTFOLIO\] SNAPSHOT pool=(?P<pool>[a-f0-9]+)\s*\|\s*"
    r"addr=(?P<addr>\S+)\s*\|\s*"
    r"block=(?P<block>\d+)\s*\|\s*"
    r"ts=(?P<ts>\d+)\s*\|\s*"
    r"position_value=(?P<position_value>[\-\d.]+)\s*\|\s*"
    r"total_deposited=(?P<total_deposited>[\-\d.]+)\s*\|\s*"
    r"total_withdrawn=(?P<total_withdrawn>[\-\d.]+)\s*\|\s*"
    r"total_profit=(?P<total_profit>[\-\d.]+)\s*\|\s*"
    r"recalculated=(?P<recalculated>[\-\d.]+)\s*\|\s*"
    r"drift=(?P<drift>[\-\d.]+)"
)


def parse_portfolio_log(log_file: str) -> list:
    """Parse [PORTFOLIO] SNAPSHOT entries from the log."""
    entries = []
    if not os.path.exists(log_file):
        print(f"  Log file not found: {log_file}")
        return entries

    with open(log_file) as f:
        for line in f:
            m = SNAPSHOT_RE.search(line)
            if m:
                entries.append({
                    "pool": m.group("pool"),
                    "addr": m.group("addr"),
                    "block": int(m.group("block")),
                    "ts": int(m.group("ts")),
                    "position_value": Decimal(m.group("position_value")),
                    "total_deposited": Decimal(m.group("total_deposited")),
                    "total_withdrawn": Decimal(m.group("total_withdrawn")),
                    "total_profit": Decimal(m.group("total_profit")),
                    "recalculated": Decimal(m.group("recalculated")),
                    "drift": Decimal(m.group("drift")),
                })
    return entries


def split_logs():
    """Split sync_services.log into per-stage files (reuse from verify_lend_positions)."""
    if not os.path.exists(SYNC_LOG):
        print(f"sync_services.log not found at {SYNC_LOG}")
        return False
    os.makedirs(LOGS_DIR, exist_ok=True)
    # Import the splitter from existing script if available
    try:
        from verify_lend_positions import split_sync_log
        split_sync_log(SYNC_LOG, LOGS_DIR)
        return True
    except ImportError:
        print("Cannot import split_sync_log from verify_lend_positions.py")
        return False


# ── Database queries ─────────────────────────────────────────────────────────

def get_db():
    db = DatabaseManager()
    return db


def get_address_id(db, address: str) -> Optional[int]:
    """Get address_id from the addresses table."""
    rows = db.execute_query("SELECT id FROM addresses WHERE address = %s", (address,))
    if rows:
        return rows[0]["id"]
    return None


def get_portfolio_snapshots_from_db(db, address_id: int, pool_nft: str) -> list:
    """Get all portfolio snapshots from the DB for an address+pool."""
    rows = db.execute_query(
        """SELECT block_height, timestamp, position_value, total_profit, sync_block
           FROM user_portfolio_snapshots
           WHERE address_id = %s AND pool_nft = %s
           ORDER BY block_height ASC""",
        (address_id, pool_nft)
    )
    return rows or []


def get_last_position_entry(db, address_id: int, pool_nft: str) -> Optional[dict]:
    """Get the last (highest block) position entry for an address+pool."""
    rows = db.execute_query(
        """SELECT block_height, position_tokens, position_value
           FROM user_lend_positions_historical
           WHERE address_id = %s AND pool_nft = %s
           ORDER BY block_height DESC, id DESC
           LIMIT 1""",
        (address_id, pool_nft)
    )
    return rows[0] if rows else None


def get_position_at_block(db, address_id: int, pool_nft: str, block_height: int) -> Optional[dict]:
    """Get the position entry at or just before a given block height."""
    rows = db.execute_query(
        """SELECT block_height, position_tokens, position_value
           FROM user_lend_positions_historical
           WHERE address_id = %s AND pool_nft = %s AND block_height <= %s
           ORDER BY block_height DESC, id DESC
           LIMIT 1""",
        (address_id, pool_nft, block_height)
    )
    return rows[0] if rows else None


def get_deposits_at_block(db, address_id: int, pool_nft: str, block_height: int) -> Optional[dict]:
    """Get the deposit entry at or just before a given block height (same LATERAL JOIN logic)."""
    rows = db.execute_query(
        """SELECT block_height, total_deposited, total_withdrawn
           FROM user_deposits_historical
           WHERE address_id = %s AND pool_nft = %s AND block_height <= %s
           ORDER BY block_height DESC, id DESC
           LIMIT 1""",
        (address_id, pool_nft, block_height)
    )
    return rows[0] if rows else None


def get_last_deposit_entry(db, address_id: int, pool_nft: str) -> Optional[dict]:
    """Get the very last deposit entry for an address+pool (no block constraint)."""
    rows = db.execute_query(
        """SELECT block_height, total_deposited, total_withdrawn
           FROM user_deposits_historical
           WHERE address_id = %s AND pool_nft = %s
           ORDER BY block_height DESC, id DESC
           LIMIT 1""",
        (address_id, pool_nft)
    )
    return rows[0] if rows else None


# ── Verification ─────────────────────────────────────────────────────────────

def verify_address_pool(db, address: str, pool_nft: str, snapshots: list) -> list:
    """Verify all portfolio snapshots for one address+pool combination."""
    issues = []
    address_id = get_address_id(db, address)
    if address_id is None:
        issues.append(("ADDRESS_NOT_FOUND", f"Address {address} not in DB"))
        return issues

    # Get DB data
    db_snapshots = get_portfolio_snapshots_from_db(db, address_id, pool_nft)
    last_position = get_last_position_entry(db, address_id, pool_nft)
    last_deposit = get_last_deposit_entry(db, address_id, pool_nft)

    print(f"  DB snapshots: {len(db_snapshots)}")
    print(f"  Log snapshots: {len(snapshots)}")
    if last_position:
        print(f"  Last position: block={last_position['block_height']}, tokens={last_position['position_tokens']}, value={last_position['position_value']}")
    if last_deposit:
        print(f"  Last deposit: block={last_deposit['block_height']}, deposited={last_deposit['total_deposited']}, withdrawn={last_deposit['total_withdrawn']}")

    # ── Check 1: Profit formula consistency (drift should be 0) ──────────
    drift_issues = 0
    for snap in snapshots:
        expected_profit = snap["position_value"] + snap["total_withdrawn"] - snap["total_deposited"]
        actual_drift = abs(snap["total_profit"] - expected_profit)
        if actual_drift > TOLERANCE:
            drift_issues += 1
            issues.append((
                "PROFIT_FORMULA_DRIFT",
                f"block={snap['block']} | profit={snap['total_profit']}, "
                f"expected={expected_profit}, drift={actual_drift}"
            ))
    if drift_issues == 0:
        print(f"  Profit formula: ALL {len(snapshots)} snapshots consistent (drift=0)")

    # ── Check 2: Terminal state bug (position=0 but deposits exist after) ──
    if last_position and last_deposit:
        last_pos_block = last_position["block_height"]
        last_pos_tokens = float(last_position["position_tokens"])
        last_dep_block = last_deposit["block_height"]

        if last_pos_tokens == 0 and last_dep_block > last_pos_block:
            # This is THE BUG: deposits exist after the last position entry
            # The portfolio will use stale deposit data for the final snapshot
            dep_at_last_pos = get_deposits_at_block(db, address_id, pool_nft, last_pos_block)
            dep_at_final = last_deposit

            stale_deposited = float(dep_at_last_pos["total_deposited"]) if dep_at_last_pos else 0
            stale_withdrawn = float(dep_at_last_pos["total_withdrawn"]) if dep_at_last_pos else 0
            final_deposited = float(dep_at_final["total_deposited"])
            final_withdrawn = float(dep_at_final["total_withdrawn"])

            stale_profit = 0 + stale_withdrawn - stale_deposited  # position=0
            correct_profit = 0 + final_withdrawn - final_deposited  # position=0

            print()
            print(f"  *** 2-STEP PROXY BUG DETECTED ***")
            print(f"  Last position entry: block={last_pos_block}, tokens={last_pos_tokens}")
            print(f"  Last deposit entry:  block={last_dep_block}")
            print(f"  Gap: {last_dep_block - last_pos_block} blocks")
            print(f"  Stale deposits at block {last_pos_block}: deposited={stale_deposited:.10f}, withdrawn={stale_withdrawn:.10f}")
            print(f"  Final deposits at block {last_dep_block}: deposited={final_deposited:.10f}, withdrawn={final_withdrawn:.10f}")
            print(f"  Shown profit (wrong):   {stale_profit:.10f}")
            print(f"  Correct profit:         {correct_profit:.10f}")
            print(f"  Error magnitude:        {abs(correct_profit - stale_profit):.10f}")

            issues.append((
                "TERMINAL_STATE_BUG",
                f"Last position at block {last_pos_block} (tokens=0), "
                f"last deposit at block {last_dep_block} (gap={last_dep_block - last_pos_block}). "
                f"Shown profit={stale_profit:.4f}, correct={correct_profit:.4f}, "
                f"error={abs(correct_profit - stale_profit):.4f}"
            ))

    # ── Check 3: Intermediate timing misalignment ────────────────────────
    # Find snapshots where position dropped significantly but deposits haven't caught up
    timing_issues = 0
    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1]
        curr = snapshots[i]

        pos_change = curr["position_value"] - prev["position_value"]
        dep_change = (curr["total_deposited"] - prev["total_deposited"]) - \
                     (curr["total_withdrawn"] - prev["total_withdrawn"])

        # A lend increases both position_value and total_deposited
        # A withdraw decreases position_value and increases total_withdrawn
        # If position drops significantly but deposits don't change, it's a timing gap
        if pos_change < Decimal("-1.0") and abs(dep_change) < TOLERANCE:
            # Position dropped but deposits didn't change - could be:
            # 1. Tokens sent to proxy (2-step) - timing issue
            # 2. Liquidation - legitimate
            # 3. Wallet transfer out - expected
            # Flag if the drop is large relative to the position
            if prev["position_value"] > 0:
                drop_pct = abs(pos_change) / prev["position_value"] * 100
                if drop_pct > 50:
                    timing_issues += 1
                    issues.append((
                        "TIMING_GAP",
                        f"block={prev['block']}→{curr['block']} | "
                        f"position dropped {pos_change:.4f} ({drop_pct:.1f}%) "
                        f"but deposits unchanged. profit swung from "
                        f"{prev['total_profit']:.4f} to {curr['total_profit']:.4f}"
                    ))
    if timing_issues:
        print(f"  Timing gaps: {timing_issues} instances where position dropped >50% without deposit change")

    # ── Check 4: Verify sample of snapshots against DB ───────────────────
    # Check first, last, and a few middle snapshots
    if snapshots:
        sample_indices = [0, len(snapshots) - 1]
        if len(snapshots) > 10:
            sample_indices.extend([len(snapshots) // 4, len(snapshots) // 2, 3 * len(snapshots) // 4])
        sample_indices = sorted(set(sample_indices))

        db_match_ok = 0
        db_match_fail = 0
        for idx in sample_indices:
            snap = snapshots[idx]
            # Check position_value against position DB
            pos = get_position_at_block(db, address_id, pool_nft, snap["block"])
            if pos:
                db_pos_value = Decimal(str(pos["position_value"]))
                if abs(db_pos_value - snap["position_value"]) > TOLERANCE:
                    db_match_fail += 1
                    issues.append((
                        "POSITION_VALUE_MISMATCH",
                        f"block={snap['block']} | log={snap['position_value']}, db={db_pos_value}"
                    ))
                else:
                    db_match_ok += 1

            # Check deposits against deposits DB
            dep = get_deposits_at_block(db, address_id, pool_nft, snap["block"])
            if dep:
                db_deposited = Decimal(str(dep["total_deposited"]))
                db_withdrawn = Decimal(str(dep["total_withdrawn"]))
                if abs(db_deposited - snap["total_deposited"]) > TOLERANCE:
                    db_match_fail += 1
                    issues.append((
                        "DEPOSITED_MISMATCH",
                        f"block={snap['block']} | log={snap['total_deposited']}, db={db_deposited}"
                    ))
                elif abs(db_withdrawn - snap["total_withdrawn"]) > TOLERANCE:
                    db_match_fail += 1
                    issues.append((
                        "WITHDRAWN_MISMATCH",
                        f"block={snap['block']} | log={snap['total_withdrawn']}, db={db_withdrawn}"
                    ))
                else:
                    db_match_ok += 1

        print(f"  DB spot checks: {db_match_ok} OK, {db_match_fail} mismatches (from {len(sample_indices)} sample points)")

    return issues


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Verify Pipeline 3 (portfolio/profit snapshots)")
    parser.add_argument("--address", help="Filter by specific address")
    parser.add_argument("--pool", help="Filter by specific pool NFT (prefix match)")
    parser.add_argument("--no-split", action="store_true", help="Skip re-splitting logs")
    args = parser.parse_args()

    # Split logs if needed
    if not args.no_split:
        if not split_logs():
            print("Failed to split logs, trying with existing split files...")

    # Parse portfolio log
    print(f"Parsing {PORTFOLIO_LOG}...")
    snapshots = parse_portfolio_log(PORTFOLIO_LOG)
    print(f"  {len(snapshots)} snapshot entries")

    if not snapshots:
        print("No snapshot entries found!")
        return

    # Group by (addr, pool)
    groups = {}
    for snap in snapshots:
        key = (snap["addr"], snap["pool"])
        if args.address and snap["addr"] != args.address:
            continue
        if args.pool and not snap["pool"].startswith(args.pool):
            continue
        groups.setdefault(key, []).append(snap)

    print(f"  Found {len(groups)} address+pool combinations")

    # Connect to DB
    print("\nConnecting to database...")
    db = get_db()
    print("  Connected")

    all_issues = []

    for (addr, pool), addr_snaps in sorted(groups.items()):
        print()
        print("#" * 140)
        print(f"  Address: {addr}")
        print(f"  Pool:    {pool[:16]}...")
        print("#" * 140)

        issues = verify_address_pool(db, addr, pool, addr_snaps)
        all_issues.extend(issues)

        if not issues:
            print(f"\n  ALL CHECKS PASSED")
        else:
            print(f"\n  *** {len(issues)} ISSUES FOUND ***")
            for i, (code, detail) in enumerate(issues, 1):
                print(f"    {i}. [{code}] {detail}")

    # Summary
    print()
    print("=" * 140)
    print("  SUMMARY")
    print("=" * 140)
    print(f"  Address+pool combinations: {len(groups)}")
    print(f"  Total issues: {len(all_issues)}")

    # Categorize issues
    categories = {}
    for code, detail in all_issues:
        categories.setdefault(code, []).append(detail)
    for code, details in sorted(categories.items()):
        print(f"    {code}: {len(details)}")

    if all_issues:
        print(f"  Result: DISCREPANCIES DETECTED")
    else:
        print(f"  Result: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
