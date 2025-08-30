from database.db_manager import DatabaseManager
from database_services.sync_services import sync_all, sync_from_last_update
from helpers.node_calls import current_height


def db_routine():
    db = DatabaseManager()
    sync_from_last_update(db, current_block_height=current_height())
    #sync_all(db, sync_block=current_height())
