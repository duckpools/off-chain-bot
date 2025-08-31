from current_pools import current_pools
from database.db_manager import DatabaseManager
from database_services.data_aggregation.pool_stats import borrow_apy, total_borrowed, lend_apy, pool_utilization
from helpers.platform_functions import get_pool_box, get_transaction_timestamp


def update_pool(db: DatabaseManager, pool, sync_block: int = None):
    # Business logic here
    pool_box = get_pool_box(pool["pool"], pool["POOL_NFT"])
    borrowed = total_borrowed(pool, pool_box)
    if pool["is_Erg"]:
        assets_in_Pool = pool_box["value"] - pool["InitializedPoolAmount"]
    else:
        assets_in_Pool = pool_box["assets"][3]["amount"] - pool["InitializedPoolAmount"]
    total_lent = borrowed + assets_in_Pool
    borrow_rate = borrow_apy(pool, pool_box)
    lend_rate = lend_apy(pool, pool_box)
    # Call raw DB function
    return db.upsert_pool(pool["POOL_NFT"], pool["CURRENCY_ID_DB"], total_lent, borrowed, lend_rate, borrow_rate,
                          sync_block)


def sync_all_pools(db: DatabaseManager, sync_block: int = None):
    # Higher-level service function
    for pool in current_pools:
        update_pool(db, pool, sync_block)


def sync_all_pools_batched(db: DatabaseManager, sync_block: int = None):
    """
    Sync all pools using batch processing for better performance.
    """
    print("Starting batch pool sync...")

    pools_batch_data = []

    for pool in current_pools:
        try:
            pool_box = get_pool_box(pool["pool"], pool["POOL_NFT"])

            # Calculate metrics
            borrowed = total_borrowed(pool, pool_box)
            if pool["is_Erg"]:
                assets_in_Pool = pool_box["value"] - pool["InitializedPoolAmount"]
            else:
                assets_in_Pool = pool_box["assets"][3]["amount"] - pool["InitializedPoolAmount"]

            total_lent = borrowed + assets_in_Pool
            borrow_rate = borrow_apy(pool, pool_box)
            lend_rate = lend_apy(pool, pool_box)

            # Add to batch
            pools_batch_data.append((
                pool["POOL_NFT"],
                pool["CURRENCY_ID_DB"],
                total_lent,
                borrowed,
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
        print(f"Successfully updated {success_count}/{len(pools_batch_data)} pools")
    else:
        print("No pool data to update")


def sync_pool_interest_data(db: DatabaseManager, pool, pool_boxes, min_height=0, sync_block: int = None):
    """
    Sync pool interest data for boxes above min_height.

    :param db: Database manager instance
    :param pool: Pool configuration
    :param pool_boxes: List of pool boxes
    :param min_height: Minimum block height to process (default: 0)
    :param sync_block: Block height when this data was synced
    """
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
            total_lent,
            borrowed,
            timestamp,
            pool_box["boxId"],
            lend_token_value,
            sync_block
        ))


def sync_pool_interest_data_batched(db: DatabaseManager, pool, pool_boxes, min_height=0, batch_size=500,
                                    sync_block: int = None):
    """
    Sync pool interest data using batch processing.

    :param db: Database manager instance
    :param pool: Pool configuration
    :param pool_boxes: List of pool boxes
    :param min_height: Minimum block height to process
    :param batch_size: Number of records to process in each batch
    :param sync_block: Block height when this data was synced
    """
    print(f"Starting batch pool interest sync for {pool['POOL_NFT']}...")

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
                total_lent,
                borrowed,
                timestamp,
                pool_box["boxId"],
                lend_token_value,
                box_sync_block
            ))

            processed_count += 1

            # Process batch when it reaches batch_size
            if len(batch_data) >= batch_size:
                success_count = db.batch_upsert_pool_data_historical(batch_data)
                print(f"Processed batch of {len(batch_data)} pool data records, {success_count} successful")
                batch_data = []

        except Exception as e:
            print(f"Error processing pool box {pool_box.get('boxId', 'unknown')}: {e}")
            continue

    # Process any remaining data in the final batch
    if batch_data:
        success_count = db.batch_upsert_pool_data_historical(batch_data)
        print(f"Processed final batch of {len(batch_data)} pool data records, {success_count} successful")

    print(f"Total pool data records processed: {processed_count}")