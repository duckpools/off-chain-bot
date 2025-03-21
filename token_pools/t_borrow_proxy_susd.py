import json
from math import floor

from consts import TX_FEE, MIN_BOX_VALUE, MAX_BORROW_TOKENS, DOUBLE_SPENDING_ATTEMPT, ERROR, LargeMultiplier
from helpers.job_helpers import latest_pool_info, job_processor
from helpers.node_calls import tree_to_address, box_id_to_binary, sign_tx, current_height
from helpers.platform_functions import get_dex_box, get_pool_param_box, get_interest_box, get_logic_box
from helpers.serializer import encode_long, encode_long_tuple
from logger import set_logger

logger = set_logger(__name__)


def process_borrow_proxy_box(pool, box, latest_tx, fee=TX_FEE):
    pool_box, borrowedTokens = latest_pool_info(pool, latest_tx)
    collateral_supplied = box["value"] - MIN_BOX_VALUE - TX_FEE
    dex_box = get_dex_box(pool["logic_settings"][0]["dex_nft"])
    interest_box = get_interest_box(pool["interest"], pool["INTEREST_NFT"])
    request_amounts = json.loads(box["additionalRegisters"]["R7"]["renderedValue"])
    amount_to_borrow = request_amounts[0]
    loanBorrowTokens = request_amounts[1]

    print(amount_to_borrow)
    print(loanBorrowTokens)


    user_tree = box["additionalRegisters"]["R4"]["renderedValue"]
    final_borrowed = borrowedTokens + loanBorrowTokens
    pool_param_box = get_pool_param_box(pool["parameter"], pool["PARAMETER_NFT"])
    logic_box = get_logic_box(pool["logic_settings"][0]["address"], pool["logic_settings"][0]["nft"])
    net_height = current_height() - 20

    dex_initial_val = dex_box["value"]
    dex_tokens = dex_box["assets"][2]["amount"]
    tokens_to_liquidate =collateral_supplied - 5000000
    dex_fee = pool["logic_settings"][0]["dex_fee"]
    liquidation_value = floor((dex_tokens * tokens_to_liquidate * dex_fee) /
                              ((dex_initial_val + floor((dex_initial_val * 2 / 100))) * 1000 +
                               (tokens_to_liquidate * dex_fee)))

    aggregateThreshold = floor(floor(collateral_supplied * LargeMultiplier * 1400 / tokens_to_liquidate) / LargeMultiplier)
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
                            "amount": pool_box["assets"][1]["amount"]
                        },
                        {
                            "tokenId": pool_box["assets"][2]["tokenId"],
                            "amount": MAX_BORROW_TOKENS - final_borrowed
                        },
                        {
                            "tokenId": pool_box["assets"][3]["tokenId"],
                            "amount": pool_box["assets"][3]["amount"] - amount_to_borrow
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
                    "address": pool["collateral"],
                    "value": collateral_supplied,
                    "assets": [
                        {
                            "tokenId": pool_box["assets"][2]["tokenId"],
                            "amount": loanBorrowTokens
                        }
                    ],
                    "registers": {
                        "R4": box["additionalRegisters"]["R4"]["serializedValue"],
                        "R5": box["additionalRegisters"]["R5"]["serializedValue"],
                        "R6": encode_long(100000000),
                        "R7": box["additionalRegisters"]["R8"]["serializedValue"],
                        "R8": box["additionalRegisters"]["R9"]["serializedValue"]
                    }
                },
                {
                    "address": tree_to_address(user_tree),
                    "value": MIN_BOX_VALUE - fee + TX_FEE,
                    "assets": [
                        {
                            "tokenId": pool_box["assets"][3]["tokenId"],
                            "amount": amount_to_borrow
                        }
                    ],
                    "registers": {
                        "R4": "0e20" + box["boxId"]
                    }
                },
                {
                    "address": pool["logic_settings"][0]["address"],
                    "value": MIN_BOX_VALUE,
                    "assets": [
                        {
                            "tokenId": logic_box["assets"][0]["tokenId"],
                            "amount": 1
                        }
                    ],
                    "registers": {
                        "R4": encode_long_tuple([1000000000000000, liquidation_value, aggregateThreshold, 30]),
                        "R5": logic_box["additionalRegisters"]["R5"]["serializedValue"],
                        "R6": logic_box["additionalRegisters"]["R6"]["serializedValue"],
                        "R7": "1100",
                        "R8": "1a00",
                        "R9": "10020404"
                    }
                }
            ],
            "fee": fee,
            "inputsRaw":
                [box_id_to_binary(pool_box["boxId"]), box_id_to_binary(box["boxId"]), box_id_to_binary(logic_box["boxId"])],
            "dataInputsRaw":
                [box_id_to_binary(interest_box["boxId"]), box_id_to_binary(pool_param_box["boxId"]), box_id_to_binary(dex_box["boxId"])]
        }
    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)

    obj = {"txId": tx_id,
           "finalBorrowed": final_borrowed}
    if tx_id != ERROR and tx_id != DOUBLE_SPENDING_ATTEMPT:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    elif tx_id == DOUBLE_SPENDING_ATTEMPT:
        logger.info("Double spend, trying with fee: %s", str(fee + 12))
        process_borrow_proxy_box(pool, box, latest_tx, fee + 12)
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
                    [box_id_to_binary(dex_box["boxId"])]
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


def t_borrow_proxy_job(pool, curr_tx_obj):
    return job_processor(pool, pool["proxy_borrow"], curr_tx_obj, process_borrow_proxy_box, "borrow", 1459925)
