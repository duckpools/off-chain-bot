import json
import math

from consts import MIN_BOX_VALUE, TX_FEE, MAX_LP_TOKENS, ERROR, node_address
from helpers.job_helpers import job_processor, latest_pool_info
from helpers.node_calls import tree_to_address, box_id_to_binary, sign_tx
from helpers.platform_functions import calculate_final_amount, get_pool_param_box
from logger import set_logger

logger = set_logger(__name__)


def process_lend_proxy_box(pool, box, latest_tx):
    erg_pool_box, borrowed = latest_pool_info(pool, latest_tx)

    usable_value = box["value"] - MIN_BOX_VALUE - TX_FEE - MIN_BOX_VALUE
    service_fee = max(calculate_final_amount(usable_value, pool["thresholds"]), MIN_BOX_VALUE)
    erg_to_give = usable_value - service_fee
    held_tokens = int(erg_pool_box["assets"][1]["amount"])
    circulating_tokens = int(MAX_LP_TOKENS - held_tokens)
    param_box = get_pool_param_box(pool["parameter"], pool["PARAMETER_NFT"])
    final_circulating = math.floor(
        (circulating_tokens * (erg_pool_box["value"] + erg_to_give + borrowed)) / (erg_pool_box["value"] + borrowed))
    receive_amount = final_circulating - circulating_tokens
    pool_gets = int(held_tokens - receive_amount)
    user_tree = box["additionalRegisters"]["R4"]["renderedValue"]
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": pool["pool"],
                    "value": erg_pool_box["value"] + erg_to_give,
                    "assets": [
                        {
                            "tokenId": erg_pool_box["assets"][0]["tokenId"],
                            "amount": erg_pool_box["assets"][0]["amount"]
                        },
                        {
                            "tokenId": erg_pool_box["assets"][1]["tokenId"],
                            "amount": pool_gets + 1
                        },
                        {
                            "tokenId": erg_pool_box["assets"][2]["tokenId"],
                            "amount": erg_pool_box["assets"][2]["amount"]
                        }
                    ],
                    "registers": {
                    }
                },
                {
                    "address": tree_to_address(param_box["additionalRegisters"]["R8"]["renderedValue"]),
                    "value": service_fee,
                    "assets": [
                    ],
                    "registers": {
                    }
                },
                {
                    "address": tree_to_address(user_tree),
                    "value": MIN_BOX_VALUE,
                    "assets": [
                        {
                            "tokenId": erg_pool_box["assets"][1]["tokenId"],
                            "amount": receive_amount - 1
                        }
                    ],
                    "registers": {
                        "R4": "0500",
                        "R5": "0400",
                        "R6": "0400",
                        "R7": "0e20" + box["boxId"]
                    }
                },
                {
                    "address": node_address,
                    "value": MIN_BOX_VALUE,
                    "assets": [
                    ],
                    "registers": {
                    }
                }
            ],
            "fee": TX_FEE,
            "inputsRaw":
                [box_id_to_binary(erg_pool_box["boxId"]), box_id_to_binary(box["boxId"])],
            "dataInputsRaw":
                [box_id_to_binary(param_box["boxId"])]
        }

    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)
    obj = {"txId": tx_id,
           "finalBorrowed": borrowed}


    if tx_id != -1 and tx_id != 1409:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    else:
        logger.debug("Failed to submit transaction, attempting to refund")
        transaction_to_sign = \
            {
                "requests": [
                    {
                        "address": tree_to_address(user_tree),
                        "value": box["value"] - TX_FEE,
                        "assets": [
                        ],
                        "registers": {
                            "R4": "0e20" + box["boxId"]
                        }
                    }
                ],
                "fee": TX_FEE,
                "inputsRaw":
                    [box_id_to_binary(box["boxId"])],
                "dataInputsRaw":
                    []
            }

        logger.debug("Signing Transaction: %s",  json.dumps(transaction_to_sign))
        tx_id = sign_tx(transaction_to_sign)
        if tx_id != ERROR:
            logger.info("Successfully submitted refund transaction with ID: %s",  tx_id)
        else:
            logger.warning("Failed to process or refund transaction object: %s Failed Refund txID quoted as: %s",
                           json.dumps(transaction_to_sign), tx_id)

        return latest_tx
    return obj


def e_lend_proxy_job(pool):
    return job_processor(pool, pool["proxy_lend"], None, process_lend_proxy_box, "lend", 1047423)
