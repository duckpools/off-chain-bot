import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Tuple

class CoreDB:
    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')
        if not self.db_url:
            raise ValueError("DATABASE_URL not set")

    @contextmanager
    def get_connection(self):
        conn = psycopg2.connect(self.db_url)
        try:
            yield conn
        except:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute_query(self, query: str, params: Optional[Tuple]=None) -> List[Dict[str,Any]]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                return [dict(r) for r in cur.fetchall()]

    def execute_insert(self, query: str, params: Optional[Tuple]=None, return_id: bool=True) -> Optional[Any]:
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                result = None
                if return_id and cur.rowcount > 0:
                    result = cur.fetchone()[0]
                conn.commit()
                return result