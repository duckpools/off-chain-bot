#!/usr/bin/env python3
"""
Standalone verification script for deposit/withdrawal tracking (Pipeline 2).

Reads the [TX_SERVICE] log (classified transactions) and replays the deposit
accumulation logic: for each lend/withdraw tx, computes cumulative
total_deposited and total_withdrawn, then compares against:
  1) The [DEPOSITS] log entries (LEND_CALC / WITHDRAW_CALC / UPSERT)
  2) The database entries in user_deposits_historical

Usage:
    python3 verify_deposits.py [--address ADDRESS] [--pool POOL_NFT]
    python3 verify_deposits.py --no-split   # reuse already-split logs
"""

import argparse
import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.db_manager import DatabaseManager
from current_pools import current_pools


# ── Parsing: TX_SERVICE log ─────────────────────────────────────────────────

TX_LINE = re.compile(
    r"\[TX_SERVICE\] CLASSIFIED tx_id=(?P<tx_id>\S+) \| pool=(?P<pool>\S+) \| "
    r"addr=(?P<addr>\S+) \| type=(?P<type>\w+) \| "
    r"raw_amount=\S+ \| amount_friendly=(?P<amount>[\d.]+) \| "
    r"raw_fee=\S+ \| fee_friendly=(?P<fee>[\d.]+) \| "
    r".*?block=(?P<block>\d+) \| ts=(?P<ts>\d+) \| "
    r"main_tx_id=\S+ \| final_tx_id=(?P<final_tx>\S+)"
)


class ClassifiedTx:
    def __init__(self, tx_id, pool, addr, tx_type, amount, fee, block, ts, final_tx):
        self.tx_id = tx_id
        self.pool = pool
        self.addr = addr
        self.tx_type = tx_type
        self.amount = float(amount)
        self.fee = float(fee)
        self.block = int(block)
        self.ts = int(ts)
        self.final_tx = final_tx


def parse_tx_service_log(path, address_filter=None, pool_filter=None):
    txs = []
    with open(path) as f:
        for line in f:
            m = TX_LINE.search(line)
            if not m:
                continue
            d = m.groupdict()
            if address_filter and d["addr"] != address_filter:
                continue
            if pool_filter and d["pool"] != pool_filter:
                continue
            txs.append(ClassifiedTx(
                tx_id=d["tx_id"], pool=d["pool"], addr=d["addr"],
                tx_type=d["type"], amount=d["amount"], fee=d["fee"],
                block=d["block"], ts=d["ts"], final_tx=d["final_tx"]
            ))
    return txs


# ── Parsing: DEPOSITS log ──────────────────────────────────────────────────

UPSERT_LINE = re.compile(
    r"\[DEPOSITS\] UPSERT tx_id=(?P<tx_id>\S+) \| pool=(?P<pool>\S+) \| "
    r"addr=(?P<addr>\S+) \| block=(?P<block>\d+) \| ts=(?P<ts>\d+) \| "
    r"total_deposited=(?P<deposited>[\d.]+) \| total_withdrawn=(?P<withdrawn>[\d.]+)"
)

LEND_CALC_LINE = re.compile(
    r"\[DEPOSITS\] LEND_CALC tx_id=(?P<tx_id>\S+) \| pool=(?P<pool>\S+) \| "
    r"addr=(?P<addr>\S+) \| block=(?P<block>\d+) \| "
    r"amount=(?P<amount>[\d.]+) \+ fee=(?P<fee>[\d.]+) = delta=(?P<delta>[\d.]+) \| "
    r"old_deposited=(?P<old_dep>[\d.]+) -> new_deposited=(?P<new_dep>[\d.]+)"
)

WITHDRAW_CALC_LINE = re.compile(
    r"\[DEPOSITS\] WITHDRAW_CALC tx_id=(?P<tx_id>\S+) \| pool=(?P<pool>\S+) \| "
    r"addr=(?P<addr>\S+) \| block=(?P<block>\d+) \| "
    r"amount=(?P<amount>[\d.]+) - fee=(?P<fee>[\d.]+) = delta=(?P<delta>[\d.]+) \| "
    r"old_withdrawn=(?P<old_wth>[\d.]+) -> new_withdrawn=(?P<new_wth>[\d.]+)"
)


class DepositUpsert:
    def __init__(self, tx_id, pool, addr, block, ts, deposited, withdrawn):
        self.tx_id = tx_id
        self.pool = pool
        self.addr = addr
        self.block = int(block)
        self.ts = int(ts)
        self.deposited = float(deposited)
        self.withdrawn = float(withdrawn)


class CalcEntry:
    def __init__(self, tx_id, pool, addr, block, amount, fee, delta, old_val, new_val, calc_type):
        self.tx_id = tx_id
        self.pool = pool
        self.addr = addr
        self.block = int(block)
        self.amount = float(amount)
        self.fee = float(fee)
        self.delta = float(delta)
        self.old_val = float(old_val)
        self.new_val = float(new_val)
        self.calc_type = calc_type  # 'lend' or 'withdraw'


def parse_deposits_log(path, address_filter=None, pool_filter=None):
    upserts = []
    calcs = []
    with open(path) as f:
        for line in f:
            m = UPSERT_LINE.search(line)
            if m:
                d = m.groupdict()
                if address_filter and d["addr"] != address_filter:
                    continue
                if pool_filter and d["pool"] != pool_filter:
                    continue
                upserts.append(DepositUpsert(**d))
                continue

            m = LEND_CALC_LINE.search(line)
            if m:
                d = m.groupdict()
                if address_filter and d["addr"] != address_filter:
                    continue
                if pool_filter and d["pool"] != pool_filter:
                    continue
                calcs.append(CalcEntry(
                    tx_id=d["tx_id"], pool=d["pool"], addr=d["addr"],
                    block=d["block"], amount=d["amount"], fee=d["fee"],
                    delta=d["delta"], old_val=d["old_dep"], new_val=d["new_dep"],
                    calc_type="lend"
                ))
                continue

            m = WITHDRAW_CALC_LINE.search(line)
            if m:
                d = m.groupdict()
                if address_filter and d["addr"] != address_filter:
                    continue
                if pool_filter and d["pool"] != pool_filter:
                    continue
                calcs.append(CalcEntry(
                    tx_id=d["tx_id"], pool=d["pool"], addr=d["addr"],
                    block=d["block"], amount=d["amount"], fee=d["fee"],
                    delta=d["delta"], old_val=d["old_wth"], new_val=d["new_wth"],
                    calc_type="withdraw"
                ))

    return upserts, calcs


# ── Database queries ────────────────────────────────────────────────────────

def get_db_deposits(db: DatabaseManager, address: str, pool_nft: str) -> dict:
    """
    Query user_deposits_historical for an address+pool.
    Returns {tx_id: {total_deposited, total_withdrawn, block_height, timestamp}}.
    """
    query = """
        SELECT udh.transaction_id, udh.block_height, udh.timestamp,
               udh.total_deposited, udh.total_withdrawn
        FROM user_deposits_historical udh
        JOIN addresses a ON udh.address_id = a.id
        WHERE a.address = %s AND udh.pool_nft = %s
        ORDER BY udh.block_height ASC, udh.id ASC
    """
    rows = db.execute_query(query, (address, pool_nft))
    result = {}
    for r in rows:
        result[r["transaction_id"]] = {
            "total_deposited": float(r["total_deposited"]),
            "total_withdrawn": float(r["total_withdrawn"]),
            "block_height": r["block_height"],
            "timestamp": r["timestamp"],
        }
    return result


def get_db_transactions(db: DatabaseManager, address: str, pool_nft: str) -> list:
    """
    Query the transactions table for an address+pool, in chronological order.
    This is the source data that sync_user_deposits_historical reads from.
    """
    query = """
        SELECT t.id, t.type, t.amount, t.fee_paid, t.block_height, t.timestamp
        FROM transactions t
        JOIN addresses a ON t.address_id = a.id
        WHERE a.address = %s AND t.pool_nft = %s
        ORDER BY t.block_height ASC, t.id ASC
    """
    return db.execute_query(query, (address, pool_nft))


# ── Verification ────────────────────────────────────────────────────────────

def verify_deposits(classified_txs, deposit_upserts, deposit_calcs,
                    db_deposits, db_transactions, address, pool):
    """
    Replay deposit accumulation from classified transactions and compare against:
      1) DEPOSITS log (calcs + upserts)
      2) DB entries (user_deposits_historical)
      3) DB source (transactions table)
    """
    issues = []
    total_deposited = 0.0
    total_withdrawn = 0.0

    # Build lookups from logs
    upsert_map = {}  # tx_id -> DepositUpsert
    for u in deposit_upserts:
        if u.addr == address and u.pool == pool:
            upsert_map[u.tx_id] = u

    calc_map = {}  # tx_id -> CalcEntry
    for c in deposit_calcs:
        if c.addr == address and c.pool == pool:
            calc_map[c.tx_id] = c

    # Build DB transaction lookup
    db_tx_map = {}
    if db_transactions:
        for t in db_transactions:
            db_tx_map[t["id"]] = t

    # Table header
    print(f"\n{'='*140}")
    print(f"  DEPOSIT TRACKING REPLAY for {address}")
    print(f"{'='*140}")
    print(f"{'Block':>10} | {'TX (first 16)':16} | {'Type':>12} | {'Amount':>14} | "
          f"{'Fee':>10} | {'Delta':>14} | {'Tot Deposited':>16} | {'Tot Withdrawn':>16} | {'Checks'}")
    print(f"{'-'*10}-+-{'-'*16}-+-{'-'*12}-+-{'-'*14}-+-{'-'*10}-+-{'-'*14}-+-{'-'*16}-+-{'-'*16}-+-{'-'*12}")

    # Replay from classified transactions (this is what the code actually uses)
    for tx in classified_txs:
        if tx.addr != address or tx.pool != pool:
            continue

        # Only lend and withdraw affect deposit totals
        delta = 0.0
        affected = False
        if tx.tx_type == "lend":
            delta = tx.amount + tx.fee
            total_deposited += delta
            affected = True
        elif tx.tx_type == "withdraw":
            delta = tx.amount - tx.fee
            total_withdrawn += delta
            affected = True

        checks = ""

        if affected:
            # The tx_id stored in deposits uses the FINAL tx id
            # (for repayments the final_tx differs, but lend/withdraw final_tx == tx_id)
            dep_tx_id = tx.final_tx

            # Check 1: Verify delta math in log
            calc = calc_map.get(dep_tx_id)
            if calc:
                expected_delta = calc.amount + calc.fee if calc.calc_type == "lend" else calc.amount - calc.fee
                if abs(expected_delta - calc.delta) > 1e-6:
                    checks += " LOG_MATH_ERR"
                    issues.append({
                        "type": "LOG_DELTA_MATH",
                        "tx": dep_tx_id, "block": tx.block,
                        "detail": f"Log calc: {calc.amount}{'+'if calc.calc_type=='lend'else'-'}{calc.fee}={calc.delta}, "
                                  f"expected {expected_delta:.10f}"
                    })
            else:
                # No calc log for this tx — fine, calcs are only logged for debug addresses
                pass

            # Check 2: Verify cumulative totals in upsert log
            upsert = upsert_map.get(dep_tx_id)
            if upsert:
                if abs(upsert.deposited - total_deposited) > 1e-6:
                    checks += " DEP_DRIFT"
                    issues.append({
                        "type": "UPSERT_DEPOSITED_MISMATCH",
                        "tx": dep_tx_id, "block": tx.block,
                        "detail": f"Replay total_deposited={total_deposited:.10f}, "
                                  f"log upsert={upsert.deposited:.10f}, "
                                  f"diff={abs(total_deposited - upsert.deposited):.10f}"
                    })
                if abs(upsert.withdrawn - total_withdrawn) > 1e-6:
                    checks += " WTH_DRIFT"
                    issues.append({
                        "type": "UPSERT_WITHDRAWN_MISMATCH",
                        "tx": dep_tx_id, "block": tx.block,
                        "detail": f"Replay total_withdrawn={total_withdrawn:.10f}, "
                                  f"log upsert={upsert.withdrawn:.10f}, "
                                  f"diff={abs(total_withdrawn - upsert.withdrawn):.10f}"
                    })

            # Check 3: Verify against database
            db_entry = db_deposits.get(dep_tx_id)
            if db_entry:
                if abs(db_entry["total_deposited"] - total_deposited) > 1e-6:
                    checks += " DB_DEP"
                    issues.append({
                        "type": "DB_DEPOSITED_MISMATCH",
                        "tx": dep_tx_id, "block": tx.block,
                        "detail": f"Replay={total_deposited:.10f}, DB={db_entry['total_deposited']:.10f}"
                    })
                if abs(db_entry["total_withdrawn"] - total_withdrawn) > 1e-6:
                    checks += " DB_WTH"
                    issues.append({
                        "type": "DB_WITHDRAWN_MISMATCH",
                        "tx": dep_tx_id, "block": tx.block,
                        "detail": f"Replay={total_withdrawn:.10f}, DB={db_entry['total_withdrawn']:.10f}"
                    })
            elif db_deposits:
                checks += " NO_DB"
                issues.append({
                    "type": "MISSING_DB_DEPOSIT_ENTRY",
                    "tx": dep_tx_id, "block": tx.block,
                    "detail": f"No DB entry for this {tx.tx_type} tx"
                })

            # Check 4: Verify the source transaction exists in DB with correct values
            db_tx = db_tx_map.get(dep_tx_id)
            if db_tx:
                db_amount = float(db_tx["amount"])
                db_fee = float(db_tx["fee_paid"]) if db_tx["fee_paid"] is not None else 0.0
                if abs(db_amount - tx.amount) > 1e-6:
                    checks += " TX_AMT"
                    issues.append({
                        "type": "TX_AMOUNT_MISMATCH",
                        "tx": dep_tx_id, "block": tx.block,
                        "detail": f"Log amount={tx.amount}, DB tx amount={db_amount}"
                    })
                if abs(db_fee - tx.fee) > 1e-6:
                    checks += " TX_FEE"
                    issues.append({
                        "type": "TX_FEE_MISMATCH",
                        "tx": dep_tx_id, "block": tx.block,
                        "detail": f"Log fee={tx.fee}, DB tx fee={db_fee}"
                    })
            elif db_tx_map:
                checks += " NO_TX"
                issues.append({
                    "type": "MISSING_DB_TRANSACTION",
                    "tx": dep_tx_id, "block": tx.block,
                    "detail": f"Transaction not found in DB transactions table"
                })

            if not checks:
                checks = " OK"

            print(f"{tx.block:>10} | {dep_tx_id[:16]:16} | {tx.tx_type:>12} | "
                  f"{tx.amount:>14.6f} | {tx.fee:>10.6f} | {delta:>14.6f} | "
                  f"{total_deposited:>16.10f} | {total_withdrawn:>16.10f} |{checks}")
        else:
            # Non-deposit tx (borrow, repayment, liquidation, etc.)
            print(f"{tx.block:>10} | {tx.final_tx[:16]:16} | {tx.tx_type:>12} | "
                  f"{tx.amount:>14.6f} | {tx.fee:>10.6f} | {'--':>14} | "
                  f"{'':>16} | {'':>16} | (no effect)")

    return issues, total_deposited, total_withdrawn


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Verify deposit/withdrawal tracking")
    parser.add_argument("--address", "-a", help="Filter to a specific address")
    parser.add_argument("--pool", "-p", help="Filter to a specific pool NFT")
    parser.add_argument("--no-db", action="store_true", help="Skip database verification")
    parser.add_argument("--no-split", action="store_true", help="Reuse already-split log files")
    parser.add_argument("--log-file", default="sync_services.log",
                        help="Path to sync_services.log")
    args = parser.parse_args()

    # Split logs if needed
    log_dir = os.path.join(os.path.dirname(os.path.abspath(args.log_file)), "logs")
    if not args.no_split:
        print("Splitting log files...")
        # Import splitter from verify_lend_positions
        from verify_lend_positions import split_log_file
        split_log_file(args.log_file, log_dir)

    tx_log = os.path.join(log_dir, "stage1_tx_service.log")
    dep_log = os.path.join(log_dir, "stage3_deposits.log")

    for p in [tx_log, dep_log]:
        if not os.path.exists(p):
            print(f"ERROR: {p} not found. Run without --no-split first.")
            sys.exit(1)

    # Parse logs
    print(f"\nParsing {tx_log}...")
    classified_txs = parse_tx_service_log(tx_log, args.address, args.pool)
    print(f"  {len(classified_txs)} classified transactions")

    print(f"Parsing {dep_log}...")
    deposit_upserts, deposit_calcs = parse_deposits_log(dep_log, args.address, args.pool)
    print(f"  {len(deposit_upserts)} upsert entries, {len(deposit_calcs)} calc entries")

    # Discover address+pool combinations
    addr_pools = set()
    for tx in classified_txs:
        addr_pools.add((tx.addr, tx.pool))

    if not addr_pools:
        print("No transactions found for the given filters.")
        sys.exit(0)

    print(f"  Found {len(addr_pools)} address+pool combinations")

    # Connect to DB
    db = None
    if not args.no_db:
        print("\nConnecting to database...")
        try:
            db = DatabaseManager()
            print("  Connected")
        except Exception as e:
            print(f"  WARNING: Could not connect: {e}")

    # Verify each combination
    total_issues = 0
    for addr, pool in sorted(addr_pools):
        print(f"\n{'#'*140}")
        print(f"  Address: {addr}")
        print(f"  Pool:    {pool[:16]}...")
        print(f"{'#'*140}")

        # Get DB data
        db_deposits = {}
        db_transactions = []
        if db:
            db_deposits = get_db_deposits(db, addr, pool)
            db_transactions = get_db_transactions(db, addr, pool)
            print(f"  DB deposit entries: {len(db_deposits)}")
            print(f"  DB transactions: {len(db_transactions)}")

        issues, final_dep, final_wth = verify_deposits(
            classified_txs, deposit_upserts, deposit_calcs,
            db_deposits, db_transactions, addr, pool
        )

        print(f"\n  Final totals (replay): deposited={final_dep:.10f}, withdrawn={final_wth:.10f}")

        if db_deposits:
            # Show final DB values
            last_db = max(db_deposits.values(), key=lambda x: x["block_height"])
            print(f"  Final totals (DB):     deposited={last_db['total_deposited']:.10f}, "
                  f"withdrawn={last_db['total_withdrawn']:.10f}")

        if issues:
            print(f"\n  *** {len(issues)} ISSUES FOUND ***")
            for i, issue in enumerate(issues, 1):
                print(f"    {i}. [{issue['type']}] block={issue['block']} "
                      f"tx={issue['tx'][:16]}... | {issue['detail']}")
            total_issues += len(issues)
        else:
            print(f"\n  ALL CHECKS PASSED")

    # Summary
    print(f"\n{'='*140}")
    print(f"  SUMMARY")
    print(f"{'='*140}")
    print(f"  Address+pool combinations: {len(addr_pools)}")
    print(f"  Total issues: {total_issues}")
    if total_issues == 0:
        print(f"  Result: ALL DEPOSIT TRACKING IS CORRECT")
    else:
        print(f"  Result: DISCREPANCIES DETECTED")
    print()


if __name__ == "__main__":
    main()
