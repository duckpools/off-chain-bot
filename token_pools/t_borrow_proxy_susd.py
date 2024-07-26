import json

from consts import TX_FEE, MIN_BOX_VALUE, MAX_BORROW_TOKENS, DOUBLE_SPENDING_ATTEMPT, ERROR, DEFAULT_BUFFER, \
    BorrowTokenDenomination
from helpers.job_helpers import latest_pool_info, job_processor
from helpers.node_calls import tree_to_address, box_id_to_binary, sign_tx, current_height
from helpers.platform_functions import get_dex_box, get_pool_param_box, get_interest_box, get_logic_box
from helpers.serializer import encode_int_tuple, encode_long, encode_long_pair, extract_number, encode_long_tuple
from logger import set_logger
from math import floor

logger = set_logger(__name__)


def process_borrow_proxy_box(pool, box, latest_tx, fee=TX_FEE):
    pool_box, borrowedTokens = latest_pool_info(pool, latest_tx)
    collateral_supplied = box["value"] - MIN_BOX_VALUE - TX_FEE
    dex_box = get_dex_box(pool["collateral_supported"]["erg"]["dex_nft"])
    interest_box = get_interest_box(pool["interest"], pool["INTEREST_NFT"])
    request_amounts = json.loads(box["additionalRegisters"]["R5"]["renderedValue"])
    amount_to_borrow = request_amounts[0]
    loanBorrowTokens = request_amounts[1]

    print(amount_to_borrow)
    print(loanBorrowTokens)


    user_tree = box["additionalRegisters"]["R4"]["renderedValue"]
    final_borrowed = borrowedTokens + loanBorrowTokens
    pool_param_box = get_pool_param_box(pool["parameter"], pool["PARAMETER_NFT"])
    logic_box = get_logic_box(pool["logic"], pool["LOGIC_NFT"])
    net_height = current_height() - 20

    dex_initial_val = dex_box["value"]
    dex_tokens = dex_box["assets"][2]["amount"]
    tokens_to_liquidate =collateral_supplied - 5000000
    dex_fee = pool["collateral_supported"]["erg"]["dex_fee"]
    liquidation_value = floor((dex_tokens * tokens_to_liquidate * dex_fee) /
                              ((dex_initial_val + floor((dex_initial_val * 2 / 100))) * 1000 +
                               (tokens_to_liquidate * dex_fee)))

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
                        "R5": box["additionalRegisters"]["R9"]["serializedValue"],
                        "R6": encode_long_tuple([2000, 200000, 1400, 300]),
                        "R7": box["additionalRegisters"]["R8"]["serializedValue"]
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
                    "address": pool["logic"],
                    "value": MIN_BOX_VALUE,
                    "assets": [
                        {
                            "tokenId": logic_box["assets"][0]["tokenId"],
                            "amount": 1
                        }
                    ],
                    "registers": {
                        "R4": encode_long(liquidation_value),
                        "R5": "0402",
                        "R6": "0101"
                    }
                }
            ],
            "fee": fee,
            "inputsRaw":
                [box_id_to_binary(pool_box["boxId"]), box_id_to_binary(box["boxId"]), box_id_to_binary(logic_box["boxId"])],
            "dataInputsRaw":
                [box_id_to_binary(interest_box["boxId"]), box_id_to_binary(dex_box["boxId"]), box_id_to_binary(pool_param_box["boxId"])]
        }

    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)

    obj = {"txId": tx_id,
           "finalBorrowed": final_borrowed}
    dsdsd
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
                    [box_id_to_binary(dex_box["boxId"]), box_id_to_binary(head_child_interest_box["boxId"])]
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
    return job_processor(pool, pool["proxy_borrow"], curr_tx_obj, process_borrow_proxy_box, "borrow", 920000)
