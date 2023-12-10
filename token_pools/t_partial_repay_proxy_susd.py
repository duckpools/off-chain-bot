import json

from consts import MIN_BOX_VALUE, TX_FEE, NULL_TX_OBJ, ERROR
from helpers.explorer_calls import get_box_from_id_explorer
from helpers.job_helpers import job_processor
from helpers.node_calls import box_id_to_binary, sign_tx, tree_to_address
from helpers.platform_functions import get_parent_box, get_head_child, get_children_boxes, get_base_child, \
    get_interest_box, get_dex_box
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
    if box["assets"][0]["tokenId"] != pool["CURRENCY_ID"]:
        return

    collateral_box = box["additionalRegisters"]["R4"]["renderedValue"]
    final_borrow_tokens = int(box["additionalRegisters"]["R5"]["renderedValue"])
    whole_collateral_box = get_box_from_id_explorer(collateral_box)
    logger.debug("Whole collateral box: ", whole_collateral_box)
    if not whole_collateral_box or len(whole_collateral_box["spentTransactionId"]) == 64:
        refund_repay_proxy_box(box)
        return

    parent_box = get_parent_box(pool["parent"], pool["PARENT_NFT"])
    head_child = get_head_child(pool["child"], pool["CHILD_NFT"], pool["parent"], pool["PARENT_NFT"])
    children = get_children_boxes(pool["child"], pool["CHILD_NFT"])
    loan_indexes = json.loads(whole_collateral_box["additionalRegisters"]["R5"]["renderedValue"])
    loan_parent_index = loan_indexes[0]
    base_child = get_base_child(children, loan_parent_index)
    interest_box = get_interest_box(pool["child"], pool["CHILD_NFT"])
    dex_nft = whole_collateral_box["additionalRegisters"]["R7"]["renderedValue"]
    dex_box = get_dex_box(dex_nft)

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

                }
            ],
            "fee": TX_FEE,
            "inputsRaw":
                [box_id_to_binary(box["boxId"]), box_id_to_binary(collateral_box)],
            "dataInputsRaw":
                [box_id_to_binary(base_child["boxId"]),box_id_to_binary(parent_box["boxId"]),
                  box_id_to_binary(head_child["boxId"]), box_id_to_binary(dex_box["boxId"])]
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
