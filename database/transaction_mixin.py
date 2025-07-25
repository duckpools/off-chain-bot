from typing import Optional


class TransactionMixin:
    def upsert_transaction(self,
                           transaction_id: str,
                           address: str,
                           pool_nft: str,
                           transaction_type: str,
                           amount: float,
                           block_height: Optional[int] = None,
                           timestamp: Optional[int] = None) -> Optional[str]:
        """
        Insert or update a transaction. If a row with the same transaction_id exists,
        updates its fields; otherwise creates it.
        """
        try:
            address_query = "SELECT id FROM addresses WHERE address = %s"
            address_result = self.execute_query(address_query, (address,))

            if address_result:
                address_id = address_result[0]['id']
            else:
                user_id = self.execute_insert("INSERT INTO users DEFAULT VALUES RETURNING id", return_id=True)
                if not user_id:
                    print("Failed to create user")
                    return None
                address_id = self.execute_insert(
                    "INSERT INTO addresses (address, user_id, is_primary) VALUES (%s,%s,%s) RETURNING id",
                    (address, user_id, True),
                    return_id=True
                )
                if not address_id:
                    print("Failed to create address")
                    return None

            # 2) Validate transaction type - updated to include all types
            valid_types = ('lend', 'withdraw', 'borrow', 'repayment', 'partial_repayment', 'liquidation')
            if transaction_type not in valid_types:
                print(f"Invalid transaction type {transaction_type}")
                return None

            # 3) Upsert in one statement:
            upsert_sql = """
            INSERT INTO transactions
              (id, address_id, pool_nft, type, amount, block_height, timestamp)
            VALUES
              (%s,     %s,         %s,       %s,    %s,     %s,           %s)
            ON CONFLICT (id) DO UPDATE
              SET address_id  = EXCLUDED.address_id,
                  pool_nft     = EXCLUDED.pool_nft,
                  type         = EXCLUDED.type,
                  amount       = EXCLUDED.amount,
                  block_height = EXCLUDED.block_height,
                  timestamp    = EXCLUDED.timestamp
            RETURNING id
            """
            params = (transaction_id, address_id, pool_nft, transaction_type, amount, block_height, timestamp)
            returned = self.execute_insert(upsert_sql, params, return_id=True)

            return returned  # will be the transaction_id if successful, else None

        except Exception as e:
            print(f"Error upserting transaction: {e}")
            return None
