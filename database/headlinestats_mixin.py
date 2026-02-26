from typing import Optional, Dict
import json

from logger import set_logger

logger = set_logger(__name__)


class HeadlinestatsMixin:
    def insert_headlinestats(self,
                            all_time_volume_by_asset: Dict[str, float],
                            total_value_locked: float,
                            quacks_holders: int,
                            timestamp: int,
                            sync_block: Optional[int] = None) -> Optional[int]:
        """
        Insert a new headline stats record (historical tracking).

        Args:
            all_time_volume_by_asset: Dictionary mapping pooled_asset to total volume
            total_value_locked: Current total value locked
            quacks_holders: Number of QUACKS token holders
            timestamp: Unix timestamp when this data was recorded
            sync_block: Block height when this data was synced

        Returns:
            id of the inserted record if successful, None if failed
        """
        try:
            insert_query = """
                INSERT INTO headlinestats (all_time_volume_by_asset, total_value_locked, quacks_holders, timestamp, sync_block)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """

            params = (json.dumps(all_time_volume_by_asset), total_value_locked, quacks_holders, timestamp, sync_block)
            result = self.execute_insert(insert_query, params, return_id=True)

            return result

        except Exception as e:
            print(f"Error inserting headline stats: {e}")
            logger.error("Error inserting headline stats: %s", e, exc_info=True)
            return None
