from current_pools import current_pools
from database.db_manager import DatabaseManager
from database_services.data_aggregation.pool_stats import borrow_apy, total_borrowed, lend_apy, pool_utilization
from helpers.platform_functions import get_pool_box, get_transaction_timestamp
from logger import set_logger

logger = set_logger(__name__)


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
    """V2 implementation of update_pool - token-only pools."""
    pool_box = get_pool_box(pool["pool"], pool["POOL_NFT"])
    borrowed = total_borrowed(pool, pool_box)

    # V2 is token-only, always use assets[3]
    assets_in_Pool = pool_box["assets"][3]["amount"] - pool["InitializedPoolAmount"]
    total_lent = borrowed + assets_in_Pool

    # Divide by pool decimals to get user-friendly values
    decimals = pool["decimals"]
    total_lent_friendly = total_lent / (10 ** decimals)
    borrowed_friendly = borrowed / (10 ** decimals)

    borrow_rate = borrow_apy(pool, pool_box)
    lend_rate = lend_apy(pool, pool_box)

    return db.upsert_pool(
        pool["POOL_NFT"], pool["CURRENCY_ID_DB"],
        total_lent_friendly, borrowed_friendly,
        lend_rate, borrow_rate, sync_block
    )


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
    """V2 implementation - sync all V2 pools."""
    for pool in current_pools:
        if pool.get("version") == 2:
            update_pool(db, pool, sync_block)


def sync_all_pools(db: DatabaseManager, sync_block: int = None):
    """Dispatcher for sync_all_pools - syncs all pools regardless of version."""
    for pool in current_pools:
        update_pool(db, pool, sync_block)


def sync_all_pools_batched_v1(db: DatabaseManager, sync_block: int = None):
    """V1 implementation of sync_all_pools_batched - original logic."""
    logger.info("Starting batch pool sync (V1)...")

    pools_batch_data = []

    for pool in current_pools:
        if pool.get("version", 1) != 1:
            continue

        pool_nft_short = pool["POOL_NFT"][:16] + "..."
        try:
            pool_box = get_pool_box(pool["pool"], pool["POOL_NFT"])

            if pool_box is None:
                logger.error("get_pool_box returned None for pool %s — skipping", pool_nft_short)
                continue

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
            logger.debug("Pool %s: total_lent=%.4f, borrowed=%.4f, lend_apy=%.4f",
                         pool_nft_short, total_lent_friendly, borrowed_friendly, lend_rate)

        except Exception as e:
            logger.error("Error processing pool %s: %s", pool_nft_short, e, exc_info=True)
            continue

    # Batch insert/update all pools
    if pools_batch_data:
        success_count = db.batch_upsert_pools(pools_batch_data)
        logger.info("Successfully updated %d/%d V1 pools", success_count, len(pools_batch_data))
    else:
        logger.warning("No V1 pool data to update")


def sync_all_pools_batched_v2(db: DatabaseManager, sync_block: int = None):
    """V2 implementation of sync_all_pools_batched - token-only pools."""
    logger.info("Starting batch pool sync (V2)...")
    pools_batch_data = []

    for pool in current_pools:
        if pool.get("version") != 2:
            continue

        pool_nft_short = pool["POOL_NFT"][:16] + "..."
        try:
            pool_box = get_pool_box(pool["pool"], pool["POOL_NFT"])

            if pool_box is None:
                logger.error("get_pool_box returned None for V2 pool %s — skipping", pool_nft_short)
                continue

            borrowed = total_borrowed(pool, pool_box)

            # V2 is token-only, always use assets[3]
            assets_in_Pool = pool_box["assets"][3]["amount"] - pool["InitializedPoolAmount"]
            total_lent = borrowed + assets_in_Pool

            decimals = pool["decimals"]
            total_lent_friendly = total_lent / (10 ** decimals)
            borrowed_friendly = borrowed / (10 ** decimals)

            borrow_rate = borrow_apy(pool, pool_box)
            lend_rate = lend_apy(pool, pool_box)

            pools_batch_data.append((
                pool["POOL_NFT"],
                pool["CURRENCY_ID_DB"],
                total_lent_friendly,
                borrowed_friendly,
                lend_rate,
                borrow_rate,
                sync_block
            ))
            logger.debug("V2 Pool %s: total_lent=%.4f, borrowed=%.4f", pool_nft_short, total_lent_friendly, borrowed_friendly)

        except Exception as e:
            logger.error("Error processing V2 pool %s: %s", pool_nft_short, e, exc_info=True)
            continue

    if pools_batch_data:
        success_count = db.batch_upsert_pools(pools_batch_data)
        logger.info("Successfully updated %d/%d V2 pools", success_count, len(pools_batch_data))
    else:
        logger.warning("No V2 pool data to update")


def sync_all_pools_batched(db: DatabaseManager, sync_block: int = None):
    """
    Dispatcher for sync_all_pools_batched - syncs all pools using batch processing.
    Processes V1 and V2 pools separately.
    """
    v1_pools = [p for p in current_pools if p.get("version", 1) == 1]
    v2_pools = [p for p in current_pools if p.get("version", 1) == 2]
    logger.info("Starting batch pool sync — %d V1, %d V2 pools", len(v1_pools), len(v2_pools))

    # Process V1 pools
    if v1_pools:
        sync_all_pools_batched_v1(db, sync_block)

    # Process V2 pools
    if v2_pools:
        try:
            sync_all_pools_batched_v2(db, sync_block)
        except NotImplementedError:
            logger.warning("V2 pool sync not yet implemented, skipping V2 pools")


def sync_pool_interest_data_v1(db: DatabaseManager, pool, pool_boxes, min_height=0, sync_block: int = None):
    """V1 implementation of sync_pool_interest_data - original logic."""
    pool_nft_short = pool["POOL_NFT"][:16] + "..."
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
        except Exception as e:
            logger.warning("Error getting timestamp for pool box %s: %s", pool_box.get('boxId', '?')[:16], e)
            continue
        result = db.upsert_pool_data_historical(
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
        )
        if result is None:
            logger.error("upsert_pool_data_historical returned None for pool %s, height %s",
                         pool_nft_short, pool_box.get("settlementHeight"))


def sync_pool_interest_data_v2(db: DatabaseManager, pool, pool_boxes, min_height=0, sync_block: int = None):
    """V2 implementation of sync_pool_interest_data - token-only pools."""
    for pool_box in pool_boxes:
        if pool_box["address"] != pool["pool"]:
            continue

        # Skip boxes below min_height
        if pool_box.get("settlementHeight", 0) <= min_height:
            continue

        borrowed = total_borrowed(pool, pool_box)
        # V2 is token-only, always use assets[3]
        assets_in_Pool = pool_box["assets"][3]["amount"] - pool["InitializedPoolAmount"]
        total_lent = borrowed + assets_in_Pool

        # Divide by pool decimals to get user-friendly values
        decimals = pool["decimals"]
        total_lent_friendly = total_lent / (10 ** decimals)
        borrowed_friendly = borrowed / (10 ** decimals)

        lend_rate = lend_apy(pool, pool_box)
        borrow_rate = borrow_apy(pool, pool_box)
        utilization = pool_utilization(pool, pool_box)

        # V2 lend_token_value calculation
        lend_tokens_circulating = pool["LendTokenSupply"] - pool_box["assets"][1]["amount"]
        lend_token_value = (assets_in_Pool + borrowed) / lend_tokens_circulating

        try:
            timestamp = get_transaction_timestamp(pool_box["transactionId"])
        except Exception as e:
            logger.warning("V2 error getting timestamp for pool box %s: %s",
                           pool_box.get('boxId', '?')[:16], e)
            continue

        if timestamp is None:
            logger.warning("V2 timestamp returned None for box %s (tx=%s) — skipping",
                           pool_box.get('boxId', '?')[:16], pool_box.get('transactionId', '?')[:16])
            continue

        result = db.upsert_pool_data_historical(
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
        )
        if result is None:
            logger.error("V2 upsert_pool_data_historical returned None for pool %s, height %s",
                         pool["POOL_NFT"][:16] + "...", pool_box.get("settlementHeight"))


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
    pool_nft_short = pool["POOL_NFT"][:16] + "..."
    batch_data = []
    processed_count = 0
    skipped_address = 0
    skipped_height = 0
    skipped_timestamp = 0
    skipped_error = 0
    total_upserted = 0

    logger.info("sync_pool_interest_data_batched_v1 START for pool %s — %d boxes, min_height=%d, batch_size=%d",
                pool_nft_short, len(pool_boxes), min_height, batch_size)

    for pool_box in pool_boxes:
        if pool_box["address"] != pool["pool"]:
            skipped_address += 1
            continue

        # Skip boxes below min_height
        if pool_box.get("settlementHeight", 0) <= min_height:
            skipped_height += 1
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
            except Exception as ts_err:
                skipped_timestamp += 1
                logger.warning("Timestamp fetch failed for box %s (tx=%s): %s",
                               pool_box['boxId'][:16], pool_box['transactionId'][:16], ts_err)
                continue

            if timestamp is None:
                skipped_timestamp += 1
                logger.warning("Timestamp returned None for box %s (tx=%s) — skipping",
                               pool_box['boxId'][:16], pool_box['transactionId'][:16])
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
                total_upserted += success_count
                if success_count == 0:
                    logger.error("  Flushed batch FAILED: 0/%d rows upserted for pool %s (processed so far: %d)",
                                 len(batch_data), pool_nft_short, processed_count)
                else:
                    logger.info("  Flushed batch: %d/%d rows upserted (processed so far: %d)",
                                success_count, len(batch_data), processed_count)
                batch_data = []

        except Exception as e:
            skipped_error += 1
            logger.error("Error processing pool box %s (height=%s): %s",
                         pool_box.get('boxId', 'unknown')[:16],
                         pool_box.get('settlementHeight', '?'), e, exc_info=True)
            continue

    # Process any remaining data in the final batch
    if batch_data:
        success_count = db.batch_upsert_pool_data_historical(batch_data)
        total_upserted += success_count
        if success_count == 0:
            logger.error("  Final batch FAILED: 0/%d rows upserted for pool %s", len(batch_data), pool_nft_short)
        else:
            logger.info("  Final batch: %d/%d rows upserted", success_count, len(batch_data))

    logger.info("sync_pool_interest_data_batched_v1 DONE for pool %s — "
                "processed: %d, upserted: %d, skipped_address: %d, skipped_height: %d, "
                "skipped_timestamp: %d, skipped_error: %d",
                pool_nft_short, processed_count, total_upserted,
                skipped_address, skipped_height, skipped_timestamp, skipped_error)


def sync_pool_interest_data_batched_v2(db: DatabaseManager, pool, pool_boxes, min_height=0, batch_size=500,
                                       sync_block: int = None):
    """V2 implementation of sync_pool_interest_data_batched - token-only pools."""
    pool_nft_short = pool["POOL_NFT"][:16] + "..."
    batch_data = []
    processed_count = 0
    skipped_address = 0
    skipped_height = 0
    skipped_timestamp = 0
    skipped_error = 0
    total_upserted = 0

    logger.info("sync_pool_interest_data_batched_v2 START for pool %s — %d boxes, min_height=%d, batch_size=%d",
                pool_nft_short, len(pool_boxes), min_height, batch_size)

    for pool_box in pool_boxes:
        if pool_box["address"] != pool["pool"]:
            skipped_address += 1
            continue

        # Skip boxes below min_height
        if pool_box.get("settlementHeight", 0) <= min_height:
            skipped_height += 1
            continue

        try:
            # Calculate metrics
            borrowed = total_borrowed(pool, pool_box)
            # V2 is token-only, always use assets[3]
            assets_in_Pool = pool_box["assets"][3]["amount"] - pool["InitializedPoolAmount"]
            total_lent = borrowed + assets_in_Pool

            # Divide by pool decimals to get user-friendly values
            decimals = pool["decimals"]
            total_lent_friendly = total_lent / (10 ** decimals)
            borrowed_friendly = borrowed / (10 ** decimals)

            lend_rate = lend_apy(pool, pool_box)
            borrow_rate = borrow_apy(pool, pool_box)
            utilization = pool_utilization(pool, pool_box)

            # V2 lend_token_value calculation
            lend_tokens_circulating = pool["LendTokenSupply"] - pool_box["assets"][1]["amount"]
            lend_token_value = (assets_in_Pool + borrowed) / lend_tokens_circulating

            try:
                timestamp = get_transaction_timestamp(pool_box["transactionId"])
            except Exception as ts_err:
                skipped_timestamp += 1
                logger.warning("V2 timestamp fetch failed for box %s (tx=%s): %s",
                               pool_box['boxId'][:16], pool_box['transactionId'][:16], ts_err)
                continue

            if timestamp is None:
                skipped_timestamp += 1
                logger.warning("V2 timestamp returned None for box %s (tx=%s) — skipping",
                               pool_box['boxId'][:16], pool_box['transactionId'][:16])
                continue

            # Add to batch
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
                total_upserted += success_count
                if success_count == 0:
                    logger.error("  V2 flushed batch FAILED: 0/%d rows upserted for pool %s (processed so far: %d)",
                                 len(batch_data), pool_nft_short, processed_count)
                else:
                    logger.info("  V2 flushed batch: %d/%d rows upserted (processed so far: %d)",
                                success_count, len(batch_data), processed_count)
                batch_data = []

        except Exception as e:
            skipped_error += 1
            logger.error("Error processing V2 pool box %s (height=%s): %s",
                         pool_box.get('boxId', 'unknown')[:16],
                         pool_box.get('settlementHeight', '?'), e, exc_info=True)
            continue

    # Process any remaining data in the final batch
    if batch_data:
        success_count = db.batch_upsert_pool_data_historical(batch_data)
        total_upserted += success_count
        if success_count == 0:
            logger.error("  V2 final batch FAILED: 0/%d rows upserted for pool %s", len(batch_data), pool_nft_short)
        else:
            logger.info("  V2 final batch: %d/%d rows upserted", success_count, len(batch_data))

    logger.info("sync_pool_interest_data_batched_v2 DONE for pool %s — "
                "processed: %d, upserted: %d, skipped_address: %d, skipped_height: %d, "
                "skipped_timestamp: %d, skipped_error: %d",
                pool_nft_short, processed_count, total_upserted,
                skipped_address, skipped_height, skipped_timestamp, skipped_error)


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