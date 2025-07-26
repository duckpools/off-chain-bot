from typing import Optional


class TransactionMixin:
    def upsert_transaction(self,
                           transaction_id: str,
                           address: str,
                           pool_nft: str,
                           transaction_type: str,
                           amount: float,
                           fee_paid: Optional[int] = None,
                           block_height: Optional[int] = None,
                           timestamp: Optional[int] = None) -> Optional[str]:
        """
        Insert or update a transaction. If a row with the same transaction_id exists,
        updates its fields; otherwise creates it.
        """
        try:
            # Validate transaction type
            valid_types = ('lend', 'withdraw', 'borrow', 'repayment', 'partial_repayment', 'liquidation')
            if transaction_type not in valid_types:
                print(f"Invalid transaction type {transaction_type}")
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
                        # Create user first
                        cur.execute("INSERT INTO users DEFAULT VALUES RETURNING id")
                        user_result = cur.fetchone()
                        if not user_result:
                            print("Failed to create user")
                            return None
                        user_id = user_result[0]

                        # Create address
                        cur.execute(
                            "INSERT INTO addresses (address, user_id, is_primary) VALUES (%s, %s, %s) RETURNING id",
                            (address, user_id, True)
                        )
                        address_result = cur.fetchone()
                        if not address_result:
                            print("Failed to create address")
                            return None
                        address_id = address_result[0]

                    # Upsert transaction
                    upsert_sql = """
                    INSERT INTO transactions
                      (id, address_id, pool_nft, type, amount, fee_paid, block_height, timestamp)
                    VALUES
                      (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                      SET address_id  = EXCLUDED.address_id,
                          pool_nft     = EXCLUDED.pool_nft,
                          type         = EXCLUDED.type,
                          amount       = EXCLUDED.amount,
                          fee_paid     = EXCLUDED.fee_paid,
                          block_height = EXCLUDED.block_height,
                          timestamp    = EXCLUDED.timestamp
                    RETURNING id
                    """

                    params = (
                    transaction_id, address_id, pool_nft, transaction_type, amount, fee_paid, block_height, timestamp)
                    cur.execute(upsert_sql, params)
                    result = cur.fetchone()

                    conn.commit()
                    return result[0] if result else None

        except Exception as e:
            print(f"Error upserting transaction: {e}")
            return None