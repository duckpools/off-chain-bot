import json
from math import floor

from consts import MIN_BOX_VALUE, TX_FEE, NULL_TX_OBJ, ERROR, LargeMultiplier
from helpers.explorer_calls import get_box_from_id_explorer
from helpers.job_helpers import job_processor
from helpers.node_calls import box_id_to_binary, sign_tx, tree_to_address
from helpers.platform_functions import get_interest_box, get_dex_box, get_logic_box
from helpers.serializer import encode_long_tuple
from logger import set_logger

logger = set_logger(__name__)


def refund_repay_proxy_box(box):
    transaction_to_sign = \
    {
        "requests": [
            {
                "address": tree_to_address(box["additionalRegisters"]["R6"]["renderedValue"]),
                "value": box["value"] - TX_FEE,
                "assets": [
                    {
                        "tokenId": box["assets"][0]["tokenId"],
                        "amount": box["assets"][0]["amount"]
                    }
                ],
                "registers": {
                }
            }
        ],
        "fee": TX_FEE,
        "inputsRaw":
            [box_id_to_binary(box["boxId"])],
        "dataInputsRaw":
            []
    }

    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)
    if tx_id != ERROR:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    else:
        logger.info("Failed to submit transaction, attempting to refund")
    return


def process_repay_partial_proxy_box(pool, box, empty):
    if len(box["assets"]) == 0 or box["assets"][0]["tokenId"] != pool["CURRENCY_ID"]:
        return

    collateral_box = box["additionalRegisters"]["R4"]["renderedValue"]
    final_borrow_tokens = int(box["additionalRegisters"]["R5"]["renderedValue"])
    whole_collateral_box = get_box_from_id_explorer(collateral_box)
    logger.debug("Whole collateral box: ", whole_collateral_box)
    if not whole_collateral_box or whole_collateral_box["spentTransactionId"] is not None:
        refund_repay_proxy_box(box)
        return

    interest_box = get_interest_box(pool["interest"], pool["INTEREST_NFT"])
    dex_nft = pool["logic_settings"][0]["dex_nft"]
    dex_box = get_dex_box(dex_nft)
    logic_box = get_logic_box(pool["logic_settings"][0]["address"], pool["logic_settings"][0]["nft"])
    iReport = json.loads(logic_box["additionalRegisters"]["R4"]["renderedValue"])


    dex_initial_val = dex_box["value"]
    dex_tokens = dex_box["assets"][2]["amount"]
    tokens_to_liquidate = int(whole_collateral_box["value"]) - 5000000
    dex_fee = pool["logic_settings"][0]["dex_fee"]
    liquidation_value = floor((dex_tokens * tokens_to_liquidate * dex_fee) /
                              ((dex_initial_val + floor((dex_initial_val * 2 / 100))) * 1000 +
                               (tokens_to_liquidate * dex_fee)))
    aggregateThreshold = floor(floor(whole_collateral_box["value"] * LargeMultiplier * 1400 / tokens_to_liquidate) / LargeMultiplier)

    if not interest_box:
        logger.debug("No Interest Box Found")
        return

    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": whole_collateral_box["address"],
                    "value": whole_collateral_box["value"],
                    "assets": [
                        {
                            "tokenId": whole_collateral_box["assets"][0]["tokenId"],
                            "amount": final_borrow_tokens
                        }
                    ],
                    "registers": {
                        "R4": whole_collateral_box["additionalRegisters"]["R4"]["serializedValue"],
                        "R5": whole_collateral_box["additionalRegisters"]["R5"]["serializedValue"],
                        "R6": whole_collateral_box["additionalRegisters"]["R6"]["serializedValue"],
                        "R7": whole_collateral_box["additionalRegisters"]["R7"]["serializedValue"],
                        "R8": whole_collateral_box["additionalRegisters"]["R8"]["serializedValue"],
                        "R9": whole_collateral_box["additionalRegisters"]["R9"]["serializedValue"]
                    }
                },
                {
                    "address": pool["repayment"],
                    "value": MIN_BOX_VALUE + TX_FEE,
                    "assets": [
                        {
                            "tokenId": whole_collateral_box["assets"][0]["tokenId"],
                            "amount": int(whole_collateral_box["assets"][0]["amount"]) - final_borrow_tokens
                        },
                        {
                            "tokenId": box["assets"][0]["tokenId"],
                            "amount": box["assets"][0]["amount"]
                        }
                    ],
                    "registers": {
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
                        "R4": encode_long_tuple([iReport[0], liquidation_value, aggregateThreshold, iReport[3], iReport[4], iReport[5]]),
                        "R5": logic_box["additionalRegisters"]["R5"]["serializedValue"],
                        "R6": logic_box["additionalRegisters"]["R6"]["serializedValue"],
                        "R7": "1100",
                        "R8": "1a00",
                        "R9": "10020202"
                    }
                }
            ],
            "fee": TX_FEE,
            "inputsRaw":
                [box_id_to_binary(box["boxId"]), box_id_to_binary(collateral_box), box_id_to_binary(logic_box["boxId"])],
            "dataInputsRaw":
                [box_id_to_binary(interest_box["boxId"]), box_id_to_binary(dex_box["boxId"])]
        }

    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)
    if tx_id != ERROR:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    else:
        logger.info("Failed to submit transaction, attempting to refund")
        refund_repay_proxy_box(box)
    return


def t_partial_repay_proxy_job(pool):
    job_processor(pool, pool["proxy_partial_repay"], NULL_TX_OBJ, process_repay_partial_proxy_box, "PARTIAL REPAYMENT", 1071199)
