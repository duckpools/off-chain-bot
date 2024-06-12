from consts import m_interest_addr, m_borrow_addr, m_lend_addr, m_pool_addr
from helpers.explorer_calls import get_unspent_boxes_by_address
from helpers.node_calls import mint_token
from helpers.serializer import hex_to_base58
from logger import set_logger
import time

logger = set_logger(__name__)


def mint_pool_nft(assetTicker, poolId):
    name = f"Pool NFT {assetTicker}-{poolId}"
    description = f"duckpools v2 Pool NFT for {assetTicker} pool"
    mint_token(m_pool_addr, name, description, 0, 1)

def mint_lend_token(assetTicker, poolId, decimals, amount=9000000000000010):
    name = f"Lend Token {assetTicker}-{poolId}"
    description = f"duckpools v2 Lend Token for {assetTicker} pool"
    mint_token(m_lend_addr, name, description, decimals, amount)

def mint_borrow_token(assetTicker, poolId):
    name = f"Borrow Token {assetTicker}-{poolId}"
    description = f"duckpools v2 Borrow Token for {assetTicker} pool"
    mint_token(m_borrow_addr, name, description, 9, 900000000000000000)

def mint_interest_token(assetTicker, poolId):
    name = f"Interest NFT {assetTicker}-{poolId}"
    description = f"duckpools v2 Interest Token for {assetTicker} pool"
    mint_token(m_interest_addr, name, description, 9, 1)

def mint_all_tokens(assetTicker, poolId, assetDecimals):
    mint_pool_nft(assetTicker, poolId)
    time.sleep(5)
    mint_lend_token(assetTicker, poolId, assetDecimals)
    time.sleep(5)
    mint_borrow_token(assetTicker, poolId)
    time.sleep(5)
    mint_interest_token(assetTicker, poolId)

def bootstrap_pool_box():
    pool_nft_utxo = get_unspent_boxes_by_address(m_pool_addr)[0]
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": "",
                    "value": 2000000 * len(binaries) - 1000000,
                    "assets": [],
                    "registers": {
                    }
                },
                {
                    "assetsToBurn": tokens
                }
            ],
            "fee": 1000000,
            "inputsRaw":
                binaries,
            "dataInputsRaw":
                []
        }
    sign_tx(transaction_to_sign, "Collecting with tx")

def create_pool():
    if len(count_mint_active()) > 0:
        logger.warning("There is an already an attempt to create pool, attempting to cancel...")
        if cancel_active_creations():
            create_pool()
        return
    logger.info("No active market creations found, attempting to mint tokens")
    mint_all_tokens("ERG", "2.0", 9)
    logger.info("Waiting for transactions to confirm, please do not terminate the program...")
    start_time = time.time()
    active_mints = count_mint_active()
    while len(active_mints) < 4:
        time.sleep(45)
        if (time.time() - start_time) > 900:
            clean_node()
            logger.error("Waited 900 seconds, assumed failure, terminating bot.")
            return
        logger.info("Still waiting for transactions to confirm, please do not terminate the program...")
        active_mints = count_mint_active()
    lend_token_id, pool_nft, borrow_token_id, interest_nft = active_mints
    print(active_mints)



def count_mint_active():
    boxes = []
    boxes.append(get_unspent_boxes_by_address(m_lend_addr))
    boxes.append(get_unspent_boxes_by_address(m_pool_addr))
    boxes.append(get_unspent_boxes_by_address(m_borrow_addr))
    boxes.append(get_unspent_boxes_by_address(m_interest_addr))
    token_ids = []
    for resp in boxes:
        if len(resp) != 0:
            token_ids.append(resp[0]["assets"][0]["tokenId"])
    return token_ids

def cancel_active_creations():
    allboxes = []
    allboxes.append(get_unspent_boxes_by_address(m_lend_addr))
    allboxes.append(get_unspent_boxes_by_address(m_pool_addr))
    allboxes.append(get_unspent_boxes_by_address(m_borrow_addr))
    allboxes.append(get_unspent_boxes_by_address(m_interest_addr))
    logger.info("Getting UTXO Binaries")
    binaries = []
    tokens = []
    for boxes in allboxes:
        for box in boxes:
            binaries.append(box_id_to_binary(box["boxId"]))
            if box["assets"]:
                tokens.append(
                    {
                        "tokenId": box["assets"][0]["tokenId"],
                        "amount": box["assets"][0]["amount"]
                    }
                )
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": node_address,
                    "value": 2000000 * len(binaries) - 1000000,
                    "assets": [],
                    "registers": {
                    }
                },
                {
                    "assetsToBurn": tokens
                }
            ],
            "fee": 1000000,
            "inputsRaw":
                binaries,
            "dataInputsRaw":
                []
        }
    sign_tx(transaction_to_sign)
    logger.info("Waiting for transactions to confirm, please do not terminate the program...")
    start_time = time.time()
    while count_mint_active() > 0:
        time.sleep(45)
        if (time.time() - start_time) > 900:
            logger.error("Waited 900 seconds, assumed failure, terminating bot.")
            clean_node()
            return False
        logger.info("Still waiting for transactions to confirm, please do not terminate the program...")
    return True