import os
import time
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Tuple, Callable
import logging

logger = logging.getLogger(__name__)


class CoreDB:
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        self.db_url = os.getenv('DATABASE_URL')
        if not self.db_url:
            raise ValueError("DATABASE_URL not set")
        self.max_retries = max_retries
        self.base_delay = base_delay

    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if an error is worth retrying"""
        if isinstance(error, psycopg2.OperationalError):
            error_msg = str(error).lower()
            retryable_errors = [
                'connection reset by peer',
                'server closed the connection unexpectedly',
                'connection refused',
                'timeout expired',
                'connection timed out',
                'could not connect to server',
                'ssl syscall error'
            ]
            return any(err in error_msg for err in retryable_errors)
        return False

    def _retry_operation(self, operation: Callable, *args, **kwargs):
        """Execute an operation with retry logic"""
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                return operation(*args, **kwargs)
            except Exception as e:
                last_exception = e

                if attempt == self.max_retries:
                    # Last attempt failed, re-raise the exception
                    logger.error(f"Operation failed after {self.max_retries + 1} attempts: {e}")
                    raise

                if not self._is_retryable_error(e):
                    # Not a retryable error, re-raise immediately
                    logger.error(f"Non-retryable error: {e}")
                    raise

                # Calculate delay with exponential backoff
                delay = self.base_delay * (2 ** attempt)
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay} seconds...")
                time.sleep(delay)

        # This shouldn't be reached, but just in case
        raise last_exception

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

    def _execute_query_impl(self, query: str, params: Optional[Tuple] = None) -> List[Dict[str, Any]]:
        """Internal implementation of execute_query"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                return [dict(r) for r in cur.fetchall()]

    def execute_query(self, query: str, params: Optional[Tuple] = None) -> List[Dict[str, Any]]:
        """Execute a query with retry logic"""
        return self._retry_operation(self._execute_query_impl, query, params)

    def _execute_insert_impl(self, query: str, params: Optional[Tuple] = None, return_id: bool = True) -> Optional[Any]:
        """Internal implementation of execute_insert"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                result = None
                if return_id and cur.rowcount > 0:
                    result = cur.fetchone()[0]
                conn.commit()
                return result

    def execute_insert(self, query: str, params: Optional[Tuple] = None, return_id: bool = True) -> Optional[Any]:
        """Execute an insert with retry logic"""
        return self._retry_operation(self._execute_insert_impl, query, params, return_id)

    def execute_upsert(self, query: str, params: Optional[Tuple] = None) -> Optional[Any]:
        """Execute an upsert with retry logic"""
        return self._retry_operation(self._execute_insert_impl, query, params, False)