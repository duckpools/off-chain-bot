import json
import secrets
import time

import requests

from client_consts import node_address, node_url, headers
from consts import MIN_BOX_VALUE, TX_FEE, LP_TOKENS_MINT_AMOUNT
from helpers.explorer_calls import get_unspent_boxes_by_address
from helpers.node_calls import box_id_to_binary, sign_tx, clean_node, generate_pool_nft_script, \
    generate_lp_tokens_script, generate_y_tokens_script
from helpers.serializer import encode_long
from logger import set_logger
from optionPools.option_consts import option_pools

logger = set_logger(__name__)


def mint_tokens(pool_nft_script, lp_tokens_script, y_tokens_script, y_token_id):
    id = secrets.token_hex(16)
    transaction_to_sign = \
        {
            "requests": [
                {
                  "address": pool_nft_script,
                  "ergValue": 2000000,
                  "amount": 1,
                  "name": "Pool NFT",
                  "description": "Used to identify Pool: " + id,
                  "decimals": 0,
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
    sign_tx(transaction_to_sign)

    transaction_to_sign = \
        {
            "requests": [
                {
                  "address": lp_tokens_script,
                  "ergValue": 2000000,
                  "amount": LP_TOKENS_MINT_AMOUNT,
                  "name": "LP Tokens",
                  "description": "Used for LP",
                  "decimals": 9,
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
    sign_tx(transaction_to_sign)
    # Consider me properly
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": y_tokens_script,
                    "value": 2000000,
                    "assets": [
                        {
                            "tokenId": y_token_id,
                            "amount": 10
                        }
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
    sign_tx(transaction_to_sign)

# Check no active mint attempts
# Mint tokens (3) to the user's collection address (generate it - 1 for each token)
# Wait for confirmation
# Submit market creation
# Submit collection creation

def count_mint_active(pool_nft_script, lp_tokens_script, y_tokens_script):
    boxes = []
    boxes.append(get_unspent_boxes_by_address(pool_nft_script))
    boxes.append(get_unspent_boxes_by_address(lp_tokens_script))
    boxes.append(get_unspent_boxes_by_address(y_tokens_script))
    count = 0
    for resp in boxes:
        if len(resp) != 0:
            count += 1
    return count

def cancel_active_creations(pool_nft_script, lp_tokens_script, y_tokens_script, y_token):
    allboxes = []
    allboxes.append(get_unspent_boxes_by_address(pool_nft_script))
    allboxes.append(get_unspent_boxes_by_address(lp_tokens_script))
    allboxes.append(get_unspent_boxes_by_address(y_tokens_script))
    logger.info("Getting UTXO Binaries")
    binaries = []
    tokens = []
    tokens_to_keep = []
    for boxes in allboxes:
        for box in boxes:
            binaries.append(box_id_to_binary(box["boxId"]))
            if box["assets"] and box["assets"][0]["tokenId"] != y_token:
                tokens.append(
                    {
                        "tokenId": box["assets"][0]["tokenId"],
                        "amount": box["assets"][0]["amount"]
                    }
                )
            elif box["assets"] and box["assets"][0]["tokenId"] == y_token:
                tokens.append(
                    {
                        "tokenId": box["assets"][0]["tokenId"],
                        "amount": box["assets"][0]["amount"]
                    }
                )
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": node_address,
                    "value": 2000000 * len(binaries) - 1000000,
                    "assets": tokens_to_keep,
                    "registers": {
                    }
                },
                {
                    "assetsToBurn": tokens
                }
            ],
            "fee": 1000000,
            "inputsRaw":
                binaries,
            "dataInputsRaw":
                []
        }
    sign_tx(transaction_to_sign)
    logger.info("Waiting for transactions to confirm, please do not terminate the program...")
    start_time = time.time()
    while count_mint_active(pool_nft_script, lp_tokens_script, y_tokens_script) > 0:
        time.sleep(45)
        if (time.time() - start_time) > 900:
            logger.error("Waited 900 seconds, assumed failure, terminating bot.")
            clean_node()
            return False
        logger.info("Still waiting for transactions to confirm, please do not terminate the program...")
    return True


def create_pool(r4_value, stage):
    y_token = "1368440201d3a950c9900bb9f4138223e5ee77f598f36a425ca665a886bb2c48"
    pool_nft_script = generate_pool_nft_script(node_address)
    lp_token_script = generate_lp_tokens_script(node_address)
    y_token_script = generate_y_tokens_script(node_address)
    if stage <= 1:
        logger.info("Checking if there are active create pool attempts...")
        if count_mint_active(pool_nft_script, lp_token_script, y_token_script) > 0:
            logger.warning("There is already an attempt to create pool, attempting to cancel...")
            if cancel_active_creations(pool_nft_script, lp_token_script, y_token_script, y_token):
                create_pool()
            return
        logger.info("No active market creations found, attempting to mint pool tokens")
        mint_tokens(pool_nft_script, lp_token_script, y_token_script, y_token)
        logger.info("Waiting for transactions to confirm, please do not terminate the program...")
        start_time = time.time()
    while count_mint_active(pool_nft_script, lp_token_script, y_token_script) < 3:
        time.sleep(45)
        if (time.time() - start_time) > 900:
            clean_node()
            logger.error("Waited 900 seconds, assumed failure, terminating bot.")
            return
        logger.info("Still waiting for transactions to confirm, please do not terminate the program...")


    pool_nft_box = get_unspent_boxes_by_address(pool_nft_script)[0]
    time.sleep(3)
    lp_token_box = get_unspent_boxes_by_address(lp_token_script)[0]
    time.sleep(3)
    y_token_box = get_unspent_boxes_by_address(y_token_script)[0]
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": option_pools[0]["pool"],
                    "value": MIN_BOX_VALUE,
                    "assets": [
                        {
                            "tokenId": pool_nft_box["assets"][0]["tokenId"],
                            "amount": "1"
                        },
                        {
                            "tokenId": lp_token_box["assets"][0]["tokenId"],
                            "amount": LP_TOKENS_MINT_AMOUNT
                        },
                        {
                            "tokenId": y_token,
                            "amount": 10
                        }
                    ],
                    "registers": {
                        "R4": encode_long(r4_value)
                    }
                }
            ],
            "fee": TX_FEE,
            "inputsRaw":
                [box_id_to_binary(pool_nft_box["boxId"]), box_id_to_binary(lp_token_box["boxId"]), box_id_to_binary(y_token_box["boxId"])],
            "dataInputsRaw":
                []
        }
    sign_tx(transaction_to_sign)
