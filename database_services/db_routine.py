from database.db_manager import DatabaseManager
from database_services.sync_services import sync_all
from helpers.node_calls import current_height


def db_routine():
    db = DatabaseManager()
    sync_all(db, sync_block=current_height())