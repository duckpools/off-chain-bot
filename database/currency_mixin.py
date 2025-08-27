from typing import Optional


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