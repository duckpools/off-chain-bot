import json

from consts import TX_FEE, MAX_BORROW_TOKENS
from helpers.job_helpers import latest_pool_info, job_processor, op_job_processor, op_latest_pool_info
from helpers.node_calls import box_id_to_binary, sign_tx
from logger import set_logger

logger = set_logger(__name__)


def process_repay_to_pool(pool, box, latest_tx, serialized_r4):
    pool_box = op_latest_pool_info(pool, latest_tx)
    erg_to_give = int(box["value"]) - TX_FEE
    y_to_give = 0
    if len(box["assets"]) > 1:
        y_to_give = int(box["assets"][1]["amount"])
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": pool["pool"],
                    "value": pool_box["value"] + erg_to_give,
                    "assets": [
                        {
                            "tokenId": pool_box["assets"][0]["tokenId"],
                            "amount": pool_box["assets"][0]["amount"]
                        },
                        {
                            "tokenId": pool_box["assets"][1]["tokenId"],
                            "amount": pool_box["assets"][1]["amount"]
                        },
                        {
                            "tokenId": pool_box["assets"][2]["tokenId"],
                            "amount": pool_box["assets"][2]["amount"] + y_to_give
                        },
                        {
                            "tokenId": pool_box["assets"][3]["tokenId"],
                            "amount": pool_box["assets"][3]["amount"] + 1
                        }
                    ],
                    "registers": {
                        "R4": serialized_r4
                    }
                },
            ],
            "fee": TX_FEE,
            "inputsRaw":
                [box_id_to_binary(pool_box["boxId"]), box_id_to_binary(box["boxId"])],
            "dataInputsRaw":
                []
        }

    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)

    obj = {"txId": tx_id}
    if tx_id != -1:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    else:
        logger.debug("Failed to submit transaction")
        return None
    return obj


def repay_to_pool_job(pool, serialized_r4):
    op_job_processor(pool, pool["repayment"], None, serialized_r4, process_repay_to_pool, "repay to pool", 1051829)
