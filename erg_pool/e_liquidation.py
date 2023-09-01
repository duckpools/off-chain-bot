import json
import math
import time
from math import floor

from consts import TX_FEE, PENALTY_DENOMINATION, MIN_BOX_VALUE, SIG_USD_ID, ERG_USD_DEX_NFT, SIG_RSV_ID, \
    ERG_RSV_DEX_NFT, DEFAULT_BUFFER
from helpers.explorer_calls import get_unspent_boxes_by_address, get_dummy_box
from helpers.node_calls import tree_to_address, box_id_to_binary, get_box_from_id, sign_tx, current_height
from helpers.platform_functions import get_dex_box, get_dex_box_from_tx, get_base_child, get_parent_box, get_head_child, \
    get_children_boxes, liquidation_allowed
from helpers.serializer import encode_long_pair
from logger import set_logger

logger = set_logger(__name__)


def create_transaction_to_sign(pool, dex_box, box, dex_initial_val, dex_tokens, tokens_to_liquidate, liquidation_value,
                               lp_tokens, dex_box_address, total_due, head_child, parent_box, base_child, dummy_script):
    """
    Create a transaction to sign for liquidation.
    """
    collateral_value = liquidation_value - TX_FEE * 4
    liquidation_penalty = json.loads(box["additionalRegisters"]["R6"]["renderedValue"])[1]
    liquidation_forced = json.loads(box["additionalRegisters"]["R9"]["renderedValue"])[0]
    liquidation_buffer = json.loads(box["additionalRegisters"]["R9"]["renderedValue"])[1]
    borrower_share = math.ceil(
        ((collateral_value - total_due) * (PENALTY_DENOMINATION - liquidation_penalty)) / PENALTY_DENOMINATION)
    user = tree_to_address(box["additionalRegisters"]["R4"]["renderedValue"])
    dummy_box = get_dummy_box(dummy_script)
    curr_height = current_height()
    if (liquidation_buffer == DEFAULT_BUFFER):
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
                            },
                            {
                                "tokenId": box["assets"][1]["tokenId"],
                                "amount": box["assets"][1]["amount"]
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
    elif (curr_height > liquidation_buffer and  borrower_share < MIN_BOX_VALUE):
        transaction_to_sign = {
            "requests": [
                {
                    "address": dex_box_address,
                    "value": dex_initial_val - liquidation_value,
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
                            "amount": str(dex_tokens + tokens_to_liquidate)
                        }
                    ],
                    "registers": {
                        "R4": "04c60f"
                    }
                },
                {
                    "address": pool["repayment"],
                    "value": liquidation_value - TX_FEE * 3,
                    "assets": [
                        {
                            "tokenId": box["assets"][1]["tokenId"],
                            "amount": box["assets"][1]["amount"]
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
                        }
                    ],
                    "registers": {
                    }
                }
            ],
            "fee": TX_FEE + box["value"],
            "inputsRaw": [box_id_to_binary(dex_box["boxId"]), box_id_to_binary(box["boxId"]), box_id_to_binary(dummy_box["boxId"])],
            "dataInputsRaw": [box_id_to_binary(base_child["boxId"]), box_id_to_binary(parent_box["boxId"]),
                              box_id_to_binary(head_child["boxId"])]
        }
    elif (curr_height > liquidation_buffer):
        transaction_to_sign = {
            "requests": [
                {
                    "address": dex_box_address,
                    "value": dex_initial_val - liquidation_value,
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
                            "amount": str(dex_tokens + tokens_to_liquidate)
                        }
                    ],
                    "registers": {
                        "R4": "04c60f"
                    }
                },
                {
                    "address": pool["repayment"],
                    "value": collateral_value - borrower_share,
                    "assets": [
                        {
                            "tokenId": box["assets"][1]["tokenId"],
                            "amount": box["assets"][1]["amount"]
                        }
                    ],
                    "registers": {
                    }
                },
                {
                    "address": user,
                    "value": borrower_share,
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
            "fee": TX_FEE + box["value"],
            "inputsRaw": [box_id_to_binary(dex_box["boxId"]), box_id_to_binary(box["boxId"]), box_id_to_binary(dummy_box["boxId"])],
            "dataInputsRaw": [box_id_to_binary(base_child["boxId"]), box_id_to_binary(parent_box["boxId"]),
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
    if box["assets"][0]['tokenId'] == SIG_USD_ID:
        dex_box, lp_tokens, dex_box_address = get_dex_box_and_tokens(sig_usd_tx, ERG_USD_DEX_NFT)

    if box["assets"][0]['tokenId'] == SIG_RSV_ID:
        dex_box, lp_tokens, dex_box_address = get_dex_box_and_tokens(sig_rsv_tx, ERG_RSV_DEX_NFT)

    dex_initial_val = int(dex_box["value"])
    dex_tokens = int(dex_box["assets"][2]["amount"])
    tokens_to_liquidate = int(box["assets"][0]["amount"])
    liquidation_value = ((int(dex_box["value"]) * int(box["assets"][0]["amount"]) * 995) //
        ((int(dex_box["assets"][2]["amount"]) +
          (int(dex_box["assets"][2]["amount"]) * 2) // 100) *
         1000 +
         int(box["assets"][0]["amount"]) *
         995))
    loan_indexes = json.loads(box["additionalRegisters"]["R5"]["renderedValue"])
    loan_parent_index = loan_indexes[0]
    base_child = get_base_child(children, loan_parent_index)

    transaction_to_sign = create_transaction_to_sign(pool, dex_box, box, dex_initial_val, dex_tokens,
                                                     tokens_to_liquidate,
                                                     liquidation_value, lp_tokens, dex_box_address, total_due,
                                                     head_child, parent_box, base_child, dummy_script)
    if transaction_to_sign is None:
        return [sig_usd_tx, sig_rsv_tx]
    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)

    if tx_id != -1 and tx_id != 1409:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
        if transaction_to_sign["requests"][0]["address"] == box["address"]:
            return [sig_usd_tx, sig_rsv_tx]
        if box["assets"][0]['tokenId'] == SIG_USD_ID:
            return [tx_id, sig_rsv_tx]
        if box["assets"][0]['tokenId'] == SIG_RSV_ID:
            return [sig_usd_tx, tx_id]
    else:
        logger.debug("Failed to submit transaction")
        return [sig_usd_tx, sig_rsv_tx]


def e_liquidation_job(pool, dummy_script):
    time.sleep(1)
    logger.info("Starting %s request processing", "liquidation")
    unspent_proxy_boxes = get_unspent_boxes_by_address(pool["collateral"])
    logger.debug(unspent_proxy_boxes)
    num_unspent_proxy_boxes = len(unspent_proxy_boxes)
    logger.info(f"Found: {num_unspent_proxy_boxes} boxes")

    tx = [None, None]
    parent_box = get_parent_box(pool["parent"], pool["PARENT_NFT"])
    head_child = get_head_child(pool["child"], pool["CHILD_NFT"], pool["parent"], pool["PARENT_NFT"], parent_box)
    children = get_children_boxes(pool["child"], pool["CHILD_NFT"])
    if len(unspent_proxy_boxes) > 0:
        for box in unspent_proxy_boxes:
            liquidation_response = liquidation_allowed(box, parent_box, head_child, children)
            if liquidation_response[0] == True:
                transaction_id = box["transactionId"]
                logger.debug(f"Liquidation Proxy Transaction Id: {transaction_id}")
                try:
                    tx = process_liquidation(pool, box, tx[0], tx[1], liquidation_response[1], head_child, parent_box,
                                             children, dummy_script)
                except Exception as e:
                    logger.exception(
                        f"Failed to process liquidation box for transaction id: {transaction_id}. Exception: {e}")
