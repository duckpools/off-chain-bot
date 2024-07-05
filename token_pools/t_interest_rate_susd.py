import json
from math import floor
from secrets import randbelow

from client_consts import node_address
from consts import INTEREST_MULTIPLIER, MIN_BOX_VALUE, INTEREST_FREQUENCY_POLL, MAX_BORROW_TOKENS, TX_FEE, ERROR, \
    DOUBLE_SPENDING_ATTEMPT, BorrowTokenDenomination
from helpers.explorer_calls import get_dummy_box
from helpers.node_calls import box_id_to_binary, sign_tx
from helpers.platform_functions import get_pool_box, get_pool_box_from_tx, \
    get_interest_param_box, get_interest_box
from helpers.serializer import encode_long, encode_bigint, extract_number
from logger import set_logger

logger = set_logger(__name__)


def t_update_interest_rate(pool, curr_height, latest_tx, dummy_script, fee=randbelow(1300001 - 1100000) + 1100000):
    dummy_box = get_dummy_box(dummy_script)
    logger.info("Starting Interest Rate Job")
    box = get_interest_box(pool["interest"], pool["INTEREST_NFT"])
    box_curr_height = int(box["additionalRegisters"]["R4"]["renderedValue"])
    if box_curr_height < curr_height:
        if box_curr_height + 40 < curr_height:
            fee += 90000
        elif box_curr_height + 25 < curr_height:
            fee += 60000
        elif box_curr_height + 15 < curr_height:
            fee += 10000
        if latest_tx is None:
            erg_pool_box = get_pool_box(pool["pool"], pool["POOL_NFT"])
            borrowedTokens = MAX_BORROW_TOKENS - int(erg_pool_box["assets"][2]["amount"])
        else:
            erg_pool_box = get_pool_box_from_tx(latest_tx["txId"])
            borrowedTokens = latest_tx["finalBorrowed"]

        print(borrowedTokens)
        interest_param_box = get_interest_param_box(pool["interest_parameter"], pool["INTEREST_PARAMETER_NFT"])
        coefficients = json.loads(interest_param_box["additionalRegisters"]["R4"]["renderedValue"])
        a = coefficients[0]
        b = coefficients[1]
        c = coefficients[2]
        d = coefficients[3]
        e = coefficients[4]
        f = coefficients[5]
        current_value = floor(extract_number(box["additionalRegisters"]["R5"]["renderedValue"]))

        real_value = erg_pool_box["assets"][3]["amount"]
        borrowed = floor(borrowedTokens * current_value / BorrowTokenDenomination)
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

        transaction_to_sign = \
            {
                "requests": [
                    {
                        "address": pool["interest"],
                        "value": int(box["value"]) - (1.9 * MIN_BOX_VALUE),
                        "assets": [
                            {
                            "tokenId": box["assets"][0]["tokenId"],
                            "amount": box["assets"][0]["amount"]
                            }
                        ],
                        "registers": {
                            "R4": encode_long(box_curr_height + INTEREST_FREQUENCY_POLL),
                            "R5": encode_bigint(floor(current_value * current_rate // M)),
                            "R6": "0101",
                            "R7": "0101",
                            "R8": "0101",
                            "R9": "0101"
                        }
                    },
                    {
                        "address": node_address,
                        "value": 1.9 * MIN_BOX_VALUE - fee,
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
            t_update_interest_rate(pool, curr_height, latest_tx, dummy_script, fee + 2000)
        else:
            logger.warning(
                "Failed to submit transaction: %s Failed txID quoted as: %s",
                json.dumps(transaction_to_sign), tx_id)
