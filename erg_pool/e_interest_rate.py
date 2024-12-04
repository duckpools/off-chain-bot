import json
from math import floor
from secrets import randbelow

from client_consts import node_address
from consts import INTEREST_MULTIPLIER, MIN_BOX_VALUE, MAX_TX_FEE, MAX_CHILD_EXECUTION_FEE, MAX_INTEREST_SIZE, \
    INTEREST_FREQUENCY_POLL, MAX_BORROW_TOKENS, TX_FEE, ERROR, DOUBLE_SPENDING_ATTEMPT
from helpers.explorer_calls import get_dummy_box
from helpers.node_calls import box_id_to_binary, sign_tx
from helpers.platform_functions import get_parent_box, get_head_child, get_pool_box, get_pool_box_from_tx, \
    get_interest_param_box
from helpers.serializer import encode_long_tuple, encode_int, encode_long
from logger import set_logger

logger = set_logger(__name__)


def create_new_child(head_child, pool):
    parent_box = get_parent_box(pool["parent"], pool["PARENT_NFT"])
    parent_history = json.loads(parent_box["additionalRegisters"]["R4"]["renderedValue"])
    child_history = json.loads(head_child["additionalRegisters"]["R4"]["renderedValue"])
    cumulative_rate = INTEREST_MULTIPLIER
    for entry in child_history:
        cumulative_rate = floor(floor(cumulative_rate * entry) / INTEREST_MULTIPLIER)
    parent_history.append(cumulative_rate)
    new_interest_history = parent_history
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": pool["parent"],
                    "value": int(parent_box["value"]) - MIN_BOX_VALUE - MAX_TX_FEE - (MAX_CHILD_EXECUTION_FEE * MAX_INTEREST_SIZE),
                    "assets": [
                        {
                            "tokenId": parent_box["assets"][0]["tokenId"],
                            "amount": parent_box["assets"][0]["amount"]
                        },
                        {
                            "tokenId": parent_box["assets"][1]["tokenId"],
                            "amount": int(parent_box["assets"][1]["amount"]) - 1
                        }
                    ],
                    "registers": {
                        "R4": encode_long_tuple(new_interest_history),
                        "R5": "0101",
                        "R6": "0101",
                        "R7": "0101",
                        "R8": "0101",
                        "R9": "0101"
                    }
                },
                {
                    "address": pool["child"],
                    "value": MAX_CHILD_EXECUTION_FEE * MAX_INTEREST_SIZE,
                    "assets": [
                        {
                            "tokenId": parent_box["assets"][1]["tokenId"],
                            "amount": 1
                        }
                    ],
                    "registers": {
                        "R4": "11018084af5f",
                        "R5": head_child["additionalRegisters"]["R5"]["serializedValue"],
                        "R6": encode_int(len(new_interest_history)),
                        "R7": "0101",
                        "R8": "0101",
                        "R9": "0101"
                    }
                },
            ],
            "fee": MAX_TX_FEE,
            "inputsRaw":
                [box_id_to_binary(parent_box["boxId"])],
            "dataInputsRaw":
                [box_id_to_binary(head_child["boxId"])]
        }
    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)
    if tx_id != -1:
        logger.info("Successfully submitted interest transaction with ID: %s", tx_id)
    else:
        logger.warning(
            "Failed to submit transaction: %s Failed txID quoted as: %s",
            json.dumps(transaction_to_sign), tx_id)
    return


def e_update_interest_rate(pool, curr_height, latest_tx, dummy_script, fee=randbelow(1300001 - 1100000) + 1100000):
    dummy_box = get_dummy_box(dummy_script)
    logger.info("Starting Interest Rate Job")
    box = get_head_child(pool["child"], pool["CHILD_NFT"], pool["parent"], pool["PARENT_NFT"])
    box_curr_height = int(box["additionalRegisters"]["R5"]["renderedValue"])
    if len(json.loads(box["additionalRegisters"]["R4"]["renderedValue"])) == MAX_INTEREST_SIZE:
        create_new_child(box, pool)
    elif box_curr_height + INTEREST_FREQUENCY_POLL < curr_height:
        if box_curr_height + INTEREST_FREQUENCY_POLL + 70 < curr_height:
            fee += 90000
        elif box_curr_height + INTEREST_FREQUENCY_POLL + 35 < curr_height:
            fee += 60000
        elif box_curr_height + INTEREST_FREQUENCY_POLL + 20 < curr_height:
            fee += 10000
        if latest_tx is None:
            erg_pool_box = get_pool_box(pool["pool"], pool["POOL_NFT"])
            borrowed = MAX_BORROW_TOKENS - int(erg_pool_box["assets"][2]["amount"])
        else:
            erg_pool_box = get_pool_box_from_tx(latest_tx["txId"])
            borrowed = latest_tx["finalBorrowed"]

        interest_param_box = get_interest_param_box(pool["interest_parameter"], pool["INTEREST_PARAMETER_NFT"])
        coefficients = json.loads(interest_param_box["additionalRegisters"]["R4"]["renderedValue"])
        a = coefficients[0]
        b = coefficients[1]
        c = coefficients[2]
        d = coefficients[3]
        e = coefficients[4]
        f = coefficients[5]

        real_value = erg_pool_box["value"]
        util = floor(INTEREST_MULTIPLIER * borrowed / (real_value + borrowed))
        x = util
        M = INTEREST_MULTIPLIER
        D = 100000000
        current_rate = floor(
            M + (
              a +
              floor(floor(b * x) / D) +
              floor(floor(floor(floor(c * x) / D) * x) / M) +
              floor(floor(floor(floor(floor(floor(d * x) / D) * x) / M) * x) / M) +
              floor(floor(floor(floor(floor(floor(floor(floor(e * x) / D) * x) / M) * x) / M) * x) / M) +
              floor(floor(floor(floor(floor(floor(floor(floor(floor(floor(f * x) / D) * x) / M) * x) / M) * x) / M) * x) / M)
              )
        )
        interest_history = json.loads(box["additionalRegisters"]["R4"]["renderedValue"])
        interest_history.append(current_rate)

        transaction_to_sign = \
            {
                "requests": [
                    {
                        "address": pool["child"],
                        "value": box["value"] - TX_FEE * 1.9,
                        "assets": [
                            {
                            "tokenId": box["assets"][0]["tokenId"],
                            "amount": box["assets"][0]["amount"]
                            }
                        ],
                        "registers": {
                            "R4": encode_long_tuple(interest_history),
                            "R5": encode_long(curr_height + 5),
                            "R6": box["additionalRegisters"]["R6"]["serializedValue"],
                            "R7": "0101",
                            "R8": "0101",
                            "R9": "0101"
                        }
                    },
                    {
                        "address": node_address,
                        "value":  1.9 * TX_FEE - fee,
                        "assets": [
                        ],
                        "registers": {
                        }
                    },
                    {
                        "address": dummy_box["address"],
                        "value": MIN_BOX_VALUE,
                        "assets": [
                            {
                                "tokenId": dummy_box["assets"][0]["tokenId"],
                                "amount": dummy_box["assets"][0]["amount"]
                            },
                            {
                                "tokenId": dummy_box["assets"][1]["tokenId"],
                                "amount": dummy_box["assets"][1]["amount"]
                            }
                        ],
                        "registers": {
                        }
                    }
                ],
                "fee": fee,
                "inputsRaw":
                    [box_id_to_binary(box["boxId"]), box_id_to_binary(dummy_box["boxId"])],
                "dataInputsRaw":
                    [box_id_to_binary(erg_pool_box["boxId"]), box_id_to_binary(interest_param_box["boxId"])]
            }
        logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
        tx_id = sign_tx(transaction_to_sign)
        if tx_id != ERROR and tx_id != DOUBLE_SPENDING_ATTEMPT:
            logger.info("Successfully submitted interest transaction with ID: %s", tx_id)
        elif tx_id == DOUBLE_SPENDING_ATTEMPT:
            logger.info("Double Spend attempt, trying with higher fee")
            e_update_interest_rate(pool, curr_height, latest_tx, dummy_script, fee + 2000)
        else:
            logger.warning(
                "Failed to submit transaction: %s Failed txID quoted as: %s",
                json.dumps(transaction_to_sign), tx_id)
