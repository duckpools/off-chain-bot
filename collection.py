import json
import requests
import time

from consts import MIN_BOX_VALUE, TX_FEE
from client_consts import node_url, headers, node_address
from helpers.explorer_calls import get_unspent_boxes_by_address
from helpers.node_calls import sign_tx, box_id_to_binary, generate_dummy_script
from logger import set_logger

logger = set_logger(__name__)


def find_boxes(dummy_address, limit=50):
    logger.info("Finding UTXOs to Collect")

    all_unspent_boxes = []
    offset = 0

    while True:
        # Fetch a chunk of unspent boxes
        unspent_boxes = get_unspent_boxes_by_address(dummy_address, limit=limit, offset=offset)

        # If no unspent boxes are returned, break out of the loop
        if not unspent_boxes:
            break

        # Add the fetched boxes to the list
        all_unspent_boxes.extend(unspent_boxes)

        # Log the current progress
        logger.info(f"Found {len(all_unspent_boxes)} UTXOs so far.")

        # Update the offset for the next API call
        offset += limit

    logger.info(f"Total UTXOs found: {len(all_unspent_boxes)}")

    return all_unspent_boxes

def genereate_binaries(boxes):
    print(boxes)
    logger.info("Getting UTXO Binaries")
    resp = []
    for box in boxes:
        resp.append(box_id_to_binary(box["boxId"]))
    return resp

def collect(binaries):
    logger.info("Beginning Collection")
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": node_address,
                    "value": MIN_BOX_VALUE * len(binaries) - TX_FEE - MIN_BOX_VALUE,
                    "assets": [
                    ],
                    "registers": {
                    }
                }
            ],
            "fee": TX_FEE,
            "inputsRaw":
                binaries,
            "dataInputsRaw":
                []
        }
    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)
    if tx_id != -1:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    else:
        logger.error("Failed to submit transaction")


dummy_script = generate_dummy_script(node_address)
boxes = find_boxes(dummy_script)
binaries = genereate_binaries(boxes)
collect(binaries)