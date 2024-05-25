import json
import math

from consts import MIN_BOX_VALUE, TX_FEE
from helpers.job_helpers import op_job_processor, op_latest_pool_info
from helpers.node_calls import tree_to_address, box_id_to_binary, sign_tx
from logger import set_logger

logger = set_logger(__name__)


def process_add_liquidity(pool, box, latest_tx, serialized_r4):
    pool_box = op_latest_pool_info(pool, latest_tx)

    value_added = box["value"] - MIN_BOX_VALUE - TX_FEE
    tokens_added = box["assets"][0]["amount"]
    held_tokens = int(pool_box["assets"][1]["amount"])
    circulating_tokens = int(9000000000000010 - held_tokens)
    final_circulating_from_x = math.floor(
        (circulating_tokens * (pool_box["value"] + value_added)) / (pool_box["value"]))
    final_circulating_from_y = math.floor(
        (circulating_tokens * (pool_box["assets"][2]["amount"] + tokens_added)) / (pool_box["assets"][2]["amount"]))
    final_circulating = min(final_circulating_from_y, final_circulating_from_x)
    receive_amount = final_circulating - circulating_tokens - 1
    pool_gets = int(held_tokens - receive_amount)
    user_tree = box["additionalRegisters"]["R4"]["renderedValue"]

    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": pool["pool"],
                    "value": pool_box["value"] + value_added,
                    "assets": [
                        {
                            "tokenId": pool_box["assets"][0]["tokenId"],
                            "amount": pool_box["assets"][0]["amount"]
                        },
                        {
                            "tokenId": pool_box["assets"][1]["tokenId"],
                            "amount": pool_gets
                        },
                        {
                            "tokenId": pool_box["assets"][2]["tokenId"],
                            "amount": pool_box["assets"][2]["amount"] + tokens_added
                        }
                    ],
                    "registers": {
                        "R4": serialized_r4
                    }
                },
                {
                    "address": tree_to_address(user_tree),
                    "value": MIN_BOX_VALUE,
                    "assets": [
                        {
                            "tokenId": pool_box["assets"][1]["tokenId"],
                            "amount": receive_amount
                        }
                    ],
                    "registers": {
                        "R4": "0500",
                        "R5": "0400",
                        "R6": "0400",
                        "R7": "0e20" + box["boxId"]
                    }
                }
            ],
            "fee": TX_FEE,
            "inputsRaw":
                [box_id_to_binary(pool_box["boxId"]), box_id_to_binary(box["boxId"])],
            "dataInputsRaw":
                []
        }
    print(transaction_to_sign)
    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)
    obj = {"txId": tx_id}


    if tx_id != -1:
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
                            {
                                "tokenId": box["assets"][0]["tokenId"],
                                "amount": box["assets"][0]["amount"]
                            }
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
        if tx_id != -1:
            logger.info("Successfully submitted refund transaction with ID: %s",  tx_id)
        else:
            logger.warning("Failed to process or refund transaction object: %s Failed Refund txID quoted as: %s",
                           json.dumps(transaction_to_sign), tx_id)

        return latest_tx
    return obj


def add_liquidity_job(pool, serialized_r4):
    return op_job_processor(pool, pool["proxy_lend"], None, serialized_r4, process_add_liquidity, "add liquidity", 1047423)
