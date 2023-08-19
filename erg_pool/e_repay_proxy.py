import json

from consts import TX_FEE, MIN_BOX_VALUE, NULL_TX_OBJ
from helpers.explorer_calls import get_box_from_id_explorer
from helpers.job_helpers import job_processor
from helpers.node_calls import tree_to_address, box_id_to_binary, sign_tx
from helpers.platform_functions import get_parent_box, get_head_child, get_children_boxes, get_base_child, \
    get_interest_box
from logger import set_logger

logger = set_logger(__name__)


def refund_repay_proxy_box(box):
    borrower = box["additionalRegisters"]["R5"]["renderedValue"]
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": tree_to_address(borrower),
                    "value": box["value"] - TX_FEE,
                    "assets": [
                    ],
                    "registers": {
                    }
                },
            ],
            "fee": TX_FEE,
            "inputsRaw":
                [box_id_to_binary(box["boxId"])],
            "dataInputsRaw": []
        }

    logger.debug("Signing Refund Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)
    if tx_id != -1:
        logger.info("Successfully submitted refund transaction with ID: %s", tx_id)
    else:
        logger.warning("Failed to process or refund transaction object: %s Failed Refund txID quoted as: %s",
                       json.dumps(transaction_to_sign), tx_id)


def process_repay_proxy_box(pool, box, empty):
    borrower = box["additionalRegisters"]["R5"]["renderedValue"]
    collateral_box = box["additionalRegisters"]["R7"]["renderedValue"]
    whole_collateral_box = get_box_from_id_explorer(collateral_box)
    logger.debug("Whole collateral box: ", whole_collateral_box)

    if not whole_collateral_box:
        refund_repay_proxy_box(box)
        return

    parent_box = get_parent_box(pool["parent"], pool["PARENT_NFT"])
    head_child = get_head_child(pool["child"], pool["CHILD_NFT"], pool["parent"], pool["PARENT_NFT"])
    children = get_children_boxes(pool["child"], pool["CHILD_NFT"])
    loan_indexes = json.loads(whole_collateral_box["additionalRegisters"]["R5"]["renderedValue"])
    loan_parent_index = loan_indexes[0]
    base_child = get_base_child(children, loan_parent_index)

    interest_box = get_interest_box(pool["child"], pool["CHILD_NFT"])

    if not interest_box:
        logger.debug("No Interest Box Found")
        return

    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": tree_to_address(borrower),
                    "value": MIN_BOX_VALUE,
                    "assets": [
                        {
                            "tokenId": whole_collateral_box["assets"][0]["tokenId"],
                            "amount": whole_collateral_box["assets"][0]["amount"]
                        }
                    ],
                    "registers": {
                        "R4": "0e20" + box["boxId"]
                    }
                },
                {
                    "address": pool["repayment"],
                    "value": box["value"] - MIN_BOX_VALUE - TX_FEE + whole_collateral_box["value"],
                    "assets": [
                        {
                            "tokenId": whole_collateral_box["assets"][1]["tokenId"],
                            "amount": whole_collateral_box["assets"][1]["amount"]
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
                  box_id_to_binary(head_child["boxId"])]
        }

    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)
    if tx_id != -1:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    else:
        logger.debug("Failed to submit transaction, attempting to refund")
    return


def e_repay_proxy_job(pool):
    job_processor(pool, pool["proxy_repay"], NULL_TX_OBJ, process_repay_proxy_box, "SUSD")
