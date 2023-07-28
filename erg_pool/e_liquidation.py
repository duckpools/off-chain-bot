import json
import math
import time
from math import floor

from consts import TX_FEE, PENALTY_DENOMINATION, MIN_BOX_VALUE, SIG_USD_ID, ERG_USD_DEX_NFT, SIG_RSV_ID, ERG_RSV_DEX_NFT
from helpers.explorer_calls import get_unspent_boxes_by_address
from helpers.node_calls import tree_to_address, box_id_to_binary, get_box_from_id, sign_tx
from helpers.platform_functions import get_dex_box, get_dex_box_from_tx, get_base_child, get_parent_box, get_head_child, \
    get_children_boxes, liquidation_allowed
from logger import set_logger

logger = set_logger(__name__)


def create_transaction_to_sign(pool, dex_box, box, dex_initial_val, dex_tokens, tokens_to_liquidate, liquidation_value,
                               lp_tokens, dex_box_address, total_due, head_child, parent_box, base_child):
    """
    Create a transaction to sign for liquidation.
    """
    collateral_value = liquidation_value - TX_FEE * 3
    liquidation_penalty = json.loads(box["additionalRegisters"]["R6"]["renderedValue"])[1]
    borrower_share = math.ceil(((collateral_value - total_due) * (PENALTY_DENOMINATION - liquidation_penalty)) / PENALTY_DENOMINATION)
    print(borrower_share)
    user = tree_to_address(box["additionalRegisters"]["R4"]["renderedValue"])
    if (borrower_share < MIN_BOX_VALUE):
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
            ],
            "fee": 3 * TX_FEE + box["value"],
            "inputsRaw": [box_id_to_binary(dex_box["boxId"]), box_id_to_binary(box["boxId"])],
            "dataInputsRaw": [box_id_to_binary(base_child["boxId"]),box_id_to_binary(parent_box["boxId"]),
                  box_id_to_binary(head_child["boxId"])]
        }
    else:
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
            ],
            "fee": 2.5 * TX_FEE + box["value"],
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
    if box["assets"][0]['tokenId'] == SIG_USD_ID:
        dex_box, lp_tokens, dex_box_address = get_dex_box_and_tokens(sig_usd_tx, ERG_USD_DEX_NFT)

    if box["assets"][0]['tokenId'] == SIG_RSV_ID:
        if sig_rsv_tx is None:
            dex_box, lp_tokens, dex_box_address = get_dex_box_and_tokens(sig_rsv_tx, ERG_RSV_DEX_NFT)

    dex_initial_val = dex_box["value"]
    dex_tokens = dex_box["assets"][2]["amount"]
    price_of_token = dex_initial_val / dex_tokens
    tokens_to_liquidate = box["assets"][0]["amount"]
    liquidation_value = floor(tokens_to_liquidate * price_of_token * 0.993)
    loan_indexes = json.loads(box["additionalRegisters"]["R5"]["renderedValue"])
    loan_parent_index = loan_indexes[0]
    base_child = get_base_child(children, loan_parent_index)

    transaction_to_sign = create_transaction_to_sign(pool, dex_box, box, dex_initial_val, dex_tokens, tokens_to_liquidate,
                                                     liquidation_value, lp_tokens, dex_box_address, total_due, head_child, parent_box, base_child)
    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)

    if tx_id != -1:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
        if box["assets"][0]['tokenId'] == SIG_USD_ID:
            return [tx_id, sig_rsv_tx]
        if box["assets"][0]['tokenId'] == SIG_RSV_ID:
            return [sig_usd_tx, tx_id]
    else:
        logger.debug("Failed to submit transaction")
        return [sig_usd_tx, sig_rsv_tx]


def e_liquidation_job(pool):
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
                    tx = process_liquidation(pool, box, tx[0], tx[1], liquidation_response[1], head_child, parent_box, children)
                except Exception as e:
                    logger.exception(
                        f"Failed to process liquidation box for transaction id: {transaction_id}. Exception: {e}")
