import json

from consts import TX_FEE, MAX_BORROW_TOKENS
from helpers.job_helpers import latest_pool_info, job_processor
from helpers.node_calls import box_id_to_binary, sign_tx
from logger import set_logger

logger = set_logger(__name__)


def process_repay_to_pool_box_v1(pool, box, latest_tx):
    erg_pool_box, borrowed = latest_pool_info(pool, latest_tx)

    erg_to_give = box["value"] - TX_FEE
    final_borrowed = borrowed - int(box["assets"][0]["amount"])

    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": pool["pool"],
                    "value": erg_pool_box["value"] + erg_to_give,
                    "assets": [
                        {
                            "tokenId": erg_pool_box["assets"][0]["tokenId"],
                            "amount": erg_pool_box["assets"][0]["amount"]
                        },
                        {
                            "tokenId": erg_pool_box["assets"][1]["tokenId"],
                            "amount": erg_pool_box["assets"][1]["amount"]
                        },
                        {
                            "tokenId": erg_pool_box["assets"][2]["tokenId"],
                            "amount": MAX_BORROW_TOKENS - final_borrowed
                        }
                    ],
                    "registers": {
                    }
                },
            ],
            "fee": TX_FEE,
            "inputsRaw":
                [box_id_to_binary(erg_pool_box["boxId"]), box_id_to_binary(box["boxId"])],
            "dataInputsRaw":
                []
        }

    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)

    obj = {"txId": tx_id,
           "finalBorrowed": final_borrowed}
    if tx_id != -1:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    else:
        logger.debug("Failed to submit transaction")
        return None
    return obj


def process_repay_to_pool_box_v2(pool, box, latest_tx):
    return process_repay_to_pool_box_v1(pool, box, latest_tx)


def e_repay_to_pool_job(pool, curr_tx_obj):
    job_processor(pool, pool["repayment"], curr_tx_obj, process_repay_to_pool_box_v1, process_repay_to_pool_box_v2, "repay to pool", 1535250)
