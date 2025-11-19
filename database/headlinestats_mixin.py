from typing import Optional


class HeadlinestatsMixin:
    def insert_headlinestats(self,
                            all_time_volume: float,
                            total_value_locked: float,
                            quacks_holders: int,
                            monthly_volume: float,
                            timestamp: int,
                            sync_block: Optional[int] = None) -> Optional[int]:
        """
        Insert a new headline stats record (historical tracking).

        Args:
            all_time_volume: Total volume across all time
            total_value_locked: Current total value locked
            quacks_holders: Number of QUACKS token holders
            monthly_volume: Volume for the current/previous month
            timestamp: Unix timestamp when this data was recorded
            sync_block: Block height when this data was synced

        Returns:
            id of the inserted record if successful, None if failed
        """
        try:
            insert_query = """
                INSERT INTO headlinestats (all_time_volume, total_value_locked, quacks_holders, monthly_volume, timestamp, sync_block)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """

            params = (all_time_volume, total_value_locked, quacks_holders, monthly_volume, timestamp, sync_block)
            result = self.execute_insert(insert_query, params, return_id=True)

            return result

        except Exception as e:
            print(f"Error inserting headline stats: {e}")
            return None
