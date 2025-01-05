import json
from math import ceil

from consts import MIN_BOX_VALUE, TX_FEE, BorrowTokenDenomination
from helpers.job_helpers import latest_pool_info, job_processor
from helpers.node_calls import tree_to_address, box_id_to_binary, sign_tx
from helpers.platform_functions import calculate_service_fee, get_pool_param_box, get_interest_box
from helpers.serializer import extract_number
from logger import set_logger

logger = set_logger(__name__)


def process_withdraw_proxy_box(pool, box, latest_tx):
    if len(box["assets"]) == 0 or box["assets"][0]["tokenId"] != pool["LEND_TOKEN"]:
        return latest_tx
    pool_box, borrowedTokens = latest_pool_info(pool, latest_tx)
    interest_box = get_interest_box(pool["interest"], pool["INTEREST_NFT"])
    borrowTokenValue = extract_number(interest_box["additionalRegisters"]["R5"]["renderedValue"])
    borrowed = borrowedTokens * borrowTokenValue / BorrowTokenDenomination

    held_erg0 = pool_box["assets"][3]["amount"]
    held_tokens = int(pool_box["assets"][1]["amount"])
    user_gives = box["assets"][0]["amount"]
    circulating_tokens = int(9000000000000010 - held_tokens)
    final_circulating = circulating_tokens - user_gives
    held_erg1 = ceil(final_circulating * (held_erg0 + borrowed) / circulating_tokens - borrowed) + 1
    total_entitled = held_erg0 - held_erg1
    service_fee = max(ceil(calculate_service_fee(total_entitled, pool["thresholds"])), 1)
    user_gets = total_entitled - service_fee
    user_tree = box["additionalRegisters"]["R4"]["renderedValue"]
    param_box = get_pool_param_box(pool["parameter"], pool["PARAMETER_NFT"])
    print(user_gets)

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
                            "amount": str(pool_box["assets"][1]["amount"] + user_gives)
                        },
                        {
                            "tokenId": pool_box["assets"][2]["tokenId"],
                            "amount": str(pool_box["assets"][2]["amount"])
                        },
                        {
                            "tokenId": pool_box["assets"][3]["tokenId"],
                            "amount": pool_box["assets"][3]["amount"] - total_entitled
                        },
                    ],
                    "registers": {
                        "R4": "0101",
                        "R5": "0101",
                        "R6": "0101",
                        "R7": "0101",
                        "R8": "0101",
                        "R9": "0101"
                    }
                },
                {
                    "address": tree_to_address(param_box["additionalRegisters"]["R5"]["renderedValue"]),
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
                            "tokenId": pool_box["assets"][3]["tokenId"],
                            "amount": user_gets
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
    if tx_id != -1:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    else:
        dssd
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


def t_withdraw_proxy_job(pool, curr_tx_obj):
    return job_processor(pool, pool["proxy_withdraw"], curr_tx_obj, process_withdraw_proxy_box, "withdrawal", 1047423)
