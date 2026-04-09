from typing import Optional, List, Dict, Any

from logger import set_logger

logger = set_logger(__name__)


class TransactionMixin:
    def upsert_transaction(self,
                           transaction_id: str,
                           address: str,
                           pool_nft: str,
                           transaction_type: str,
                           amount: float,
                           fee_paid: Optional[int] = None,
                           borrow_apy: Optional[float] = None,
                           interest_paid: Optional[float] = None,
                           block_height: Optional[int] = None,
                           timestamp: Optional[int] = None,
                           sync_block: Optional[int] = None) -> Optional[str]:
        """
        Insert or update a transaction. If a row with the same transaction_id exists,
        updates its fields; otherwise creates it.
        """
        try:
            # Validate transaction type
            valid_types = ('lend', 'withdraw', 'borrow', 'repayment', 'partial_repayment', 'liquidation')
            if transaction_type not in valid_types:
                print(f"Invalid transaction type {transaction_type}")
                logger.error("Invalid transaction type %s", transaction_type)
                return None

            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # Get or create address_id in a single transaction
                    address_query = "SELECT id FROM addresses WHERE address = %s"
                    cur.execute(address_query, (address,))
                    address_result = cur.fetchone()

                    if address_result:
                        address_id = address_result[0]
                    else:
                        # Create address
                        cur.execute(
                            "INSERT INTO addresses (address, sync_block) VALUES (%s, %s) RETURNING id",
                            (address, sync_block)
                        )
                        address_result = cur.fetchone()
                        if not address_result:
                            print("Failed to create address")
                            logger.error("Failed to create address %s for transaction", address)
                            return None
                        address_id = address_result[0]

                    # Upsert transaction
                    upsert_sql = """
                    INSERT INTO transactions
                      (id, address_id, pool_nft, type, amount, fee_paid, borrow_apy, interest_paid, block_height, timestamp, sync_block)
                    VALUES
                      (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                      SET address_id  = EXCLUDED.address_id,
                          pool_nft     = EXCLUDED.pool_nft,
                          type         = EXCLUDED.type,
                          amount       = EXCLUDED.amount,
                          fee_paid     = EXCLUDED.fee_paid,
                          borrow_apy   = EXCLUDED.borrow_apy,
                          interest_paid = EXCLUDED.interest_paid,
                          block_height = EXCLUDED.block_height,
                          timestamp    = EXCLUDED.timestamp,
                          sync_block   = EXCLUDED.sync_block
                    RETURNING id
                    """

                    params = (
                        transaction_id, address_id, pool_nft, transaction_type, amount, fee_paid, borrow_apy,
                        interest_paid, block_height, timestamp, sync_block)
                    cur.execute(upsert_sql, params)
                    result = cur.fetchone()

                    conn.commit()
                    return result[0] if result else None

        except Exception as e:
            print(f"Error upserting transaction: {e}")
            logger.error("Error upserting transaction: %s", e, exc_info=True)
            return None

    def batch_upsert_transactions(self, transactions: List[Dict[str, Any]]) -> int:
        """
        Batch upsert transactions into the database for improved performance.

        :param transactions: List of transaction dictionaries with keys:
                            - transaction_id: str
                            - address: str
                            - pool_nft: str
                            - transaction_type: str
                            - amount: float
                            - fee_paid: Optional[int]
                            - borrow_apy: Optional[float]
                            - interest_paid: Optional[float]
                            - block_height: Optional[int]
                            - timestamp: Optional[int]
                            - sync_block: Optional[int]
        :return: Number of successfully processed transactions
        """
        if not transactions:
            return 0

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # First, collect all unique addresses and ensure they exist
                    unique_addresses = set(tx['address'] for tx in transactions)
                    address_to_id = {}

                    # Get existing addresses
                    if unique_addresses:
                        placeholders = ','.join(['%s'] * len(unique_addresses))
                        cur.execute(f"SELECT address, id FROM addresses WHERE address IN ({placeholders})",
                                    list(unique_addresses))
                        existing_addresses = cur.fetchall()
                        address_to_id = {addr: addr_id for addr, addr_id in existing_addresses}

                    # Create missing addresses
                    missing_addresses = unique_addresses - set(address_to_id.keys())
                    for address in missing_addresses:
                        try:
                            # Get sync_block from first transaction for this address
                            sync_block = None
                            for tx in transactions:
                                if tx['address'] == address:
                                    sync_block = tx.get('sync_block')
                                    break

                            # Create address
                            cur.execute(
                                "INSERT INTO addresses (address, sync_block) VALUES (%s, %s) RETURNING id",
                                (address, sync_block)
                            )
                            address_result = cur.fetchone()
                            if not address_result:
                                print(f"Failed to create address {address}")
                                logger.error("Failed to create address %s for batch transactions", address)
                                continue
                            address_to_id[address] = address_result[0]
                        except Exception as e:
                            print(f"Error creating address {address}: {e}")
                            logger.error("Error creating address %s: %s", address, e, exc_info=True)
                            continue

                    # Prepare transaction data for bulk insert
                    transaction_params = []
                    valid_types = ('lend', 'withdraw', 'borrow', 'repayment', 'partial_repayment', 'liquidation')

                    for tx_data in transactions:
                        # Validate transaction type
                        if tx_data['transaction_type'] not in valid_types:
                            print(f"Invalid transaction type {tx_data['transaction_type']}")
                            logger.error("Invalid transaction type %s in batch", tx_data['transaction_type'])
                            continue

                        # Get address_id
                        address_id = address_to_id.get(tx_data['address'])
                        if not address_id:
                            print(f"Could not find address_id for {tx_data['address']}")
                            logger.error("Could not find address_id for %s", tx_data['address'])
                            continue

                        transaction_params.append((
                            tx_data['transaction_id'],
                            address_id,
                            tx_data['pool_nft'],
                            tx_data['transaction_type'],
                            tx_data['amount'],
                            tx_data.get('fee_paid'),
                            tx_data.get('borrow_apy'),
                            tx_data.get('interest_paid'),
                            tx_data.get('block_height'),
                            tx_data.get('timestamp'),
                            tx_data.get('sync_block')
                        ))

                    # Bulk upsert transactions
                    if transaction_params:
                        upsert_sql = """
                        INSERT INTO transactions
                          (id, address_id, pool_nft, type, amount, fee_paid, borrow_apy, interest_paid, block_height, timestamp, sync_block)
                        VALUES
                          (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE
                          SET address_id  = EXCLUDED.address_id,
                              pool_nft     = EXCLUDED.pool_nft,
                              type         = EXCLUDED.type,
                              amount       = EXCLUDED.amount,
                              fee_paid     = EXCLUDED.fee_paid,
                              borrow_apy   = EXCLUDED.borrow_apy,
                              interest_paid = EXCLUDED.interest_paid,
                              block_height = EXCLUDED.block_height,
                              timestamp    = EXCLUDED.timestamp,
                              sync_block   = EXCLUDED.sync_block
                        """

                        cur.executemany(upsert_sql, transaction_params)
                        conn.commit()

                        return len(transaction_params)

                    return 0

        except Exception as e:
            print(f"Error processing transaction batch: {e}")
            logger.error("Error processing transaction batch: %s", e, exc_info=True)
            return 0