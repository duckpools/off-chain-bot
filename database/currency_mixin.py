from typing import Optional, List


class CurrencyMixin:
    def upsert_currency_rate(self, pooled_asset: str, usd_rate: float = 0) -> Optional[str]:
        """Insert or update a currency rate in the database."""
        try:
            upsert_query = """
                INSERT INTO currency_rates (pooled_asset, usd_rate)
                VALUES (%s, %s)
                ON CONFLICT (pooled_asset)
                DO UPDATE SET
                    usd_rate = EXCLUDED.usd_rate,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING pooled_asset
            """

            params = (pooled_asset, usd_rate)
            result = self.execute_insert(upsert_query, params, return_id=True)

            return pooled_asset if result else None

        except Exception as e:
            print(f"Error upserting currency rate for {pooled_asset}: {e}")
            return None

    def batch_upsert_currency_rates(self, currency_data: List[tuple]) -> int:
        """
        Batch upsert currency rates.

        Args:
            currency_data: List of tuples (pooled_asset, usd_rate)

        Returns:
            Number of successfully processed rates
        """
        if not currency_data:
            return 0

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    from psycopg2.extras import execute_values

                    upsert_query = """
                        INSERT INTO currency_rates (pooled_asset, usd_rate)
                        VALUES %s
                        ON CONFLICT (pooled_asset)
                        DO UPDATE SET
                            usd_rate = EXCLUDED.usd_rate,
                            updated_at = CURRENT_TIMESTAMP
                    """

                    execute_values(
                        cur,
                        upsert_query,
                        currency_data,
                        template=None,
                        page_size=1000
                    )

                    conn.commit()
                    return len(currency_data)

        except Exception as e:
            print(f"Error batch upserting currency rates: {e}")
            return 0
