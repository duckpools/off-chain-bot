from typing import Optional, List, Dict, Any

from logger import set_logger

logger = set_logger(__name__)


class AnalyticsMixin:
    def get_next_snapshot(self, address: str, timestamp: int) -> Dict[str, Dict[str, Any]]:
        """
        Fetch the earliest snapshot strictly after a given timestamp for an address, by pool.

        Args:
            address: The blockchain address to query
            timestamp: Unix timestamp to search after

        Returns:
            Dictionary with pool_nft as keys containing snapshot data for each pool
        """
        try:
            query = """
                SELECT DISTINCT ON (ups.pool_nft)
                    a.address,
                    ups.pool_nft,
                    ups.position_value,
                    ups.total_profit,
                    ups.timestamp,
                    ups.block_height,
                    ups.sync_block
                FROM user_portfolio_snapshots ups
                JOIN addresses a ON ups.address_id = a.id
                WHERE a.address = %s
                  AND ups.timestamp > %s
                ORDER BY ups.pool_nft, ups.timestamp ASC, ups.block_height ASC;
            """

            result = self.execute_query(query, (address, timestamp))

            snapshots = {}
            if result:
                for row in result:
                    pool_nft = row['pool_nft']
                    snapshots[pool_nft] = {
                        'address': row['address'],
                        'pool_nft': row['pool_nft'],
                        'position_value': row['position_value'],
                        'total_profit': row['total_profit'],
                        'timestamp': row['timestamp'],
                        'block_height': row['block_height'],
                        'sync_block': row['sync_block']
                    }

            return snapshots

        except Exception as e:
            print(f"Error fetching next snapshot for address {address} after timestamp {timestamp}: {e}")
            logger.error("Error fetching next snapshot for address %s after timestamp %s: %s", address, timestamp, e, exc_info=True)
            return {}

    def get_latest_snapshot(self, address: str) -> Dict[str, Dict[str, Any]]:
        """
        Fetch the most recent snapshot for each pool for an address.

        Args:
            address: The blockchain address to query

        Returns:
            Dictionary with pool_nft as keys containing latest snapshot data for each pool
        """
        try:
            query = """
                SELECT DISTINCT ON (ups.pool_nft)
                    a.address,
                    ups.pool_nft,
                    ups.position_value,
                    ups.total_profit,
                    ups.timestamp,
                    ups.block_height,
                    ups.sync_block
                FROM user_portfolio_snapshots ups
                JOIN addresses a ON ups.address_id = a.id
                WHERE a.address = %s
                ORDER BY ups.pool_nft, ups.timestamp DESC, ups.block_height DESC;
            """

            result = self.execute_query(query, (address,))

            snapshots = {}
            if result:
                for row in result:
                    pool_nft = row['pool_nft']
                    snapshots[pool_nft] = {
                        'address': row['address'],
                        'pool_nft': row['pool_nft'],
                        'position_value': row['position_value'],
                        'total_profit': row['total_profit'],
                        'timestamp': row['timestamp'],
                        'block_height': row['block_height'],
                        'sync_block': row['sync_block']
                    }

            return snapshots

        except Exception as e:
            print(f"Error fetching latest snapshot for address {address}: {e}")
            logger.error("Error fetching latest snapshot for address %s: %s", address, e, exc_info=True)
            return {}

    def get_currency_rates(self) -> Dict[str, float]:
        """
        Get all currency rates.

        Returns:
            Dictionary with pooled_asset as keys and USD rates as values
        """
        try:
            query = "SELECT pooled_asset, usd_rate FROM currency_rates;"
            result = self.execute_query(query)

            rates = {}
            if result:
                for row in result:
                    rates[row['pooled_asset']] = float(row['usd_rate'])

            return rates

        except Exception as e:
            print(f"Error fetching currency rates: {e}")
            logger.error("Error fetching currency rates: %s", e, exc_info=True)
            return {}

    def get_pool_asset(self, pool_nft: str) -> Optional[str]:
        """
        Get the pooled asset for a given pool NFT.

        Args:
            pool_nft: The pool NFT identifier

        Returns:
            The pooled asset string, or None if not found
        """
        try:
            query = "SELECT pooled_asset FROM pools WHERE nft = %s;"
            result = self.execute_query(query, (pool_nft,))

            if result and len(result) > 0:
                return result[0]['pooled_asset']
            else:
                return None

        except Exception as e:
            print(f"Error fetching pool asset for {pool_nft}: {e}")
            logger.error("Error fetching pool asset for %s: %s", pool_nft, e, exc_info=True)
            return None

    def get_address_id(self, address: str) -> Optional[int]:
        """
        Get the address ID for a given address string.

        Args:
            address: The blockchain address

        Returns:
            The address ID, or None if not found
        """
        try:
            query = "SELECT id FROM addresses WHERE address = %s;"
            result = self.execute_query(query, (address,))

            if result and len(result) > 0:
                return result[0]['id']
            else:
                return None

        except Exception as e:
            print(f"Error fetching address ID for {address}: {e}")
            logger.error("Error fetching address ID for %s: %s", address, e, exc_info=True)
            return None

    def get_pool_lend_apy(self, pool_nft: str) -> float:
        """
        Get the current lend APY for a given pool NFT.

        Args:
            pool_nft: The pool NFT identifier

        Returns:
            The current lend APY as a float, or 0 if not found
        """
        try:
            query = "SELECT lend_apy FROM pools WHERE nft = %s;"
            result = self.execute_query(query, (pool_nft,))

            if result and len(result) > 0:
                return float(result[0]['lend_apy']) / 100
            else:
                return 0.0

        except Exception as e:
            print(f"Error fetching lend APY for pool {pool_nft}: {e}")
            logger.error("Error fetching lend APY for pool %s: %s", pool_nft, e, exc_info=True)
            return 0.0

    def get_all_addresses(self) -> List[str]:
        """
        Get all address strings from the database.

        Returns:
            List of all address strings in the database
        """
        try:
            query = "SELECT address FROM addresses ORDER BY address;"
            result = self.execute_query(query)

            addresses = []
            if result:
                for row in result:
                    addresses.append(row['address'])

            return addresses

        except Exception as e:
            print(f"Error fetching all addresses: {e}")
            logger.error("Error fetching all addresses: %s", e, exc_info=True)
            return []