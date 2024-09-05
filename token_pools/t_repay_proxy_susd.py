import json

from consts import TX_FEE, MIN_BOX_VALUE, NULL_TX_OBJ
from helpers.explorer_calls import get_box_from_id_explorer
from helpers.job_helpers import job_processor
from helpers.node_calls import tree_to_address, box_id_to_binary, sign_tx
from helpers.platform_functions import get_children_boxes, get_base_child, \
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
                        {
                            "tokenId": box["assets"][0]["tokenId"],
                            "amount": box["assets"][0]["amount"]
                        }
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
    if len(box["assets"]) == 0 or box["assets"][0]["tokenId"] != pool["CURRENCY_ID"]:
        return
    borrower = box["additionalRegisters"]["R5"]["renderedValue"]
    collateral_box = box["additionalRegisters"]["R7"]["renderedValue"]
    whole_collateral_box = get_box_from_id_explorer(collateral_box)
    logger.debug("Whole collateral box: ", whole_collateral_box)

    if not whole_collateral_box:
        refund_repay_proxy_box(box)
        return

    interest_box = get_interest_box(pool["interest"], pool["INTEREST_NFT"])

    if not interest_box:
        logger.debug("No Interest Box Found")
        return

    collateral_box_binary = None
    try:
        collateral_box_binary = box_id_to_binary(collateral_box)
    except Exception:
        refund_repay_proxy_box(box)

    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": tree_to_address(borrower),
                    "value": whole_collateral_box["value"],
                    "assets": [
                    ],
                    "registers": {
                        "R4": "0e20" + box["boxId"]
                    }
                },
                {
                    "address": pool["repayment"],
                    "value": MIN_BOX_VALUE + TX_FEE,
                    "assets": [
                        {
                            "tokenId": whole_collateral_box["assets"][0]["tokenId"],
                            "amount": whole_collateral_box["assets"][0]["amount"]
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
                [box_id_to_binary(box["boxId"]), collateral_box_binary],
            "dataInputsRaw":
                [box_id_to_binary(interest_box["boxId"])]
        }

    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)
    if tx_id != -1:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    else:
        logger.debug("Failed to submit transaction, attempting to refund")
        refund_repay_proxy_box(box)
    return


def t_repay_proxy_job(pool):
    job_processor(pool, pool["proxy_repay"], NULL_TX_OBJ, process_repay_proxy_box, "SUSD", 1047423)
