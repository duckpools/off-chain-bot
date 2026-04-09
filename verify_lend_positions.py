#!/usr/bin/env python3
"""
Standalone verification script for lend position tracking (Pipeline 1).

Reads the [LEND_POS] entries from sync_services.log, replays all lend token
movements transaction-by-transaction, recalculates expected position_tokens,
and compares against the database entries in user_lend_positions_historical.

Usage:
    python verify_lend_positions.py [--address ADDRESS] [--pool POOL_NFT] [--log-file PATH]

If no address is given, processes all debug addresses found in the log.
"""

import argparse
import os
import re
import sys
from collections import defaultdict
from typing import Optional

# Add project root to path so we can import from the codebase
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.db_manager import DatabaseManager
from current_pools import current_pools


# ── Pool decimals lookup ────────────────────────────────────────────────────

def get_pool_decimals(pool_nft: str) -> int:
    """Look up the decimals for a pool by its NFT ID."""
    for pool in current_pools:
        if pool.get("POOL_NFT") == pool_nft:
            return pool["decimals"]
    # Fallback: try to infer from data
    print(f"  WARNING: Could not find pool {pool_nft[:16]}... in current_pools, using decimals=9")
    return 9


# ── Log file splitting ──────────────────────────────────────────────────────

LOG_TAGS = {
    "TX_SERVICE":  "logs/stage1_tx_service.log",
    "LEND_POS":    "logs/stage2_lend_positions.log",
    "DEPOSITS":    "logs/stage3_deposits.log",
    "GRANULAR":    "logs/stage4_granular.log",
    "PORTFOLIO":   "logs/stage5_portfolio.log",
}

TAG_PATTERN = re.compile(r"\[(" + "|".join(LOG_TAGS.keys()) + r")\]")
SYNC_LINE   = re.compile(r"^[\d\-]+ [\d:,]+ - sync_services -")


def split_log_file(src: str, dest_dir: str) -> dict:
    """Split sync_services.log into per-stage files. Returns {tag: path}."""
    os.makedirs(dest_dir, exist_ok=True)

    handles = {}
    paths = {}
    for tag, relpath in LOG_TAGS.items():
        p = os.path.join(dest_dir, os.path.basename(relpath))
        handles[tag] = open(p, "w")
        paths[tag] = p

    # Also capture the sync_services orchestration lines
    sync_handle = open(os.path.join(dest_dir, "stage0_sync_orchestration.log"), "w")

    with open(src) as f:
        for line in f:
            m = TAG_PATTERN.search(line)
            if m:
                handles[m.group(1)].write(line)
            elif SYNC_LINE.match(line):
                sync_handle.write(line)

    for h in handles.values():
        h.close()
    sync_handle.close()

    for tag, p in paths.items():
        count = sum(1 for _ in open(p))
        print(f"  [{tag:12s}] -> {p}  ({count} lines)")

    return paths


# ── Log parsing ─────────────────────────────────────────────────────────────

# [LEND_POS] tx=<txid> | pool=<pool> | addr=<addr> | block=<block> |
#            input_tokens=<f> | output_tokens=<f> | net_change=<f>
LEND_POS_LINE = re.compile(
    r"\[LEND_POS\] tx=(?P<tx>\S+) \| pool=(?P<pool>\S+) \| addr=(?P<addr>\S+) \| "
    r"block=(?P<block>\d+) \| input_tokens=(?P<input>[\d.]+) \| "
    r"output_tokens=(?P<output>[\d.]+) \| net_change=(?P<net>[\-\d.]+)"
)

# [LEND_POS] POSITION_UPDATE tx=<txid> | pool=<pool> | addr=<addr> | block=<block> |
#            ts=<ts> | old_pos_raw=<f> | net_change=<f> | new_pos_raw=<f> |
#            new_pos_friendly=<f> | lend_token_value=<f> | position_value=<f>
POS_UPDATE_LINE = re.compile(
    r"\[LEND_POS\] POSITION_UPDATE tx=(?P<tx>\S+) \| pool=(?P<pool>\S+) \| "
    r"addr=(?P<addr>\S+) \| block=(?P<block>\d+) \| ts=(?P<ts>\d+) \| "
    r"old_pos_raw=(?P<old_pos>[\-\d.]+) \| net_change=(?P<net_change>[\-\d.]+) \| "
    r"new_pos_raw=(?P<new_pos>[\-\d.]+) \| new_pos_friendly=(?P<friendly>[\-\d.]+) \| "
    r"lend_token_value=(?P<ltv>\S+) \| position_value=(?P<pv>\S+)"
)

# [LEND_POS] CONSOLIDATED_RECORD pool=<pool> | addr=<addr> | block=<block> |
#            ts=<ts> | position_tokens=<f> | position_value=<f> | sync_block=<sb>
CONSOLIDATED_LINE = re.compile(
    r"\[LEND_POS\] CONSOLIDATED_RECORD pool=(?P<pool>\S+) \| addr=(?P<addr>\S+) \| "
    r"block=(?P<block>\d+) \| ts=(?P<ts>\d+) \| position_tokens=(?P<tokens>[\-\d.]+) \| "
    r"position_value=(?P<pv>\S+) \| sync_block=(?P<sb>\d+)"
)


class LendPosEntry:
    """A single input/output log entry (not necessarily a position change)."""
    def __init__(self, tx, pool, addr, block, input_tokens, output_tokens, net_change):
        self.tx = tx
        self.pool = pool
        self.addr = addr
        self.block = int(block)
        self.input_tokens = float(input_tokens)
        self.output_tokens = float(output_tokens)
        self.net_change = float(net_change)


class PosUpdateEntry:
    """A POSITION_UPDATE log entry — produced when net_change != 0."""
    def __init__(self, tx, pool, addr, block, ts, old_pos, net_change, new_pos,
                 friendly, ltv, pv):
        self.tx = tx
        self.pool = pool
        self.addr = addr
        self.block = int(block)
        self.ts = int(ts)
        self.old_pos = float(old_pos)
        self.net_change = float(net_change)
        self.new_pos = float(new_pos)
        self.friendly = float(friendly)
        self.ltv = ltv      # kept as string (may be -1)
        self.pv = pv        # kept as string


def parse_lend_pos_log(path: str, address_filter: Optional[str] = None,
                       pool_filter: Optional[str] = None):
    """
    Parse the stage2_lend_positions.log file.
    Returns (movements, updates, consolidated) — lists filtered by address/pool.
    """
    movements = []   # LendPosEntry
    updates = []     # PosUpdateEntry
    consolidated = []

    with open(path) as f:
        for line in f:
            m = POS_UPDATE_LINE.search(line)
            if m:
                d = m.groupdict()
                if address_filter and d["addr"] != address_filter:
                    continue
                if pool_filter and d["pool"] != pool_filter:
                    continue
                updates.append(PosUpdateEntry(**d))
                continue

            m = CONSOLIDATED_LINE.search(line)
            if m:
                d = m.groupdict()
                if address_filter and d["addr"] != address_filter:
                    continue
                if pool_filter and d["pool"] != pool_filter:
                    continue
                consolidated.append(d)
                continue

            m = LEND_POS_LINE.search(line)
            if m:
                d = m.groupdict()
                if address_filter and d["addr"] != address_filter:
                    continue
                if pool_filter and d["pool"] != pool_filter:
                    continue
                movements.append(LendPosEntry(
                    tx=d["tx"], pool=d["pool"], addr=d["addr"],
                    block=d["block"], input_tokens=d["input"],
                    output_tokens=d["output"], net_change=d["net"]
                ))

    return movements, updates, consolidated


# ── Database verification ───────────────────────────────────────────────────

def get_db_positions(db: DatabaseManager, address: str, pool_nft: str) -> dict:
    """
    Query all user_lend_positions_historical entries for an address+pool.
    Returns {block_height: {position_tokens, position_value, timestamp}}.
    """
    query = """
        SELECT lp.block_height, lp.position_tokens, lp.position_value, lp.timestamp
        FROM user_lend_positions_historical lp
        JOIN addresses a ON lp.address_id = a.id
        WHERE a.address = %s
          AND lp.pool_nft = %s
        ORDER BY lp.block_height ASC
    """
    rows = db.execute_query(query, (address, pool_nft))
    result = {}
    for r in rows:
        result[r["block_height"]] = {
            "position_tokens": float(r["position_tokens"]),
            "position_value":  float(r["position_value"]),
            "timestamp":       r["timestamp"],
        }
    return result


# ── Verification logic ──────────────────────────────────────────────────────

def verify_address(movements, updates, db_positions, address, pool, decimals=9):
    """
    Replay lend token movements and compare against:
      1) The POSITION_UPDATE log entries
      2) The database entries

    Returns a list of discrepancy dicts.
    """
    issues = []
    running_pos_raw = 0.0  # running position in raw token units

    # Build a lookup: (tx, block) -> PosUpdateEntry
    update_map = {}
    for u in updates:
        update_map[(u.tx, u.block)] = u

    # Group movements by (block, tx) for chronological replay
    # movements are already in log order which is chronological
    for mv in movements:
        if mv.addr != address:
            continue

        # --- Step 1: Verify input/output math ---
        expected_net = mv.output_tokens - mv.input_tokens
        if abs(expected_net - mv.net_change) > 0.01:
            issues.append({
                "type": "LOG_MATH_ERROR",
                "tx": mv.tx,
                "block": mv.block,
                "detail": f"output({mv.output_tokens}) - input({mv.input_tokens}) = "
                          f"{expected_net}, but log says net_change={mv.net_change}"
            })

        if mv.net_change == 0:
            continue  # no position update expected

        old_pos = running_pos_raw
        running_pos_raw += mv.net_change
        expected_friendly = running_pos_raw / (10 ** decimals)

        # --- Step 2: Verify against POSITION_UPDATE log ---
        upd = update_map.get((mv.tx, mv.block))
        if upd is None:
            issues.append({
                "type": "MISSING_UPDATE_LOG",
                "tx": mv.tx,
                "block": mv.block,
                "detail": f"net_change={mv.net_change} but no POSITION_UPDATE logged"
            })
        else:
            # Check old_pos matches
            if abs(upd.old_pos - old_pos) > 0.5:
                issues.append({
                    "type": "OLD_POS_MISMATCH",
                    "tx": mv.tx,
                    "block": mv.block,
                    "detail": f"Expected old_pos_raw={old_pos:.6f}, "
                              f"log says {upd.old_pos:.6f}"
                })

            # Check new_pos matches
            if abs(upd.new_pos - running_pos_raw) > 0.5:
                issues.append({
                    "type": "NEW_POS_MISMATCH",
                    "tx": mv.tx,
                    "block": mv.block,
                    "detail": f"Expected new_pos_raw={running_pos_raw:.6f}, "
                              f"log says {upd.new_pos:.6f}"
                })

            # Check friendly conversion
            if abs(upd.friendly - expected_friendly) > 1e-8:
                issues.append({
                    "type": "FRIENDLY_MISMATCH",
                    "tx": mv.tx,
                    "block": mv.block,
                    "detail": f"Expected friendly={expected_friendly:.10f}, "
                              f"log says {upd.friendly:.10f}"
                })

        # --- Step 3: Verify against database ---
        db_entry = db_positions.get(mv.block)
        if db_entry is None:
            issues.append({
                "type": "MISSING_DB_ENTRY",
                "tx": mv.tx,
                "block": mv.block,
                "detail": f"No DB entry at block {mv.block} for this address/pool. "
                          f"Expected position_tokens={expected_friendly:.10f}"
            })
        else:
            db_tokens = db_entry["position_tokens"]
            # The DB might consolidate multiple txs in the same block.
            # We only check the final position at the block after all movements.
            # So we defer DB check to a second pass below.
            pass

    # --- Second pass: verify final DB values per block ---
    # Replay again to get final position per block
    block_final_pos = {}
    replay_pos = 0.0
    for mv in movements:
        if mv.addr != address or mv.net_change == 0:
            continue
        replay_pos += mv.net_change
        friendly = replay_pos / (10 ** decimals)
        block_final_pos[mv.block] = friendly  # last write wins for same block

    for block, expected_tokens in block_final_pos.items():
        db_entry = db_positions.get(block)
        if db_entry is None:
            # Already reported above
            continue
        db_tokens = db_entry["position_tokens"]
        if abs(db_tokens - expected_tokens) > 1e-8:
            issues.append({
                "type": "DB_POSITION_MISMATCH",
                "tx": "consolidated",
                "block": block,
                "detail": f"DB position_tokens={db_tokens:.10f}, "
                          f"expected={expected_tokens:.10f}, "
                          f"diff={db_tokens - expected_tokens:.10f}"
            })

    return issues, block_final_pos, running_pos_raw


# ── Reporting ───────────────────────────────────────────────────────────────

def print_movement_table(movements, updates, address, decimals=9):
    """Print a readable table of all movements for an address."""
    print(f"\n{'='*120}")
    print(f"  LEND TOKEN MOVEMENTS for {address}")
    print(f"{'='*120}")
    print(f"{'Block':>10} | {'TX (first 16)':16} | {'Input Tokens':>16} | "
          f"{'Output Tokens':>16} | {'Net Change':>16} | {'Running Pos':>16} | {'Friendly':>14}")
    print(f"{'-'*10}-+-{'-'*16}-+-{'-'*16}-+-{'-'*16}-+-{'-'*16}-+-{'-'*16}-+-{'-'*14}")

    running = 0.0
    for mv in movements:
        if mv.addr != address:
            continue
        running += mv.net_change
        friendly = running / (10 ** decimals)
        marker = "" if mv.net_change == 0 else " *"
        print(f"{mv.block:>10} | {mv.tx[:16]:16} | {mv.input_tokens:>16.2f} | "
              f"{mv.output_tokens:>16.2f} | {mv.net_change:>16.2f} | "
              f"{running:>16.2f} | {friendly:>14.10f}{marker}")


def print_db_comparison(block_final_pos, db_positions):
    """Print side-by-side comparison of calculated vs DB positions."""
    all_blocks = sorted(set(block_final_pos.keys()) | set(db_positions.keys()))
    print(f"\n{'Block':>10} | {'Calculated':>16} | {'DB Value':>16} | {'Match':>6} | {'Source'}")
    print(f"{'-'*10}-+-{'-'*16}-+-{'-'*16}-+-{'-'*6}-+-{'-'*10}")

    for block in all_blocks:
        calc = block_final_pos.get(block)
        db_val = db_positions.get(block, {}).get("position_tokens")

        if calc is not None and db_val is not None:
            match = abs(calc - db_val) < 1e-8
            print(f"{block:>10} | {calc:>16.10f} | {db_val:>16.10f} | "
                  f"{'  OK  ' if match else ' FAIL '} | tx+db")
        elif calc is not None:
            print(f"{block:>10} | {calc:>16.10f} | {'(missing)':>16} | {'MISS':>6} | tx only")
        else:
            # DB has entry but no movement log (likely granular/interpolated)
            print(f"{block:>10} | {'(granular)':>16} | {db_val:>16.10f} | {'  --  ':>6} | db only (granular)")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Verify lend position tracking")
    parser.add_argument("--address", "-a", help="Filter to a specific address")
    parser.add_argument("--pool", "-p", help="Filter to a specific pool NFT")
    parser.add_argument("--log-file", default="sync_services.log",
                        help="Path to sync_services.log (default: sync_services.log)")
    parser.add_argument("--decimals", type=int, default=None,
                        help="Override token decimals (auto-detected from pool config if not set)")
    parser.add_argument("--no-db", action="store_true",
                        help="Skip database verification")
    parser.add_argument("--no-split", action="store_true",
                        help="Skip log splitting (use existing split files)")
    args = parser.parse_args()

    # Step 1: Split the log file
    log_dir = os.path.join(os.path.dirname(os.path.abspath(args.log_file)), "logs")
    if not args.no_split:
        print("Step 1: Splitting log file into per-stage files...")
        split_log_file(args.log_file, log_dir)
    else:
        print("Step 1: Skipping log split (--no-split)")

    lend_pos_log = os.path.join(log_dir, "stage2_lend_positions.log")
    if not os.path.exists(lend_pos_log):
        print(f"ERROR: {lend_pos_log} not found. Run without --no-split first.")
        sys.exit(1)

    # Step 2: Parse lend position log
    print(f"\nStep 2: Parsing {lend_pos_log}...")
    movements, updates, consolidated = parse_lend_pos_log(
        lend_pos_log,
        address_filter=args.address,
        pool_filter=args.pool
    )
    print(f"  Parsed {len(movements)} movement entries, {len(updates)} position updates, "
          f"{len(consolidated)} consolidated records")

    # Discover unique address+pool combinations
    addr_pools = set()
    for mv in movements:
        addr_pools.add((mv.addr, mv.pool))
    for u in updates:
        addr_pools.add((u.addr, u.pool))

    if not addr_pools:
        print("No lend position data found for the given filters.")
        sys.exit(0)

    print(f"  Found {len(addr_pools)} address+pool combinations")

    # Step 3: Connect to DB (if needed)
    db = None
    if not args.no_db:
        print("\nStep 3: Connecting to database...")
        try:
            db = DatabaseManager()
            print("  Connected successfully")
        except Exception as e:
            print(f"  WARNING: Could not connect to DB: {e}")
            print("  Continuing without DB verification...")

    # Step 4: Verify each address+pool
    total_issues = 0
    for addr, pool in sorted(addr_pools):
        print(f"\n{'#'*120}")
        print(f"  Verifying: {addr}")
        print(f"  Pool:      {pool[:16]}...")
        print(f"{'#'*120}")

        # Filter movements and updates for this address+pool
        addr_movements = [m for m in movements if m.addr == addr and m.pool == pool]
        addr_updates = [u for u in updates if u.addr == addr and u.pool == pool]

        # Look up correct decimals for this pool (CLI override takes precedence)
        decimals = args.decimals if args.decimals is not None else get_pool_decimals(pool)
        print(f"  Decimals: {decimals}")

        # Print movement table
        print_movement_table(addr_movements, addr_updates, addr, decimals)

        # Get DB data
        db_positions = {}
        if db:
            db_positions = get_db_positions(db, addr, pool)
            print(f"\n  DB entries for this address+pool: {len(db_positions)}")

        # Run verification
        issues, block_final_pos, final_raw = verify_address(
            addr_movements, addr_updates, db_positions, addr, pool,
            decimals=decimals
        )

        # Print DB comparison
        if db_positions:
            print(f"\n  Position comparison (calculated from log vs database):")
            print_db_comparison(block_final_pos, db_positions)

        # Print final state
        final_friendly = final_raw / (10 ** decimals)
        print(f"\n  Final position (from log replay): {final_friendly:.10f} "
              f"(raw: {final_raw:.2f})")

        if db_positions:
            # Find the highest block from movements
            max_mv_block = max(block_final_pos.keys()) if block_final_pos else 0
            db_at_max = db_positions.get(max_mv_block)
            if db_at_max:
                print(f"  Final position (from DB at block {max_mv_block}): "
                      f"{db_at_max['position_tokens']:.10f}")

        # Print issues
        if issues:
            print(f"\n  *** {len(issues)} ISSUES FOUND ***")
            for i, issue in enumerate(issues, 1):
                print(f"    {i}. [{issue['type']}] block={issue['block']} "
                      f"tx={issue['tx'][:16]}... | {issue['detail']}")
            total_issues += len(issues)
        else:
            print(f"\n  ALL CHECKS PASSED")

    # Summary
    print(f"\n{'='*120}")
    print(f"  SUMMARY")
    print(f"{'='*120}")
    print(f"  Address+pool combinations checked: {len(addr_pools)}")
    print(f"  Total issues found: {total_issues}")
    if total_issues == 0:
        print(f"  Result: ALL LEND POSITION TRACKING IS CORRECT")
    else:
        print(f"  Result: DISCREPANCIES DETECTED — see details above")
    print()


if __name__ == "__main__":
    main()
