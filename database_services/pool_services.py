from current_pools import current_pools
from database.db_manager import DatabaseManager
from database_services.data_aggregation.pool_stats import borrow_apy, total_borrowed, lend_apy, pool_utilization
from helpers.platform_functions import get_pool_box, get_transaction_timestamp


def update_pool_v1(db: DatabaseManager, pool, sync_block: int = None):
    """V1 implementation of update_pool - original logic."""
    # Business logic here
    pool_box = get_pool_box(pool["pool"], pool["POOL_NFT"])
    borrowed = total_borrowed(pool, pool_box)
    if pool["is_Erg"]:
        assets_in_Pool = pool_box["value"] - pool["InitializedPoolAmount"]
    else:
        assets_in_Pool = pool_box["assets"][3]["amount"] - pool["InitializedPoolAmount"]
    total_lent = borrowed + assets_in_Pool

    # Divide by pool decimals to get user-friendly values
    decimals = pool["decimals"]
    total_lent_friendly = total_lent / (10 ** decimals)
    borrowed_friendly = borrowed / (10 ** decimals)

    borrow_rate = borrow_apy(pool, pool_box)
    lend_rate = lend_apy(pool, pool_box)
    # Call raw DB function
    return db.upsert_pool(pool["POOL_NFT"], pool["CURRENCY_ID_DB"], total_lent_friendly, borrowed_friendly, lend_rate, borrow_rate,
                          sync_block)


def update_pool_v2(db: DatabaseManager, pool, sync_block: int = None):
    """V2 implementation of update_pool - to be implemented."""
    raise NotImplementedError("V2 pool update logic not yet implemented")


def update_pool(db: DatabaseManager, pool, sync_block: int = None):
    """Dispatcher for update_pool based on pool version."""
    if pool["version"] == 1:
        return update_pool_v1(db, pool, sync_block)
    elif pool["version"] == 2:
        return update_pool_v2(db, pool, sync_block)
    else:
        raise ValueError(f"Unknown pool version: {pool['version']}")


def sync_all_pools_v1(db: DatabaseManager, sync_block: int = None):
    """V1 implementation of sync_all_pools - original logic."""
    # Higher-level service function
    for pool in current_pools:
        if pool.get("version", 1) == 1:
            update_pool(db, pool, sync_block)


def sync_all_pools_v2(db: DatabaseManager, sync_block: int = None):
    """V2 implementation of sync_all_pools - to be implemented."""
    raise NotImplementedError("V2 sync_all_pools logic not yet implemented")


def sync_all_pools(db: DatabaseManager, sync_block: int = None):
    """Dispatcher for sync_all_pools - syncs all pools regardless of version."""
    for pool in current_pools:
        update_pool(db, pool, sync_block)


def sync_all_pools_batched_v1(db: DatabaseManager, sync_block: int = None):
    """V1 implementation of sync_all_pools_batched - original logic."""
    print("Starting batch pool sync (V1)...")

    pools_batch_data = []

    for pool in current_pools:
        if pool.get("version", 1) != 1:
            continue

        try:
            pool_box = get_pool_box(pool["pool"], pool["POOL_NFT"])

            # Calculate metrics
            borrowed = total_borrowed(pool, pool_box)
            if pool["is_Erg"]:
                assets_in_Pool = pool_box["value"] - pool["InitializedPoolAmount"]
            else:
                assets_in_Pool = pool_box["assets"][3]["amount"] - pool["InitializedPoolAmount"]

            total_lent = borrowed + assets_in_Pool

            # Divide by pool decimals to get user-friendly values
            decimals = pool["decimals"]
            total_lent_friendly = total_lent / (10 ** decimals)
            borrowed_friendly = borrowed / (10 ** decimals)

            borrow_rate = borrow_apy(pool, pool_box)
            lend_rate = lend_apy(pool, pool_box)

            # Add to batch
            pools_batch_data.append((
                pool["POOL_NFT"],
                pool["CURRENCY_ID_DB"],
                total_lent_friendly,
                borrowed_friendly,
                lend_rate,
                borrow_rate,
                sync_block
            ))

        except Exception as e:
            print(f"Error processing pool {pool['POOL_NFT']}: {e}")
            continue

    # Batch insert/update all pools
    if pools_batch_data:
        success_count = db.batch_upsert_pools(pools_batch_data)
        print(f"Successfully updated {success_count}/{len(pools_batch_data)} V1 pools")
    else:
        print("No V1 pool data to update")


def sync_all_pools_batched_v2(db: DatabaseManager, sync_block: int = None):
    """V2 implementation of sync_all_pools_batched - to be implemented."""
    raise NotImplementedError("V2 sync_all_pools_batched logic not yet implemented")


def sync_all_pools_batched(db: DatabaseManager, sync_block: int = None):
    """
    Dispatcher for sync_all_pools_batched - syncs all pools using batch processing.
    Processes V1 and V2 pools separately.
    """
    print("Starting batch pool sync...")

    # Process V1 pools
    v1_pools = [p for p in current_pools if p.get("version", 1) == 1]
    if v1_pools:
        sync_all_pools_batched_v1(db, sync_block)

    # Process V2 pools
    v2_pools = [p for p in current_pools if p.get("version", 1) == 2]
    if v2_pools:
        try:
            sync_all_pools_batched_v2(db, sync_block)
        except NotImplementedError:
            print("V2 pool sync not yet implemented, skipping V2 pools")


def sync_pool_interest_data_v1(db: DatabaseManager, pool, pool_boxes, min_height=0, sync_block: int = None):
    """V1 implementation of sync_pool_interest_data - original logic."""
    for pool_box in pool_boxes:
        if pool_box["address"] != pool["pool"]:
            continue

        # Skip boxes below min_height
        if pool_box.get("settlementHeight", 0) <= min_height:
            continue

        borrowed = total_borrowed(pool, pool_box)
        if pool["is_Erg"]:
            assets_in_Pool = pool_box["value"] - pool["InitializedPoolAmount"]
        else:
            assets_in_Pool = pool_box["assets"][3]["amount"] - pool["InitializedPoolAmount"]
        total_lent = borrowed + assets_in_Pool

        # Divide by pool decimals to get user-friendly values
        decimals = pool["decimals"]
        total_lent_friendly = total_lent / (10 ** decimals)
        borrowed_friendly = borrowed / (10 ** decimals)

        lend_rate = lend_apy(pool, pool_box)
        borrow_rate = borrow_apy(pool, pool_box)
        utilization = pool_utilization(pool, pool_box)
        lend_token_value = (assets_in_Pool + borrowed) / (pool["LendTokenSupply"] - pool_box["assets"][1]["amount"])
        try:
            timestamp = get_transaction_timestamp(pool_box["transactionId"])
        except Exception:
            print("Error getting timestamp for pool box")
            continue
        print(db.upsert_pool_data_historical(
            pool["POOL_NFT"],
            pool_box["settlementHeight"],
            pool_box["transactionId"],
            lend_rate,
            borrow_rate,
            utilization,
            total_lent_friendly,
            borrowed_friendly,
            timestamp,
            pool_box["boxId"],
            lend_token_value,
            sync_block
        ))


def sync_pool_interest_data_v2(db: DatabaseManager, pool, pool_boxes, min_height=0, sync_block: int = None):
    """V2 implementation of sync_pool_interest_data - to be implemented."""
    raise NotImplementedError("V2 sync_pool_interest_data logic not yet implemented")


def sync_pool_interest_data(db: DatabaseManager, pool, pool_boxes, min_height=0, sync_block: int = None):
    """
    Dispatcher for sync_pool_interest_data based on pool version.
    Sync pool interest data for boxes above min_height.

    :param db: Database manager instance
    :param pool: Pool configuration
    :param pool_boxes: List of pool boxes
    :param min_height: Minimum block height to process (default: 0)
    :param sync_block: Block height when this data was synced
    """
    if pool["version"] == 1:
        return sync_pool_interest_data_v1(db, pool, pool_boxes, min_height, sync_block)
    elif pool["version"] == 2:
        return sync_pool_interest_data_v2(db, pool, pool_boxes, min_height, sync_block)
    else:
        raise ValueError(f"Unknown pool version: {pool['version']}")


def sync_pool_interest_data_batched_v1(db: DatabaseManager, pool, pool_boxes, min_height=0, batch_size=500,
                                       sync_block: int = None):
    """V1 implementation of sync_pool_interest_data_batched - original logic."""
    batch_data = []
    processed_count = 0

    for pool_box in pool_boxes:
        if pool_box["address"] != pool["pool"]:
            continue

        # Skip boxes below min_height
        if pool_box.get("settlementHeight", 0) <= min_height:
            continue

        try:
            # Calculate metrics
            borrowed = total_borrowed(pool, pool_box)
            if pool["is_Erg"]:
                assets_in_Pool = pool_box["value"] - pool["InitializedPoolAmount"]
            else:
                assets_in_Pool = pool_box["assets"][3]["amount"] - pool["InitializedPoolAmount"]

            total_lent = borrowed + assets_in_Pool

            # Divide by pool decimals to get user-friendly values
            decimals = pool["decimals"]
            total_lent_friendly = total_lent / (10 ** decimals)
            borrowed_friendly = borrowed / (10 ** decimals)

            lend_rate = lend_apy(pool, pool_box)
            borrow_rate = borrow_apy(pool, pool_box)
            utilization = pool_utilization(pool, pool_box)
            lend_token_value = (assets_in_Pool + borrowed) / (pool["LendTokenSupply"] - pool_box["assets"][1]["amount"])

            try:
                timestamp = get_transaction_timestamp(pool_box["transactionId"])
            except Exception:
                print(f"Error getting timestamp for pool box {pool_box['boxId']}, skipping")
                continue

            # Add to batch - use settlement height as sync_block if not provided
            box_sync_block = sync_block

            batch_data.append((
                pool["POOL_NFT"],
                pool_box["settlementHeight"],
                pool_box["transactionId"],
                lend_rate,
                borrow_rate,
                utilization,
                total_lent_friendly,
                borrowed_friendly,
                timestamp,
                pool_box["boxId"],
                lend_token_value,
                box_sync_block
            ))

            processed_count += 1

            # Process batch when it reaches batch_size
            if len(batch_data) >= batch_size:
                success_count = db.batch_upsert_pool_data_historical(batch_data)
                batch_data = []

        except Exception as e:
            print(f"Error processing pool box {pool_box.get('boxId', 'unknown')}: {e}")
            continue

    # Process any remaining data in the final batch
    if batch_data:
        success_count = db.batch_upsert_pool_data_historical(batch_data)


def sync_pool_interest_data_batched_v2(db: DatabaseManager, pool, pool_boxes, min_height=0, batch_size=500,
                                       sync_block: int = None):
    """V2 implementation of sync_pool_interest_data_batched - to be implemented."""
    raise NotImplementedError("V2 sync_pool_interest_data_batched logic not yet implemented")


def sync_pool_interest_data_batched(db: DatabaseManager, pool, pool_boxes, min_height=0, batch_size=500,
                                    sync_block: int = None):
    """
    Dispatcher for sync_pool_interest_data_batched based on pool version.
    Sync pool interest data using batch processing.

    :param db: Database manager instance
    :param pool: Pool configuration
    :param pool_boxes: List of pool boxes
    :param min_height: Minimum block height to process
    :param batch_size: Number of records to process in each batch
    :param sync_block: Block height when this data was synced
    """
    if pool["version"] == 1:
        return sync_pool_interest_data_batched_v1(db, pool, pool_boxes, min_height, batch_size, sync_block)
    elif pool["version"] == 2:
        return sync_pool_interest_data_batched_v2(db, pool, pool_boxes, min_height, batch_size, sync_block)
    else:
        raise ValueError(f"Unknown pool version: {pool['version']}")