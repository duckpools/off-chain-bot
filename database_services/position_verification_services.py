from collections import defaultdict
from typing import List, Optional

from database.db_manager import DatabaseManager
from helpers.explorer_calls import get_unspent_boxes_by_token_id
from logger import set_logger

logger = set_logger(__name__)


def get_all_unspent_lend_token_boxes(lend_token_id: str, limit: int = 100) -> list:
    """
    Fetch all unspent boxes containing a specific lend token using pagination.

    Args:
        lend_token_id: The lend token ID to search for
        limit: Number of boxes to fetch per request (default 100)

    Returns:
        List of all unspent boxes containing the lend token
    """
    all_boxes = []
    offset = 0
    page = 0

    while True:
        page += 1
        logger.debug("Fetching lend token boxes page %d (offset=%d, limit=%d) for token %s...",
                      page, offset, limit, lend_token_id[:16])
        try:
            boxes = get_unspent_boxes_by_token_id(lend_token_id, limit=limit, offset=offset)
        except Exception as e:
            logger.error("Explorer API call failed on page %d for token %s: %s",
                         page, lend_token_id[:16], e, exc_info=True)
            raise

        if not boxes:
            logger.debug("Page %d returned empty — done (total so far: %d boxes)", page, len(all_boxes))
            break

        logger.debug("Page %d returned %d boxes", page, len(boxes))
        all_boxes.extend(boxes)

        if len(boxes) < limit:  # Last page reached
            logger.debug("Last page reached (got %d < limit %d). Total: %d boxes",
                         len(boxes), limit, len(all_boxes))
            break

        offset += limit

    return all_boxes


def get_excluded_addresses(pool: dict) -> set:
    """
    Collect all pool/proxy/contract addresses that should be excluded
    from user position counting.

    Args:
        pool: Pool configuration dict

    Returns:
        Set of addresses to exclude
    """
    excluded = set()

    address_keys = [
        'pool', 'collateral', 'repayment', 'child', 'parent',
        'parameter', 'interest_parameter', 'interest',
        'proxy_lend', 'proxy_withdraw', 'proxy_borrow',
        'proxy_repay', 'proxy_partial_repay',
        'proxy_lend_legacy', 'proxy_withdraw_legacy',
    ]

    for key in address_keys:
        value = pool.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            for addr in value:
                excluded.add(addr)
        elif isinstance(value, str):
            excluded.add(value)

    return excluded


def sync_user_current_positions(db: DatabaseManager, pool: dict, sync_block: Optional[int] = None) -> int:
    """
    Sync user current positions for a single pool from on-chain data.

    Args:
        db: Database manager instance
        pool: Pool configuration dict
        sync_block: Block height to mark as sync point

    Returns:
        Number of records upserted
    """
    pool_nft = pool["POOL_NFT"]
    lend_token_id = pool["LEND_TOKEN"]
    decimals = pool.get("decimals", 9)
    pool_nft_short = pool_nft[:16] + "..."

    logger.info("=== sync_user_current_positions START for pool %s ===", pool_nft_short)
    logger.info("  LEND_TOKEN: %s, decimals: %d, sync_block: %s", lend_token_id[:16] + "...", decimals, sync_block)

    # Step 1: Clear existing position entries for this pool
    rows_deleted = db.delete_pool_current_positions(pool_nft)
    logger.info("  Step 1: Deleted %d existing position rows for pool %s", rows_deleted, pool_nft_short)

    # Step 2: Get latest lend_token_value from pool_data_historical
    lend_token_value = db.get_latest_lend_token_value(pool_nft)
    if lend_token_value is None:
        logger.warning("  Step 2: No lend_token_value found in pool_data_historical for pool %s — SKIPPING",
                        pool_nft_short)
        print(f"  No lend_token_value found for pool {pool_nft_short}, skipping")
        return 0
    logger.info("  Step 2: lend_token_value = %s", lend_token_value)

    # Step 3: Fetch all unspent boxes containing this lend token
    try:
        logger.info("  Step 3: Fetching unspent boxes for lend token %s...", lend_token_id[:16] + "...")
        boxes = get_all_unspent_lend_token_boxes(lend_token_id)
        logger.info("  Step 3: Explorer returned %d total boxes", len(boxes))
    except Exception as e:
        logger.error("  Step 3: FAILED to fetch lend token boxes: %s", e, exc_info=True)
        print(f"  Error fetching lend token boxes for pool {pool_nft_short}: {e}")
        return 0

    if not boxes:
        logger.warning("  Step 3: No unspent boxes found for lend token — returning 0")
        return 0

    # Log a sample of box addresses for debugging
    sample_size = min(5, len(boxes))
    for i in range(sample_size):
        box = boxes[i]
        box_addr = box.get("address", "N/A")
        box_assets = [f"{a['tokenId'][:12]}...={a['amount']}" for a in box.get("assets", [])]
        logger.debug("  Sample box %d: address=%s...  assets=%s", i, box_addr[:30], box_assets)

    # Step 4: Get excluded addresses
    excluded = get_excluded_addresses(pool)
    logger.info("  Step 4: Built exclusion set with %d addresses", len(excluded))
    for addr in excluded:
        logger.debug("    Excluded: %s...", addr[:40])

    # Step 5: Group lend token amounts by address, excluding contract addresses
    address_tokens = defaultdict(int)  # raw token amounts (before decimal division)
    boxes_excluded = 0
    boxes_no_token = 0
    boxes_matched = 0

    for box in boxes:
        box_address = box.get("address", "")
        if box_address in excluded:
            boxes_excluded += 1
            continue

        # Find the lend token in the box's assets
        found = False
        for asset in box.get("assets", []):
            if asset["tokenId"] == lend_token_id:
                token_amount = int(asset["amount"])
                address_tokens[box_address] += token_amount
                boxes_matched += 1
                found = True
                break

        if not found:
            boxes_no_token += 1

    logger.info("  Step 5: Box breakdown — matched: %d, excluded: %d, no_lend_token: %d (of %d total)",
                boxes_matched, boxes_excluded, boxes_no_token, len(boxes))
    logger.info("  Step 5: Found %d unique user addresses with lend tokens", len(address_tokens))

    if not address_tokens:
        logger.warning("  Step 5: No user addresses with lend tokens after filtering — returning 0")
        return 0

    # Log top holders
    sorted_holders = sorted(address_tokens.items(), key=lambda x: x[1], reverse=True)
    for addr, raw_tokens in sorted_holders[:5]:
        human_tokens = raw_tokens / (10 ** decimals)
        logger.debug("  Top holder: %s... raw=%d human=%.6f", addr[:30], raw_tokens, human_tokens)

    # Step 6: Convert to position data tuples
    positions_data = []
    for address, raw_tokens in address_tokens.items():
        position_tokens = raw_tokens / (10 ** decimals)
        position_value = position_tokens * lend_token_value
        positions_data.append((address, pool_nft, position_tokens, position_value))

    logger.info("  Step 6: Prepared %d position records for upsert", len(positions_data))

    # Step 7: Batch upsert
    try:
        num_upserted = db.batch_upsert_user_current_positions(positions_data, sync_block)
        logger.info("  Step 7: Upserted %d position records (of %d prepared)", num_upserted, len(positions_data))
    except Exception as e:
        logger.error("  Step 7: FAILED to upsert positions: %s", e, exc_info=True)
        return 0

    logger.info("=== sync_user_current_positions DONE for pool %s: %d positions ===", pool_nft_short, num_upserted)
    return num_upserted


def sync_all_user_current_positions(db: DatabaseManager, pools: list, sync_block: Optional[int] = None) -> int:
    """
    Sync user current positions for all pools from on-chain data.

    Args:
        db: Database manager instance
        pools: List of pool configuration dicts
        sync_block: Block height to mark as sync point

    Returns:
        Total number of records upserted across all pools
    """
    logger.info("sync_all_user_current_positions: Starting for %d pools (sync_block=%s)", len(pools), sync_block)
    total_upserted = 0

    for i, pool in enumerate(pools, 1):
        pool_nft = pool.get("POOL_NFT", "unknown")
        pool_nft_short = pool_nft[:8] + "..."

        try:
            num_upserted = sync_user_current_positions(db, pool, sync_block)
            total_upserted += num_upserted
            print(f"  Pool {i}/{len(pools)} ({pool_nft_short}): {num_upserted} positions ✓")
        except Exception as e:
            logger.error("Pool %d/%d (%s): Unhandled exception: %s", i, len(pools), pool_nft_short, e, exc_info=True)
            print(f"  Pool {i}/{len(pools)} ({pool_nft_short}): ERROR - {e}")
            continue

    logger.info("sync_all_user_current_positions: DONE — total %d positions across %d pools",
                total_upserted, len(pools))
    print(f"  Total position records: {total_upserted} ✓")

    return total_upserted
