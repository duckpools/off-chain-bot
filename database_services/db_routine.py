from database.db_manager import DatabaseManager
from database_services.pool_services import sync_all_pools


def db_routine():
    db = DatabaseManager()
    sync_all_pools(db)