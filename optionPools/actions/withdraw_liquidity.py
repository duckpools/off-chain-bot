import json
import math

from consts import MIN_BOX_VALUE, TX_FEE
from helpers.job_helpers import op_job_processor, op_latest_pool_info
from helpers.node_calls import tree_to_address, box_id_to_binary, sign_tx
from logger import set_logger

logger = set_logger(__name__)


def process_withdraw_liquidity(pool, box, latest_tx, serialized_r4):
    pool_box = op_latest_pool_info(pool, latest_tx)

    lp_given = box["assets"][0]["amount"]
    # TODO: ADD CHECK THAT LP_GIVEN HAS VALID TOKENID
    held_tokens = int(pool_box["assets"][1]["amount"])
    circulating_tokens = int(9000000000000010 - held_tokens)
    final_circulating = circulating_tokens - lp_given
    final_x = math.ceil(
        (final_circulating * pool_box["value"]) / circulating_tokens
    )
    final_y = math.ceil(
        (final_circulating * pool_box["assets"][2]["amount"]) / circulating_tokens
    )
    print(final_x / final_circulating)
    print(pool_box["value"] / circulating_tokens)

    print(final_y / final_circulating)
    print(pool_box["assets"][2]["amount"]/ circulating_tokens)

    user_x = pool_box["value"] - final_x
    user_y = pool_box["assets"][2]["amount"] - final_y

    user_tree = box["additionalRegisters"]["R4"]["renderedValue"]

    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": pool["pool"],
                    "value": final_x,
                    "assets": [
                        {
                            "tokenId": pool_box["assets"][0]["tokenId"],
                            "amount": pool_box["assets"][0]["amount"]
                        },
                        {
                            "tokenId": pool_box["assets"][1]["tokenId"],
                            "amount": str(int(9000000000000010 - final_circulating))
                        },
                        {
                            "tokenId": pool_box["assets"][2]["tokenId"],
                            "amount": final_y
                        }
                    ],
                    "registers": {
                        "R4": serialized_r4
                    }
                },
                {
                    "address": tree_to_address(user_tree),
                    "value": MIN_BOX_VALUE + user_x,
                    "assets": [
                        {
                            "tokenId": pool_box["assets"][2]["tokenId"],
                            "amount": user_y
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
            "fee": 2 * TX_FEE,
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


def withdraw_liquidity_job(pool, serialized_r4):
    return op_job_processor(pool, pool["proxy_withdraw"], None, serialized_r4, process_withdraw_liquidity, "withdraw liquidity", 1047423)
