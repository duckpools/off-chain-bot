"""
Checksum services for verifying database integrity before/after syncs.

Usage:
    # Before sync
    python -m database_services.checksum_services create checksums_before.json

    # After sync
    python -m database_services.checksum_services create checksums_after.json

    # Compare
    python -m database_services.checksum_services compare checksums_before.json checksums_after.json
"""

import json
from datetime import datetime
from typing import Dict, Any, List
from database.db_manager import DatabaseManager


class ChecksumManager:
    """Creates and verifies checksums for database integrity checking"""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def create_checksums(
        self,
        sync_block: int = None,
        block_interval: int = 10000
    ) -> Dict[str, Any]:
        """
        Create checksums for all tables using 10k block intervals.

        Args:
            sync_block: Block height to checksum up to. If None, uses current highest.
            block_interval: Size of block ranges to checksum (default: 10000)

        Returns:
            Dictionary containing all checksums and metadata
        """
        if sync_block is None:
            sync_block = self.db.get_highest_sync_block()

        print(f"Creating checksums up to block {sync_block}...")
        print(f"Using {block_interval} block intervals\n")

        checksum_data = {
            'metadata': {
                'created_at': datetime.now().isoformat(),
                'sync_block': sync_block,
                'block_interval': block_interval,
                'database_info': self._get_database_info()
            },
            'checksums': {}
        }

        # Tables to checksum with their configurations
        tables = [
            ('transactions', True),  # (table_name, has_block_height)
            ('user_lend_positions_historical', True),
            ('user_deposits_historical', True),
            ('pool_data_historical', True),
            ('user_portfolio_snapshots', True),
        ]

        # Create block-range checksums for historical tables
        for table, has_blocks in tables:
            print(f"Processing {table}...")
            table_checksums = self._create_table_checksums(
                table, 0, sync_block, block_interval
            )
            checksum_data['checksums'].update(table_checksums)

        # Create single checksums for reference tables
        print(f"\nProcessing reference tables...")
        checksum_data['checksums']['addresses_all'] = self._checksum_addresses(sync_block)
        checksum_data['checksums']['pools_all'] = self._checksum_pools(sync_block)
        checksum_data['checksums']['currency_rates_all'] = self._checksum_currency_rates(sync_block)

        # Note: user_pool_debts is excluded because it gets completely replaced each sync

        total_checksums = len(checksum_data['checksums'])
        print(f"\n✓ Created {total_checksums} checksums")

        return checksum_data

    def _create_table_checksums(
        self,
        table: str,
        start_block: int,
        end_block: int,
        interval: int
    ) -> Dict[str, str]:
        """Create checksums for a table in block intervals"""
        checksums = {}
        current = start_block

        while current <= end_block:
            range_end = min(current + interval - 1, end_block)

            # Get checksum for this range
            checksum = self._checksum_table_range(table, current, range_end)

            # Only store if there's data in this range
            if checksum != "empty":
                key = f"{table}_{current}_{range_end}"
                checksums[key] = checksum
                print(f"  Blocks {current:>6} - {range_end:>6}: {checksum[:16]}...")

            current += interval

        return checksums

    def _checksum_table_range(self, table: str, start_block: int, end_block: int) -> str:
        """
        Create MD5 checksum for table data in block range.
        Only includes immutable fields (excludes created_at, updated_at, sync_block).
        """

        if table == "transactions":
            query = """
                SELECT md5(array_agg(
                    id || address_id::text || pool_nft || type::text ||
                    amount::text || COALESCE(fee_paid::text, 'null') ||
                    block_height::text || timestamp::text
                    ORDER BY block_height, id
                )::text) as checksum
                FROM transactions
                WHERE block_height BETWEEN %s AND %s
            """

        elif table == "user_lend_positions_historical":
            query = """
                SELECT md5(array_agg(
                    address_id::text || pool_nft || block_height::text ||
                    timestamp::text || position_tokens::text || position_value::text
                    ORDER BY block_height, address_id, pool_nft, timestamp
                )::text) as checksum
                FROM user_lend_positions_historical
                WHERE block_height BETWEEN %s AND %s
            """

        elif table == "user_deposits_historical":
            query = """
                SELECT md5(array_agg(
                    address_id::text || pool_nft ||
                    COALESCE(transaction_id, 'null') ||
                    block_height::text || timestamp::text ||
                    total_deposited::text || total_withdrawn::text
                    ORDER BY block_height, address_id, pool_nft
                )::text) as checksum
                FROM user_deposits_historical
                WHERE block_height BETWEEN %s AND %s
            """

        elif table == "pool_data_historical":
            query = """
                SELECT md5(array_agg(
                    pool_nft || block_height::text || transaction_id ||
                    lend_apy::text || borrow_apy::text || pool_utilization::text ||
                    total_lent::text || total_borrowed::text || box_timestamp::text ||
                    pool_box_id || lend_token_value::text
                    ORDER BY block_height, pool_nft, transaction_id
                )::text) as checksum
                FROM pool_data_historical
                WHERE block_height BETWEEN %s AND %s
            """

        elif table == "user_portfolio_snapshots":
            query = """
                SELECT md5(array_agg(
                    address_id::text || pool_nft || block_height::text ||
                    timestamp::text || position_value::text || total_profit::text
                    ORDER BY block_height, address_id, pool_nft, timestamp
                )::text) as checksum
                FROM user_portfolio_snapshots
                WHERE block_height BETWEEN %s AND %s
            """

        else:
            raise ValueError(f"Checksum not implemented for table: {table}")

        result = self.db.execute_query(query, (start_block, end_block))
        return result[0]['checksum'] if result and result[0]['checksum'] else "empty"

    def _checksum_addresses(self, sync_block: int) -> str:
        """Checksum all addresses (immutable data only)"""
        query = """
            SELECT md5(array_agg(
                id::text || address
                ORDER BY id
            )::text) as checksum
            FROM addresses
            WHERE sync_block <= %s
        """
        result = self.db.execute_query(query, (sync_block,))
        return result[0]['checksum'] if result and result[0]['checksum'] else "empty"

    def _checksum_pools(self, sync_block: int) -> str:
        """Checksum pool reference data (immutable fields only)"""
        query = """
            SELECT md5(array_agg(
                nft || pooled_asset
                ORDER BY nft
            )::text) as checksum
            FROM pools
            WHERE sync_block <= %s
        """
        result = self.db.execute_query(query, (sync_block,))
        return result[0]['checksum'] if result and result[0]['checksum'] else "empty"

    def _checksum_currency_rates(self, sync_block: int) -> str:
        """Checksum currency rates"""
        query = """
            SELECT md5(array_agg(
                pooled_asset || usd_rate::text || timestamp::text
                ORDER BY pooled_asset, timestamp
            )::text) as checksum
            FROM currency_rates
            WHERE sync_block <= %s
        """
        result = self.db.execute_query(query, (sync_block,))
        return result[0]['checksum'] if result and result[0]['checksum'] else "empty"

    def _get_database_info(self) -> Dict[str, Any]:
        """Get current database statistics"""
        info = {}

        tables = [
            'addresses', 'pools', 'currency_rates', 'pool_data_historical',
            'transactions', 'user_lend_positions_historical',
            'user_deposits_historical', 'user_portfolio_snapshots',
            'user_pool_debts'
        ]

        for table in tables:
            query = f"SELECT COUNT(*) as count FROM {table}"
            result = self.db.execute_query(query)
            info[f"{table}_count"] = result[0]['count'] if result else 0

        # Sync block ranges
        sync_info = self.db.get_sync_block_summary()
        info['sync_block_ranges'] = sync_info

        return info

    def save_checksums(self, checksums: Dict[str, Any], filepath: str):
        """Save checksums to JSON file"""
        with open(filepath, 'w') as f:
            json.dump(checksums, f, indent=2)
        print(f"\n✓ Checksums saved to: {filepath}")

    def load_checksums(self, filepath: str) -> Dict[str, Any]:
        """Load checksums from JSON file"""
        with open(filepath, 'r') as f:
            return json.load(f)

    def compare_checksum_files(
        self,
        before_file: str,
        after_file: str,
        output_file: str = None
    ) -> Dict[str, Any]:
        """
        Compare two checksum files and generate a detailed report.

        Args:
            before_file: Path to "before sync" checksum file
            after_file: Path to "after sync" checksum file
            output_file: Optional path to save comparison report

        Returns:
            Dictionary containing comparison results
        """
        print("Loading checksum files...")
        before = self.load_checksums(before_file)
        after = self.load_checksums(after_file)

        print(f"\nBefore sync: {before['metadata']['created_at']}")
        print(f"  Sync block: {before['metadata']['sync_block']}")
        print(f"  Total checksums: {len(before['checksums'])}")

        print(f"\nAfter sync: {after['metadata']['created_at']}")
        print(f"  Sync block: {after['metadata']['sync_block']}")
        print(f"  Total checksums: {len(after['checksums'])}")

        # Compare checksums
        print("\n" + "="*70)
        print("CHECKSUM COMPARISON")
        print("="*70 + "\n")

        comparison = {
            'before_file': before_file,
            'after_file': after_file,
            'before_sync_block': before['metadata']['sync_block'],
            'after_sync_block': after['metadata']['sync_block'],
            'compared_at': datetime.now().isoformat(),
            'results': {
                'matching': [],
                'mismatched': [],
                'missing_in_after': [],
                'new_in_after': []
            },
            'summary': {}
        }

        before_checksums = before['checksums']
        after_checksums = after['checksums']

        # Compare each checksum from before
        for key, before_sum in before_checksums.items():
            if key not in after_checksums:
                comparison['results']['missing_in_after'].append({
                    'key': key,
                    'checksum': before_sum
                })
            elif after_checksums[key] == before_sum:
                comparison['results']['matching'].append(key)
            else:
                comparison['results']['mismatched'].append({
                    'key': key,
                    'before': before_sum,
                    'after': after_checksums[key]
                })

        # Find new checksums in after
        for key in after_checksums:
            if key not in before_checksums:
                comparison['results']['new_in_after'].append({
                    'key': key,
                    'checksum': after_checksums[key]
                })

        # Generate summary
        comparison['summary'] = {
            'total_compared': len(before_checksums),
            'matching': len(comparison['results']['matching']),
            'mismatched': len(comparison['results']['mismatched']),
            'missing_in_after': len(comparison['results']['missing_in_after']),
            'new_in_after': len(comparison['results']['new_in_after']),
            'status': 'PASS' if len(comparison['results']['mismatched']) == 0 else 'FAIL'
        }

        # Print results
        self._print_comparison_results(comparison)

        # Save report if requested
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(comparison, f, indent=2)
            print(f"\n✓ Detailed report saved to: {output_file}")

        return comparison

    def _print_comparison_results(self, comparison: Dict[str, Any]):
        """Print comparison results in a readable format"""
        summary = comparison['summary']
        results = comparison['results']

        print(f"Matching checksums:     {summary['matching']:>5} ✓")
        print(f"Mismatched checksums:   {summary['mismatched']:>5} {'✗' if summary['mismatched'] > 0 else '✓'}")
        print(f"Missing in after:       {summary['missing_in_after']:>5} {'⚠' if summary['missing_in_after'] > 0 else '✓'}")
        print(f"New in after:           {summary['new_in_after']:>5}")

        print("\n" + "="*70)

        if summary['status'] == 'PASS':
            print("✓ VERIFICATION PASSED")
            print("  All existing data checksums match!")
            print(f"  Data integrity maintained for blocks 0-{comparison['before_sync_block']}")

            if summary['new_in_after'] > 0:
                print(f"\n  New data added (expected behavior):")
                for item in results['new_in_after'][:5]:  # Show first 5
                    print(f"    + {item['key']}")
                if summary['new_in_after'] > 5:
                    print(f"    ... and {summary['new_in_after'] - 5} more")

        else:
            print("✗ VERIFICATION FAILED")
            print("  Data integrity issues detected!\n")

            if results['mismatched']:
                print(f"  Mismatched checksums ({len(results['mismatched'])}):")
                for item in results['mismatched']:
                    print(f"    ✗ {item['key']}")
                    print(f"      Before: {item['before'][:16]}...")
                    print(f"      After:  {item['after'][:16]}...")

            if results['missing_in_after']:
                print(f"\n  Missing checksums ({len(results['missing_in_after'])}):")
                for item in results['missing_in_after'][:10]:
                    print(f"    ⚠ {item['key']}")

        print("="*70)


def main():
    """CLI interface for checksum operations"""
    import sys

    if len(sys.argv) < 2:
        print(__doc__)
        print("\nCommands:")
        print("  create <output_file> [sync_block]")
        print("    Create checksums and save to file")
        print("    If sync_block not provided, uses current highest")
        print()
        print("  compare <before_file> <after_file> [report_file]")
        print("    Compare two checksum files")
        print("    Optional: save detailed report to report_file")
        print()
        print("Examples:")
        print("  python -m database_services.checksum_services create checksums_before.json")
        print("  python -m database_services.checksum_services create checksums_after.json 1234567")
        print("  python -m database_services.checksum_services compare checksums_before.json checksums_after.json")
        print("  python -m database_services.checksum_services compare checksums_before.json checksums_after.json report.json")
        return

    command = sys.argv[1]

    db = DatabaseManager()
    manager = ChecksumManager(db)

    if command == "create":
        if len(sys.argv) < 3:
            print("Error: output file required")
            print("Usage: create <output_file> [sync_block]")
            return

        output_file = sys.argv[2]
        sync_block = int(sys.argv[3]) if len(sys.argv) > 3 else None

        checksums = manager.create_checksums(sync_block=sync_block)
        manager.save_checksums(checksums, output_file)

    elif command == "compare":
        if len(sys.argv) < 4:
            print("Error: two checksum files required")
            print("Usage: compare <before_file> <after_file> [report_file]")
            return

        before_file = sys.argv[2]
        after_file = sys.argv[3]
        report_file = sys.argv[4] if len(sys.argv) > 4 else None

        manager.compare_checksum_files(before_file, after_file, report_file)

    else:
        print(f"Unknown command: {command}")
        print("Use 'create' or 'compare'")


if __name__ == "__main__":
    main()
