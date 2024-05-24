import time

from consts import ERGO_MIN_HEIGHT, NULL_TX_OBJ, MAX_BORROW_TOKENS
from helpers.explorer_calls import get_unspent_boxes_by_address
from helpers.generic_calls import logger
from helpers.platform_functions import get_pool_box, get_pool_box_from_tx


def job_processor(pool, address_to_scan, curr_tx_obj, proxy_job, job_name, height_limit=ERGO_MIN_HEIGHT):
    """Process a job by applying the proxy_job function to unspent boxes.

    Args:
        pool: (dict): The pool to read pool constants from.
        address_to_scan (str): The address to scan for unspent boxes.
        curr_tx_obj (object): The current transaction object.
        proxy_job (function): The function to be applied to each unspent box.
        job_name (str): The name of the job being processed.
        height_limit (int, optional): The minimum creation height of a box to be considered. Defaults to ERGO_MAX_HEIGHT.

    Returns:
        object: The processed transaction object.
    """
    time.sleep(1)
    logger.info("Starting %s request processing", job_name)
    unspent_proxy_boxes = get_unspent_boxes_by_address(address_to_scan)
    logger.debug(unspent_proxy_boxes)
    num_unspent_proxy_boxes = len(unspent_proxy_boxes)
    logger.info(f"Found: {num_unspent_proxy_boxes} boxes")

    if num_unspent_proxy_boxes == 0:
        return None

    processed_tx_obj = curr_tx_obj
    for box in unspent_proxy_boxes:
        transaction_id = box["transactionId"]
        logger.debug(f"{job_name} Proxy Transaction Id: {transaction_id}")

        if int(box["creationHeight"]) < height_limit:
            continue

        try:
            if processed_tx_obj != NULL_TX_OBJ:
                processed_tx_obj = proxy_job(pool, box, processed_tx_obj)
            else:
                proxy_job(pool, box, processed_tx_obj)
        except Exception as e:
            logger.exception(
                f"Failed to process {job_name} proxy box for transaction id: {transaction_id}. Exception: {e}")
    return processed_tx_obj


def op_job_processor(pool, address_to_scan, curr_tx_obj, serialized_r4, proxy_job, job_name, height_limit=ERGO_MIN_HEIGHT):
    """Process a job by applying the proxy_job function to unspent boxes.

    Args:
        pool: (dict): The pool to read pool constants from.
        address_to_scan (str): The address to scan for unspent boxes.
        curr_tx_obj (object): The current transaction object.
        proxy_job (function): The function to be applied to each unspent box.
        job_name (str): The name of the job being processed.
        height_limit (int, optional): The minimum creation height of a box to be considered. Defaults to ERGO_MAX_HEIGHT.

    Returns:
        object: The processed transaction object.
    """
    time.sleep(1)
    logger.info("Starting %s request processing", job_name)
    unspent_proxy_boxes = get_unspent_boxes_by_address(address_to_scan)
    logger.debug(unspent_proxy_boxes)
    num_unspent_proxy_boxes = len(unspent_proxy_boxes)
    logger.info(f"Found: {num_unspent_proxy_boxes} boxes")

    if num_unspent_proxy_boxes == 0:
        return None

    processed_tx_obj = curr_tx_obj
    for box in unspent_proxy_boxes:
        transaction_id = box["transactionId"]
        logger.debug(f"{job_name} Proxy Transaction Id: {transaction_id}")

        if int(box["creationHeight"]) < height_limit:
            continue

        try:
            if processed_tx_obj != NULL_TX_OBJ:
                processed_tx_obj = proxy_job(pool, box, processed_tx_obj, serialized_r4)
            else:
                proxy_job(pool, box, processed_tx_obj, serialized_r4)
        except Exception as e:
            logger.exception(
                f"Failed to process {job_name} proxy box for transaction id: {transaction_id}. Exception: {e}")
    return processed_tx_obj


def latest_pool_info(pool, latest_tx):
    if latest_tx is None:
        erg_pool_box = get_pool_box(pool["pool"], pool["POOL_NFT"])
        borrowed = MAX_BORROW_TOKENS - int(erg_pool_box["assets"][2]["amount"])
    else:
        erg_pool_box = get_pool_box_from_tx(latest_tx["txId"])
        borrowed = latest_tx["finalBorrowed"]
    return erg_pool_box, borrowed

def op_latest_pool_info(pool, latest_tx):
    if latest_tx is None:
        pool_box = get_pool_box(pool["pool"], pool["POOL_NFT"])
    else:
        pool_box = get_pool_box_from_tx(latest_tx["txId"])
    return pool_box
