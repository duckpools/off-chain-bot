import json
import requests
import time

from consts import MIN_BOX_VALUE, node_address, TX_FEE, node_url, headers
from helpers.node_calls import sign_tx, box_id_to_binary, generate_dummy_script
from logger import set_logger

logger = set_logger(__name__)


def split_utxos():
    logger.info("Setup stage 0/2")
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": node_address,
                    "value": 2 * MIN_BOX_VALUE,
                    "assets": [
                    ],
                    "registers": {
                    }
                },
                {
                    "address": node_address,
                    "value": 2 * MIN_BOX_VALUE,
                    "assets": [
                    ],
                    "registers": {
                    }
                }
            ],
            "fee": TX_FEE,
            "inputsRaw":
                [],
            "dataInputsRaw":
                []
        }
    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)
    if tx_id != -1:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    else:
        logger.error("Failed to submit transaction")


def get_input_boxes():
    time.sleep(10)
    current_boxes = json.loads(requests.get(f"{node_url}/wallet/boxes/unspent", params={"minConfirmations": -1}, headers=headers).text)
    print(current_boxes)
    boxes = []
    for box in current_boxes:
        if box["box"]["value"] >= 2 * MIN_BOX_VALUE:
            boxes.append(box)
            if len(boxes) == 2:
                return boxes
    return None


def create_mint_tx(input_boxes, index):
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": node_address,
                    "ergValue": MIN_BOX_VALUE,
                    "amount": 70,
                    "name": "Dummy",
                    "description": "Dummy token",
                    "decimals": 0,
                    "registers": {
                    }
                }
            ],
            "fee": TX_FEE,
            "inputsRaw":
                [box_id_to_binary(input_boxes[index]["box"]["boxId"])],
            "dataInputsRaw":
                []
        }

    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)
    if tx_id != -1:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    else:
        logger.error("Failed to submit transaction")

def mint_dummy_tokens():
    logger.info("Setup stage 1/2")
    input_boxes = get_input_boxes()
    if not input_boxes:
        logger.info("Could not find input boxes with sufficient ERGs")
        return
    create_mint_tx(input_boxes, 0)
    create_mint_tx(input_boxes, 1)
    return input_boxes


def create_dummy_boxes(input_boxes, dummy_script):
    logger.info("Setup stage 2/2")
    transaction_to_sign = \
        {
            "requests": [
            ],
            "fee": TX_FEE,
            "inputsRaw":
                [],
            "dataInputsRaw":
                []
        }
    for _ in range(70):
        transaction_to_sign["requests"].append({
            "address": dummy_script,
            "value": MIN_BOX_VALUE,
            "assets": [
                {
                    "tokenId": input_boxes[0]["box"]["boxId"],
                    "amount": 1
                },
                {
                    "tokenId": input_boxes[1]["box"]["boxId"],
                    "amount": 1
                }
            ],
            "registers": {
            }
        })
    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)
    if tx_id != -1:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    else:
        logger.error("Failed to submit transaction")


dummy_script = generate_dummy_script(node_address)
split_utxos()
input_boxes = mint_dummy_tokens()
create_dummy_boxes(input_boxes, dummy_script)

