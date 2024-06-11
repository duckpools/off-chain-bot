import json
import math

from consts import MIN_BOX_VALUE, TX_FEE, MAX_OPTION_LP_TOKENS
from helpers.job_helpers import op_job_processor, op_latest_pool_info
from helpers.node_calls import tree_to_address, box_id_to_binary, sign_tx, current_height
from helpers.platform_functions import get_CDF_box, get_spot_price, get_volatility, calculate_call_price, get_opDEX_box, \
    calculate_put_price
from helpers.serializer import encode_long_tuple, encode_coll_int
from logger import set_logger

logger = set_logger(__name__)


def process_withdraw_liquidity(pool, box, latest_tx, serialized_r4):
    pool_box = op_latest_pool_info(pool, latest_tx)
    cdf_box = get_CDF_box()
    dex_box = get_opDEX_box()
    S = get_spot_price(dex_box)
    P = 1000000
    σ = get_volatility()
    r = int(pool_box["additionalRegisters"]["R4"]["renderedValue"])
    print(r)
    strikes = json.loads(pool_box["additionalRegisters"]["R5"]["renderedValue"])
    expiry = int(strikes[0])
    K = int(strikes[1])
    Kp = int(strikes[3])
    print(K)
    print(expiry)
    print(strikes)
    t_hint = current_height()
    call_price_response = calculate_call_price(S, σ, r, strikes[1], t_hint, expiry)
    call_price = call_price_response[0]
    put_price_response = calculate_put_price(S, σ, r, Kp, t_hint, expiry)
    put_price = put_price_response[0]
    y = call_price_response[1]
    size = int(strikes[2])
    putSize = int(strikes[4])
    sqrtT = call_price_response[2]
    nd1i = call_price_response[3]
    nd2i = call_price_response[4]
    y_deduction = call_price * size

    y_deduction = call_price * size - putSize
    print(y_deduction)
    current_y_realized = pool_box["assets"][2]["amount"] - y_deduction
    x_deduction = put_price * putSize + size
    print(x_deduction)
    current_x_realized = pool_box["value"] - x_deduction
    print(y_deduction)
    lp_given = box["assets"][0]["amount"]
    print(lp_given)
    # TODO: ADD CHECK THAT LP_GIVEN HAS VALID TOKENID
    held_tokens = int(pool_box["assets"][1]["amount"])
    circulating_tokens = int(MAX_OPTION_LP_TOKENS - held_tokens)
    final_circulating = circulating_tokens - lp_given
    final_x = math.ceil(
        (final_circulating * current_x_realized) / circulating_tokens
    )
    final_y = math.ceil(
        (final_circulating * current_y_realized) / circulating_tokens
    )
    final_x = 60000000
    final_y = 6
    yp = put_price_response[1]
    pnd1i = put_price_response[3]
    pnd2i = put_price_response[4]

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
                            "amount": str(int(MAX_OPTION_LP_TOKENS - final_circulating))
                        },
                        {
                            "tokenId": pool_box["assets"][2]["tokenId"],
                            "amount": final_y
                        },
                        {
                            "tokenId": pool_box["assets"][3]["tokenId"],
                            "amount": pool_box["assets"][3]["amount"]
                        },
                        {
                            "tokenId": pool_box["assets"][4]["tokenId"],
                            "amount": pool_box["assets"][4]["amount"]
                        }
                    ],
                    "registers": {
                        "R4": pool_box["additionalRegisters"]["R4"]["serializedValue"],
                        "R5": pool_box["additionalRegisters"]["R5"]["serializedValue"],
                        "R6": encode_long_tuple([t_hint, y, yp, sqrtT]),
                        "R7": encode_coll_int([nd1i, nd2i, pnd1i, pnd2i])
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
                [box_id_to_binary(dex_box["boxId"]), box_id_to_binary(cdf_box["boxId"])]
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
