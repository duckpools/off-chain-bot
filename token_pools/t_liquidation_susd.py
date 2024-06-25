import json
import math
import time
from math import floor

from consts import PENALTY_DENOMINATION, MIN_BOX_VALUE, TX_FEE, DEFAULT_BUFFER
from helpers.explorer_calls import get_unspent_boxes_by_address, get_dummy_box
from helpers.node_calls import tree_to_address, box_id_to_binary, get_box_from_id, sign_tx, current_height
from helpers.platform_functions import get_dex_box, get_dex_box_from_tx, get_base_child, \
    get_children_boxes, liquidation_allowed_susd
from helpers.serializer import encode_long_pair
from logger import set_logger

logger = set_logger(__name__)


def create_transaction_to_sign(pool, dex_box, box, dex_initial_val, dex_tokens, tokens_to_liquidate, liquidation_value, client_amount,
                               lp_tokens, dex_box_address, total_due, head_child, parent_box, base_child, dummy_script):
    """
    Create a transaction to sign for liquidation.
    """
    collateral_value = liquidation_value
    liquidation_penalty = json.loads(box["additionalRegisters"]["R6"]["renderedValue"])[1]
    borrower_share = math.floor(((collateral_value - total_due) * (PENALTY_DENOMINATION - liquidation_penalty)) / PENALTY_DENOMINATION)
    user = tree_to_address(box["additionalRegisters"]["R4"]["renderedValue"])


    liquidation_forced = json.loads(box["additionalRegisters"]["R9"]["renderedValue"])[0]
    liquidation_buffer = json.loads(box["additionalRegisters"]["R9"]["renderedValue"])[1]
    dummy_box = get_dummy_box(dummy_script)
    curr_height = current_height()
    if ((curr_height < liquidation_forced) and liquidation_buffer == DEFAULT_BUFFER):
        transaction_to_sign = \
            {
                "requests": [
                    {
                        "address": box["address"],
                        "value": box["value"] - TX_FEE,
                        "assets": [
                            {
                                "tokenId": box["assets"][0]["tokenId"],
                                "amount": box["assets"][0]["amount"]
                            }
                        ],
                        "registers": {
                            "R4": box["additionalRegisters"]["R4"]["serializedValue"],
                            "R5": box["additionalRegisters"]["R5"]["serializedValue"],
                            "R6": box["additionalRegisters"]["R6"]["serializedValue"],
                            "R7": box["additionalRegisters"]["R7"]["serializedValue"],
                            "R8": box["additionalRegisters"]["R8"]["serializedValue"],
                            "R9": encode_long_pair(liquidation_forced, curr_height + 4)
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
                "fee": TX_FEE,
                "inputsRaw":
                    [box_id_to_binary(dummy_box["boxId"]), box_id_to_binary(box["boxId"])],
                "dataInputsRaw":
                    [box_id_to_binary(base_child["boxId"]), box_id_to_binary(parent_box["boxId"]),
                     box_id_to_binary(head_child["boxId"]), box_id_to_binary(dex_box["boxId"])]
            }
    elif ((curr_height > liquidation_forced or curr_height > liquidation_buffer) and borrower_share < 1):
        transaction_to_sign = {
            "requests": [
                {
                    "address": dex_box_address,
                    "value": dex_initial_val + tokens_to_liquidate,
                    "assets": [
                        {
                            "tokenId": dex_box["assets"][0]["tokenId"],
                            "amount": str(dex_box["assets"][0]["amount"])
                        },
                        {
                            "tokenId": dex_box["assets"][1]["tokenId"],
                            "amount": str(lp_tokens)
                        },
                        {
                            "tokenId": dex_box["assets"][2]["tokenId"],
                            "amount": str(dex_tokens - liquidation_value)
                        }
                    ],
                    "registers": {
                        "R4": pool["collateral_supported"]["erg"]["dex_fee_serialized"]
                    }
                },
                {
                    "address": pool["repayment"],
                    "value": MIN_BOX_VALUE + TX_FEE,
                    "assets": [
                        {
                            "tokenId": box["assets"][0]["tokenId"],
                            "amount": box["assets"][0]["amount"]
                        },
                        {
                            "tokenId": dex_box["assets"][2]["tokenId"],
                            "amount": str(liquidation_value)
                        }
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
            "fee": TX_FEE,
            "inputsRaw": [box_id_to_binary(dex_box["boxId"]), box_id_to_binary(box["boxId"]), box_id_to_binary(dummy_box["boxId"])],
            "dataInputsRaw": [box_id_to_binary(base_child["boxId"]),box_id_to_binary(parent_box["boxId"]),
                  box_id_to_binary(head_child["boxId"])]
        }
    elif ((curr_height > liquidation_forced or curr_height > liquidation_buffer)):
        transaction_to_sign = {
            "requests": [
                {
                    "address": dex_box_address,
                    "value": dex_initial_val + tokens_to_liquidate,
                    "assets": [
                        {
                            "tokenId": dex_box["assets"][0]["tokenId"],
                            "amount": str(dex_box["assets"][0]["amount"])
                        },
                        {
                            "tokenId": dex_box["assets"][1]["tokenId"],
                            "amount": str(lp_tokens)
                        },
                        {
                            "tokenId": dex_box["assets"][2]["tokenId"],
                            "amount": str(dex_tokens - liquidation_value - client_amount)
                        }
                    ],
                    "registers": {
                        "R4": pool["collateral_supported"]["erg"]["dex_fee_serialized"]
                    }
                },
                {
                    "address": pool["repayment"],
                    "value": MIN_BOX_VALUE + TX_FEE,
                    "assets": [
                        {
                            "tokenId": box["assets"][0]["tokenId"],
                            "amount": box["assets"][0]["amount"]
                        },
                        {
                            "tokenId": dex_box["assets"][2]["tokenId"],
                            "amount": str(liquidation_value - borrower_share + client_amount)
                        }
                    ],
                    "registers": {
                    }
                },
                {
                    "address": user,
                    "value": MIN_BOX_VALUE / 2,
                    "assets": [
                        {
                            "tokenId": dex_box["assets"][2]["tokenId"],
                            "amount": str(borrower_share)
                        }
                    ],
                    "registers": {
                    }
                },
                {
                    "address": dummy_box["address"],
                    "value": dummy_box["value"],
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
            "fee": TX_FEE,
            "inputsRaw": [box_id_to_binary(dex_box["boxId"]), box_id_to_binary(box["boxId"]), box_id_to_binary(dummy_box["boxId"])],
            "dataInputsRaw": [box_id_to_binary(base_child["boxId"]),box_id_to_binary(parent_box["boxId"]),
                  box_id_to_binary(head_child["boxId"])]
        }
    else:
        print("Waiting for buffer")
        return None
    return transaction_to_sign


def get_dex_box_and_tokens(transaction, nft):
    """
    Get the dex box, its LP tokens, and address from a transaction.
    """
    if transaction is None:
        dex_box = get_dex_box(nft)
        dex_box_contents = get_box_from_id(dex_box['boxId'])
        lp_tokens = dex_box_contents["assets"][1]["amount"]
        dex_box_address = dex_box["address"]
    else:
        dex_box = get_dex_box_from_tx(transaction)
        lp_tokens = dex_box["assets"][1]["amount"]
        dex_box_address = tree_to_address(dex_box['ergoTree'])

    return dex_box, lp_tokens, dex_box_address


def process_liquidation(pool, box, sig_usd_tx, sig_rsv_tx, total_due, head_child, parent_box, children, dummy_script):
    dex_box, lp_tokens, dex_box_address = get_dex_box_and_tokens(sig_usd_tx, pool["collateral_supported"]["erg"]["dex_nft"])

    dex_initial_val = dex_box["value"]
    dex_tokens = dex_box["assets"][2]["amount"]
    tokens_to_liquidate = box["value"] - MIN_BOX_VALUE - 3 * TX_FEE
    dex_fee = pool["collateral_supported"]["erg"]["dex_fee"]
    liquidation_value = floor((dex_tokens * tokens_to_liquidate * dex_fee) /
			((dex_initial_val + floor((dex_initial_val * 2 / 100))) * 1000 +
			(tokens_to_liquidate * dex_fee)))
    client_amount = floor((dex_tokens * tokens_to_liquidate * dex_fee) /
                              ((dex_initial_val + floor((dex_initial_val * 1 / 100))) * 1000 +
                               (tokens_to_liquidate * dex_fee))) - liquidation_value
    loan_indexes = json.loads(box["additionalRegisters"]["R5"]["renderedValue"])
    loan_parent_index = loan_indexes[0]
    base_child = get_base_child(children, loan_parent_index)

    transaction_to_sign = create_transaction_to_sign(pool, dex_box, box, dex_initial_val, dex_tokens, tokens_to_liquidate, liquidation_value, client_amount,
                                                     lp_tokens, dex_box_address, total_due, head_child, parent_box, base_child, dummy_script)
    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    if transaction_to_sign is None:
        return [sig_usd_tx, sig_rsv_tx]
    tx_id = sign_tx(transaction_to_sign)

    if tx_id != -1 and tx_id != 1409:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
        return [tx_id, sig_rsv_tx]
    else:
        logger.debug("Failed to submit transaction")
        return [sig_usd_tx, sig_rsv_tx]


def t_liquidation_job(pool, dummy_script, height):
    time.sleep(1)
    logger.info("Starting %s request processing", "liquidation")
    unspent_proxy_boxes = get_unspent_boxes_by_address(pool["collateral"])
    logger.debug(unspent_proxy_boxes)
    num_unspent_proxy_boxes = len(unspent_proxy_boxes)
    logger.info(f"Found: {num_unspent_proxy_boxes} boxes")

    tx = [None, None]
    parent_box = get_parent_box(pool["parent"], pool["PARENT_NFT"])
    head_child = get_head_child(pool["child"], pool["CHILD_NFT"], pool["parent"], pool["PARENT_NFT"])
    children = get_children_boxes(pool["child"], pool["CHILD_NFT"])
    if len(unspent_proxy_boxes) > 0:
        for box in unspent_proxy_boxes:
            liquidation_response = liquidation_allowed_susd(box, parent_box, head_child, children, pool["collateral_supported"]["erg"]["dex_nft"], pool["liquidation_threshold"], height)
            if liquidation_response[0] == True:
                transaction_id = box["transactionId"]
                logger.debug(f"Liquidation Proxy Transaction Id: {transaction_id}")
                try:
                    tx = process_liquidation(pool, box, tx[0], tx[1], liquidation_response[1], head_child, parent_box, children, dummy_script)
                except Exception as e:
                    logger.exception(
                        f"Failed to process liquidation box for transaction id: {transaction_id}. Exception: {e}")
