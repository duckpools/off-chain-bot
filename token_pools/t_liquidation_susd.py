import json
import math
import time
from math import floor

from consts import PENALTY_DENOMINATION, MIN_BOX_VALUE, TX_FEE, ERG_USD_DEX_NFT
from helpers.explorer_calls import get_unspent_boxes_by_address
from helpers.node_calls import tree_to_address, box_id_to_binary, get_box_from_id, sign_tx
from helpers.platform_functions import get_dex_box, get_dex_box_from_tx, get_base_child, get_parent_box, get_head_child, \
    get_children_boxes, liquidation_allowed_susd
from logger import set_logger

logger = set_logger(__name__)


def create_transaction_to_sign(pool, dex_box, box, dex_initial_val, dex_tokens, tokens_to_liquidate, liquidation_value,
                               lp_tokens, dex_box_address, total_due, head_child, parent_box, base_child):
    """
    Create a transaction to sign for liquidation.
    """
    collateral_value = liquidation_value
    liquidation_penalty = json.loads(box["additionalRegisters"]["R6"]["renderedValue"])[1]
    borrower_share = math.floor(((collateral_value - total_due) * (PENALTY_DENOMINATION - liquidation_penalty)) / PENALTY_DENOMINATION)
    user = tree_to_address(box["additionalRegisters"]["R4"]["renderedValue"])
    if (borrower_share < 1):
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
                        "R4": "04c60f"
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
            ],
            "fee": TX_FEE,
            "inputsRaw": [box_id_to_binary(dex_box["boxId"]), box_id_to_binary(box["boxId"])],
            "dataInputsRaw": [box_id_to_binary(base_child["boxId"]),box_id_to_binary(parent_box["boxId"]),
                  box_id_to_binary(head_child["boxId"])]
        }
        print(transaction_to_sign)
    else:
        print(borrower_share)
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
                        "R4": "04c60f"
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
                            "amount": str(liquidation_value - borrower_share)
                        }
                    ],
                    "registers": {
                    }
                },
                {
                    "address": user,
                    "value": MIN_BOX_VALUE,
                    "assets": [
                        {
                            "tokenId": dex_box["assets"][2]["tokenId"],
                            "amount": str(borrower_share)
                        }
                    ],
                    "registers": {
                    }
                },
            ],
            "fee": TX_FEE,
            "inputsRaw": [box_id_to_binary(dex_box["boxId"]), box_id_to_binary(box["boxId"])],
            "dataInputsRaw": [box_id_to_binary(base_child["boxId"]),box_id_to_binary(parent_box["boxId"]),
                  box_id_to_binary(head_child["boxId"])]
        }
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


def process_liquidation(pool, box, sig_usd_tx, sig_rsv_tx, total_due, head_child, parent_box, children):
    dex_box, lp_tokens, dex_box_address = get_dex_box_and_tokens(sig_usd_tx, pool["collateral_supported"]["erg"]["dex_nft"])

    dex_initial_val = dex_box["value"]
    dex_tokens = dex_box["assets"][2]["amount"]
    tokens_to_liquidate = box["value"] - MIN_BOX_VALUE - 3 * TX_FEE
    liquidation_value = floor((dex_tokens * tokens_to_liquidate * 995) /
			((dex_initial_val + floor((dex_initial_val * 2 / 100))) * 1000 +
			(tokens_to_liquidate * 995)))
    loan_indexes = json.loads(box["additionalRegisters"]["R5"]["renderedValue"])
    loan_parent_index = loan_indexes[0]
    base_child = get_base_child(children, loan_parent_index)

    transaction_to_sign = create_transaction_to_sign(pool, dex_box, box, dex_initial_val, dex_tokens, tokens_to_liquidate,
                                                     liquidation_value, lp_tokens, dex_box_address, total_due, head_child, parent_box, base_child)
    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)

    if tx_id != -1:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
        return [tx_id, sig_rsv_tx]
    else:
        logger.debug("Failed to submit transaction")
        return [sig_usd_tx, sig_rsv_tx]


def t_liquidation_job(pool):
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
            liquidation_response = liquidation_allowed_susd(box, parent_box, head_child, children, pool["collateral_supported"]["erg"]["dex_nft"])
            if liquidation_response[0] == True:
                transaction_id = box["transactionId"]
                logger.debug(f"Liquidation Proxy Transaction Id: {transaction_id}")
                try:
                    tx = process_liquidation(pool, box, tx[0], tx[1], liquidation_response[1], head_child, parent_box, children)
                except Exception as e:
                    logger.exception(
                        f"Failed to process liquidation box for transaction id: {transaction_id}. Exception: {e}")
