from client_consts import node_address
from consts import m_interest_addr, m_borrow_addr, m_lend_addr, m_pool_addr, m_param_addr, m_interest_param_addr, \
    m_currency_addr, m_logic_addr, PARAMETER_ADDRESS, SERIALIZED_SERVICE_ADDRESS, INTEREST_PARAMETER_ADDRESS, PROXY_LEND, \
    PROXY_WITHDRAW, PROXY_BORROW, PROXY_REPAY, PROXY_PARTIAL_REPAY, INTEREST_MULTIPLIER, BorrowTokenDenomination
from contracts.quacks import generate_pool_script, generate_repayment_script, generate_collateral_script, \
    generate_interest_script, generate_logic_script, generate_proxy_borrow_script
from helpers.explorer_calls import get_unspent_boxes_by_address
from helpers.node_calls import mint_token, box_id_to_binary, sign_tx, clean_node, address_to_tree, pay_token_to_address, \
    current_height
from helpers.platform_functions import update_pools_in_file
from helpers.serializer import hex_to_base58, bytesLike, blake2b256, encode_long_tuple, encode_long, encode_bigint
from logger import set_logger
import time

logger = set_logger(__name__)

creation_settings = {
    "AssetTicker": "QUACKS - Beta",
    "VersionId": "2.0",
    "Version": 2,
    "AssetDecimals": 2,
    "tokenId": "089990451bb430f05a85f4ef3bcb6ebf852b3d6ee68d86d78658b9ccef20074f",
    "liquidationThresholds": [1400],
    "serviceFeeThresholds": [2000, 200000],
    "liquidationAssets": None,
    "dexNFTs": ["46463b61bae37a3f2f0963798d57279167d82e17f78ccd0ccedec7e49cbdbbd1"],
    "dexFee": 30,
    "dexFeeSerialized": "04ca0f",
    "penalty": [300],
    "interestParams": [890,8000,0,0,53000,9840],
    "feeSettings": [2000, 200000, 160, 200, 250, 1],
}


def create_pool():
    startHeight = current_height()
    if len(count_mint_active()) > 0:
        logger.warning("There is an already an attempt to create pool, attempting to cancel...")
        if cancel_active_creations():
            create_pool()
        return
    logger.info("No active market creations found, attempting to mint tokens")
    mint_all_tokens(creation_settings)
    logger.info("Waiting for transactions to confirm, please do not terminate the program...")
    start_time = time.time()
    active_mints = count_mint_active()
    while len(active_mints) < 8:
        print(active_mints)
        time.sleep(45)
        if (time.time() - start_time) > 900:
            clean_node(3000000)
            logger.error("Waited 900 seconds, assumed failure, terminating bot.")
            return
        logger.info("Still waiting for transactions to confirm, please do not terminate the program...")
        active_mints = count_mint_active()
    lend_token_id, pool_nft, borrow_token_id, interest_nft, parameter_nft, interest_parameter_nft, logic_nft, _ = active_mints
    print(active_mints)
    f_pool_nft = hex_to_base58(pool_nft)
    f_interest_nft = hex_to_base58(interest_nft)
    f_parameter_nft = hex_to_base58(parameter_nft)
    f_interest_parameter_nft = hex_to_base58(interest_parameter_nft)
    f_currency_id = hex_to_base58(creation_settings["tokenId"])
    repayment_address = generate_repayment_script(f_pool_nft)
    f_dex_nft = hex_to_base58(creation_settings["dexNFTs"][0])
    f_borrow_token = hex_to_base58(borrow_token_id)
    print(repayment_address)
    f_repayment_address = hex_to_base58(blake2b256(bytesLike(address_to_tree(repayment_address))))
    collateral_address = generate_collateral_script(f_repayment_address, f_interest_nft, f_currency_id)
    print(collateral_address)
    f_collateral_address = hex_to_base58(blake2b256(bytesLike(address_to_tree(collateral_address))))
    pool_address = generate_pool_script(f_collateral_address, f_interest_nft, f_parameter_nft)
    print(pool_address)
    interest_address = generate_interest_script(f_pool_nft, f_interest_parameter_nft)
    print(interest_address)
    logic_address = generate_logic_script()
    proxy_borrow_address = generate_proxy_borrow_script(f_collateral_address, f_pool_nft, f_borrow_token, f_currency_id)
    print(proxy_borrow_address)
    logger.info("Attempting to bootstrap contracts...")
    logger.info("Pool contract...")
    bootstrap_pool_box(pool_address, pool_nft, lend_token_id, borrow_token_id)
    logger.info("Interest Param Contract...")
    bootstrap_interest_parameter_box(interest_parameter_nft)
    logger.info("Parameter Param Contract...")
    bootstrap_parameter_box(parameter_nft, logic_nft)
    logger.info("Interest box Contract...")
    bootstrap_interest_box(interest_address, interest_nft)
    logger.info("Logic box Contract...")
    bootstrap_logic_box(logic_address, logic_nft, creation_settings)
    logger.info("Waiting for transactions to confirm, please do not terminate the program...")
    start_time = time.time()
    while not (allAddressesWithBoxes([pool_address, INTEREST_PARAMETER_ADDRESS, PARAMETER_ADDRESS, interest_address], startHeight)):
        if (time.time() - start_time) > 900:
            clean_node(3000000)
            logger.error("Waited 900 seconds, assumed failure, terminating bot.")
            return
        logger.info("Still waiting for transactions to confirm, please do not terminate the program...")

    pool = {
        "is_Erg": False,
        "thresholds": creation_settings["serviceFeeThresholds"],
        "liquidation_threshold": creation_settings["liquidationThresholds"],
        "proxy_forced_liquidation": 65520,
        "version": creation_settings["Version"],

        # SPF MAIN ADDRESSES
        "pool": pool_address,
        "collateral": collateral_address,
        "repayment": repayment_address,
        "interest": interest_address,

        # SPF Proxy Addresses
        "proxy_lend": PROXY_LEND,
        "proxy_withdraw": PROXY_WITHDRAW,
        "proxy_borrow": proxy_borrow_address,
        "proxy_repay": PROXY_REPAY,
        "proxy_partial_repay": PROXY_PARTIAL_REPAY,

        # SPF Param Addresses
        "parameter": PARAMETER_ADDRESS,
        "interest_parameter": INTEREST_PARAMETER_ADDRESS,

        # SPF Token IDs
        "POOL_NFT": pool_nft,
        "CURRENCY_ID": creation_settings["tokenId"],
        "INTEREST_NFT": interest_nft,
        "PARAMETER_NFT": parameter_nft,
        "INTEREST_PARAMETER_NFT": interest_parameter_nft,
        "LEND_TOKEN": lend_token_id,

        # Quotes
        "quotes": [{
            "quoteNFT": logic_nft,
            "quoteScript": logic_address,
            "primarySupportedCollateral": {
                "DEXNFT": creation_settings["dexNFTs"][0],
                "dexFee": creation_settings["dexFee"],
                "dexFeeSerialized": creation_settings["dexFeeSerialized"]
            },
            "secondarySupportedCollateral": []
        }]
    }
    update_pools_in_file(pool)
    print(active_mints, repayment_address, collateral_address, pool_address)


def mint_pool_nft(assetTicker, VersionId):
    name = f"Pool NFT {assetTicker}-{VersionId}"
    description = f"duckpools v2 Pool NFT for {assetTicker} pool"
    mint_token(m_pool_addr, name, description, 0, 1)

def mint_lend_token(assetTicker, VersionId, decimals, amount=9000000000000010):
    name = f"Lend Token {assetTicker}-{VersionId}"
    description = f"duckpools v2 Lend Token for {assetTicker} pool"
    mint_token(m_lend_addr, name, description, decimals, amount)

def mint_borrow_token(assetTicker, VersionId):
    name = f"Borrow Token {assetTicker}-{VersionId}"
    description = f"duckpools v2 Borrow Token for {assetTicker} pool"
    mint_token(m_borrow_addr, name, description, 9, 900000000000000000)

def mint_interest_token(assetTicker, VersionId):
    name = f"Interest NFT {assetTicker}-{VersionId}"
    description = f"duckpools v2 Interest Token for {assetTicker} pool"
    mint_token(m_interest_addr, name, description, 0, 1)

def mint_param_token(assetTicker, VersionId):
    name = f"Pool Parameter NFT {assetTicker}-{VersionId}"
    description = f"duckpools v2 Pool Parameter Token for {assetTicker} pool"
    mint_token(m_param_addr, name, description, 0, 1)

def mint_interest_param_token(assetTicker, VersionId):
    name = f"Interest Parameter NFT {assetTicker}-{VersionId}"
    description = f"duckpools v2 Interest Parameter for {assetTicker} pool"
    mint_token(m_interest_param_addr, name, description, 0, 1)

def mint_logic_nft(assetTicker, VersionId):
    name = f"Logic NFT {assetTicker}-{VersionId}"
    description = f"duckpools v2 Logic NFT for {assetTicker} pool"
    mint_token(m_logic_addr, name, description, 0, 10, ergValue=11000000)

def mint_all_tokens(creation_settings):
    assetTicker = creation_settings["AssetTicker"]
    VersionId = creation_settings["VersionId"]
    assetDecimals = creation_settings["AssetDecimals"]
    mint_pool_nft(assetTicker, VersionId)
    time.sleep(5)
    mint_lend_token(assetTicker, VersionId, assetDecimals)
    time.sleep(5)
    mint_borrow_token(assetTicker, VersionId)
    time.sleep(5)
    mint_interest_token(assetTicker, VersionId)
    time.sleep(5)
    mint_param_token(assetTicker, VersionId)
    time.sleep(5)
    mint_interest_param_token(assetTicker, VersionId)
    time.sleep(5)
    mint_logic_nft(assetTicker, VersionId)
    time.sleep(5)
    pay_token_to_address(m_currency_addr, creation_settings["tokenId"], 10)



def get_mint_boxes():
    boxes = []
    boxes.append(get_unspent_boxes_by_address(m_lend_addr))
    time.sleep(2)
    boxes.append(get_unspent_boxes_by_address(m_pool_addr))
    time.sleep(2)
    boxes.append(get_unspent_boxes_by_address(m_borrow_addr))
    time.sleep(2)
    boxes.append(get_unspent_boxes_by_address(m_interest_addr))
    time.sleep(2)
    boxes.append(get_unspent_boxes_by_address(m_param_addr))
    time.sleep(2)
    boxes.append(get_unspent_boxes_by_address(m_interest_param_addr))
    time.sleep(2)
    boxes.append(get_unspent_boxes_by_address(m_logic_addr))
    time.sleep(2)
    boxes.append(get_unspent_boxes_by_address(m_currency_addr))
    return boxes

def allAddressesWithBoxes(addrList, cutoff=0):
    for addr in addrList:
        time.sleep(2)
        boxes = get_unspent_boxes_by_address(addr)
        print(boxes)
        if len(boxes) == 0 or int(boxes[0]["creationHeight"]) < cutoff:
            return False
    return True


def count_mint_active():
    boxes = get_mint_boxes()
    token_ids = []
    for resp in boxes:
        if len(resp) != 0:
            token_ids.append(resp[0]["assets"][0]["tokenId"])
    return token_ids

def cancel_active_creations():
    boxes= get_mint_boxes()
    logger.info("Getting UTXO Binaries")
    binaries = []
    tokens = []
    tokens_to_keep = []
    for boxes in boxes:
        for box in boxes:
            binaries.append(box_id_to_binary(box["boxId"]))
            if box["assets"][0]["tokenId"] != creation_settings["tokenId"]:
                tokens_to_keep.append(
                    {
                        "tokenId": box["assets"][0]["tokenId"],
                        "amount": box["assets"][0]["amount"]
                    }
                )
            elif box["assets"]:
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
                    "assets": tokens_to_keep,
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
    while len(count_mint_active()) > 0:
        time.sleep(45)
        if (time.time() - start_time) > 900:
            logger.error("Waited 900 seconds, assumed failure, terminating bot.")
            clean_node(3000000)
            return False
        logger.info("Still waiting for transactions to confirm, please do not terminate the program...")
    return True

def bootstrap_pool_box(pool_address, pool_nft, lend_token_id, borrow_token_id):
    pool_nft_utxo = get_unspent_boxes_by_address(m_pool_addr)[0]
    lend_token_utxo = get_unspent_boxes_by_address(m_lend_addr)[0]
    borrow_token_utxo = get_unspent_boxes_by_address(m_borrow_addr)[0]
    currency_token_utxo = get_unspent_boxes_by_address(m_currency_addr)[0]
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": pool_address,
                    "value": 1000000,
                    "assets": [
                        {
                            "tokenId": pool_nft,
                            "amount": 1
                        },
                        {
                            "tokenId": lend_token_id,
                            "amount": 9000000000000000
                        },
                        {
                            "tokenId": borrow_token_id,
                            "amount": 9000000000000000
                        },
                        {
                            "tokenId": creation_settings["tokenId"],
                            "amount": 10
                        }
                    ],
                    "registers": {
                    }
                }
            ],
            "fee": 1000000,
            "inputsRaw":
                [box_id_to_binary(pool_nft_utxo["boxId"]), box_id_to_binary(lend_token_utxo["boxId"]), box_id_to_binary(borrow_token_utxo["boxId"]), box_id_to_binary(currency_token_utxo["boxId"])],
            "dataInputsRaw":
                []
        }
    sign_tx(transaction_to_sign)


def bootstrap_interest_box(interest_address, interest_nft):
    interst_nft_utxo = get_unspent_boxes_by_address(m_interest_addr)[0]
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": interest_address,
                    "value": 1000000,
                    "assets": [
                        {
                            "tokenId": interest_nft,
                            "amount": 1
                        }
                    ],
                    "registers": {
                        "R4": encode_long(current_height() - 2),
                        "R5": encode_bigint(BorrowTokenDenomination)
                    }
                }
            ],
            "fee": 1000000,
            "inputsRaw":
                [box_id_to_binary(interst_nft_utxo["boxId"])],
            "dataInputsRaw":
                []
        }
    sign_tx(transaction_to_sign)

def bad_encode_arr(items):
    #works up to size 4
    resp = "1a0" + str(len(items))
    for item in items:
        resp += "20" + item
    return resp

def bootstrap_logic_box(address, nft, creation):
    logic_nft_utxo = get_unspent_boxes_by_address(m_logic_addr)[0]

    # Create 10 quote boxes, each with 1 NFT
    output_boxes = []
    for _ in range(10):
        output_boxes.append({
            "address": address,
            "value": 1000000,
            "assets": [
                {
                    "tokenId": nft,
                    "amount": 1
                }
            ],
            "registers": {
                "R4": encode_long_tuple([100000000000, 0, 0, 30, 15000000, 8, 0, 50, 15, 20000000]),
                "R5": bad_encode_arr(creation["dexNFTs"]),
                "R6": encode_long_tuple(creation["liquidationThresholds"])
            }
        })

    transaction_to_sign = {
        "requests": output_boxes,
        "fee": 1000000,
        "inputsRaw": [box_id_to_binary(logic_nft_utxo["boxId"])],
        "dataInputsRaw": []
    }
    sign_tx(transaction_to_sign)


def bootstrap_parameter_box(parameter_token, logic_nft):
    parameter_token_utxo = get_unspent_boxes_by_address(m_param_addr)[0]
    r5 = "1a01010a"
    if creation_settings["liquidationAssets"]:
        r5 = encode_long_tuple(creation_settings["liquidationAssets"])
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": PARAMETER_ADDRESS,
                    "value": 1000000,
                    "assets": [
                        {
                            "tokenId": parameter_token,
                            "amount": 1
                        }
                    ],
                    "registers": {
                        "R4": "1a0120" + logic_nft,
                        "R5": SERIALIZED_SERVICE_ADDRESS,
                        "R6": encode_long_tuple(creation_settings["feeSettings"])
                    }
                }
            ],
            "fee": 1000000,
            "inputsRaw":
                [box_id_to_binary(parameter_token_utxo["boxId"])],
            "dataInputsRaw":
                []
        }
    print(transaction_to_sign)
    sign_tx(transaction_to_sign)

def bootstrap_interest_parameter_box(token):
    token_utxo = get_unspent_boxes_by_address(m_interest_param_addr)[0]
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": INTEREST_PARAMETER_ADDRESS,
                    "value": 1000000,
                    "assets": [
                        {
                            "tokenId": token,
                            "amount": 1
                        }
                    ],
                    "registers": {
                        "R4": encode_long_tuple(creation_settings["interestParams"])
                    }
                }
            ],
            "fee": 1000000,
            "inputsRaw":
                [box_id_to_binary(token_utxo["boxId"])],
            "dataInputsRaw":
                []
        }
    print(transaction_to_sign)
    sign_tx(transaction_to_sign)


def clear_logic_mint_boxes(currency_token_id):
    """
    Clear any old/failed logic box mint attempts from the mint address.
    Burns any tokens except the currency token.

    Args:
        currency_token_id: The currency token ID to preserve (won't be burned)

    Returns:
        bool: True if cleanup was successful or no boxes to clean, False on timeout
    """
    boxes = get_unspent_boxes_by_address(m_logic_addr)

    if not boxes:
        logger.info("No logic boxes to clear")
        return True

    logger.info(f"Found {len(boxes)} box(es) at logic mint address, attempting to clear...")

    binaries = []
    tokens_to_burn = []
    tokens_to_keep = []

    for box in boxes:
        binaries.append(box_id_to_binary(box["boxId"]))
        if box.get("assets"):
            for asset in box["assets"]:
                # Keep currency token, burn everything else
                if asset["tokenId"] != currency_token_id:
                    tokens_to_burn.append({
                        "tokenId": asset["tokenId"],
                        "amount": asset["amount"]
                    })
                else:
                    tokens_to_keep.append({
                        "tokenId": asset["tokenId"],
                        "amount": asset["amount"]
                    })

    if not binaries:
        return True

    transaction_to_sign = {
        "requests": [
            {
                "address": node_address,
                "value": 2000000 * len(binaries) - 1000000,
                "assets": tokens_to_keep,
                "registers": {}
            }
        ],
        "fee": 1000000,
        "inputsRaw": binaries,
        "dataInputsRaw": []
    }

    # Add burn request if there are tokens to burn
    if tokens_to_burn:
        transaction_to_sign["requests"].append({
            "assetsToBurn": tokens_to_burn
        })

    sign_tx(transaction_to_sign)

    logger.info("Waiting for cleanup transaction to confirm...")
    start_time = time.time()
    while len(get_unspent_boxes_by_address(m_logic_addr)) > 0:
        time.sleep(5)
        if (time.time() - start_time) > 300:
            logger.error("Waited 300 seconds for cleanup, assumed failure")
            return False
        logger.info("Still waiting for cleanup confirmation...")

    logger.info("Logic mint boxes cleared successfully")
    return True


def bootstrap_logic_box_flow(creation_settings, wait_timeout=900):
    """
    Complete flow to bootstrap a logic box:
    1. Clear any old boxes at the logic mint address
    2. Mint the logic NFT to the mint address
    3. Wait for confirmation
    4. Generate the logic script
    5. Call bootstrap_logic_box() to sign and submit the transaction

    Args:
        creation_settings: Dictionary containing pool configuration with keys:
            - AssetTicker: Asset ticker for NFT name (e.g., "QUACKS - Beta")
            - VersionId: Version ID for NFT name (e.g., "2.0")
            - tokenId: Currency token ID to preserve during cleanup
            - dexNFTs: Array of DEX NFT IDs (hex strings without 0x prefix)
            - liquidationThresholds: Array of liquidation threshold values
        wait_timeout: Maximum seconds to wait for confirmation (default: 900)

    Returns:
        Tuple of (logic_nft_id, logic_address) on success

    Raises:
        TimeoutError: If mint confirmation takes longer than wait_timeout
        ValueError: If no boxes found after minting

    Example:
        settings = {
            "AssetTicker": "QUACKS - Beta",
            "VersionId": "2.0",
            "tokenId": "089990451bb430f05a85f4ef3bcb6ebf852b3d6ee68d86d78658b9ccef20074f",
            "dexNFTs": ["46463b61bae37a3f2f0963798d57279167d82e17f78ccd0ccedec7e49cbdbbd1"],
            "liquidationThresholds": [1400]
        }
        nft_id, address = bootstrap_logic_box_flow(settings)
    """
    asset_ticker = creation_settings["AssetTicker"]
    version_id = creation_settings["VersionId"]

    logger.info(f"Starting complete logic box bootstrap flow for {asset_ticker}-{version_id}")

    # Step 1: Clear any old boxes at the mint address
    logger.info("Step 1: Checking for old boxes at logic mint address...")
    if not clear_logic_mint_boxes(creation_settings["tokenId"]):
        logger.warning("Failed to clear old boxes, but continuing anyway...")

    # Step 2: Mint the logic NFT
    logger.info("Step 2: Minting logic NFT...")
    mint_logic_nft(asset_ticker, version_id)
    time.sleep(5)  # Give it a moment to propagate

    # Step 3: Wait for confirmation
    logger.info("Step 3: Waiting for mint transaction to confirm...")
    start_time = time.time()
    logic_nft_id = None

    while logic_nft_id is None:
        time.sleep(5)
        if (time.time() - start_time) > wait_timeout:
            logger.error(f"Waited {wait_timeout} seconds, mint transaction did not confirm")
            clean_node(3000000)
            raise TimeoutError(f"Logic NFT mint did not confirm within {wait_timeout} seconds")

        boxes = get_unspent_boxes_by_address(m_logic_addr)
        if boxes and boxes[0].get("assets") and len(boxes[0]["assets"]) > 0:
            logic_nft_id = boxes[0]["assets"][0]["tokenId"]
            logger.info(f"Logic NFT minted with ID: {logic_nft_id}")
        else:
            logger.info("Still waiting for mint confirmation...")

    # Step 4: Generate the logic script
    logger.info("Step 4: Generating logic script...")
    logic_address = generate_logic_script()
    logger.info(f"Generated logic address: {logic_address}")

    # Step 5: Bootstrap the logic box using the existing function
    logger.info("Step 5: Bootstrapping logic box...")
    bootstrap_logic_box(logic_address, logic_nft_id, creation_settings)

    logger.info(f"Logic box bootstrap complete!")
    logger.info(f"  NFT ID: {logic_nft_id}")
    logger.info(f"  Address: {logic_address}")

    return logic_nft_id, logic_address