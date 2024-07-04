import json
import math

from consts import MIN_BOX_VALUE, TX_FEE, BorrowTokenDenomination
from helpers.job_helpers import latest_pool_info, job_processor
from helpers.node_calls import tree_to_address, box_id_to_binary, sign_tx
from helpers.platform_functions import calculate_final_amount, get_pool_param_box, get_interest_box
from helpers.serializer import extract_number
from logger import set_logger

logger = set_logger(__name__)


def process_lend_proxy_box(pool, box, latest_tx):
    if box["assets"][0]["tokenId"] != pool["CURRENCY_ID"]:
        return latest_tx
    pool_box, borrowedTokens = latest_pool_info(pool, latest_tx)
    interest_box = get_interest_box(pool["interest"], pool["INTEREST_NFT"])
    borrowTokenValue = extract_number(interest_box["additionalRegisters"]["R5"]["renderedValue"])
    borrowed = borrowedTokens * borrowTokenValue / BorrowTokenDenomination

    token_amount = box["assets"][0]["amount"]
    service_fee = max(calculate_final_amount(token_amount, pool["thresholds"]), 1)
    assets_to_give = token_amount - service_fee
    held_tokens = int(pool_box["assets"][1]["amount"])
    circulating_tokens = int(9000000000000010 - held_tokens)
    param_box = get_pool_param_box(pool["parameter"], pool["PARAMETER_NFT"])
    final_circulating = math.floor(
        (circulating_tokens * (pool_box["assets"][3]["amount"] + assets_to_give + borrowed)) / (pool_box["assets"][3]["amount"] + borrowed))
    receive_amount = final_circulating - circulating_tokens
    pool_gets = int(held_tokens - receive_amount)
    user_tree = box["additionalRegisters"]["R4"]["renderedValue"]

    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": pool["pool"],
                    "value": pool_box["value"],
                    "assets": [
                        {
                            "tokenId": pool_box["assets"][0]["tokenId"],
                            "amount": pool_box["assets"][0]["amount"]
                        },
                        {
                            "tokenId": pool_box["assets"][1]["tokenId"],
                            "amount": pool_gets + 1
                        },
                        {
                            "tokenId": pool_box["assets"][2]["tokenId"],
                            "amount": pool_box["assets"][2]["amount"]
                        },
                        {
                            "tokenId": pool_box["assets"][3]["tokenId"],
                            "amount": pool_box["assets"][3]["amount"] + assets_to_give
                        }
                    ],
                    "registers": {
                    }
                },
                {
                    "address": tree_to_address(param_box["additionalRegisters"]["R8"]["renderedValue"]),
                    "value": MIN_BOX_VALUE,
                    "assets": [
                        {
                            "tokenId": pool_box["assets"][3]["tokenId"],
                            "amount": service_fee
                        }
                    ],
                    "registers": {
                    }
                },
                {
                    "address": tree_to_address(user_tree),
                    "value": MIN_BOX_VALUE,
                    "assets": [
                        {
                            "tokenId": pool_box["assets"][1]["tokenId"],
                            "amount": receive_amount - 1
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
                [box_id_to_binary(interest_box["boxId"]), box_id_to_binary(param_box["boxId"])]
        }

    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)
    obj = {"txId": tx_id,
           "finalBorrowed": borrowed}

    print(transaction_to_sign)
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


def t_lend_proxy_job(pool):
    return job_processor(pool, pool["proxy_lend"], None, process_lend_proxy_box, "lend", 1047423)
