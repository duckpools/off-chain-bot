import json

from consts import TX_FEE, MIN_BOX_VALUE, MAX_BORROW_TOKENS, DOUBLE_SPENDING_ATTEMPT, ERROR, LargeMultiplier, \
    DEFAULT_BUFFER, MAX_NETWORK_FEE, SLIPPAGE, DEX_FEE_DENOM
from helpers.job_helpers import latest_pool_info, job_processor
from helpers.node_calls import tree_to_address, box_id_to_binary, sign_tx, current_height
from helpers.platform_functions import get_dex_box, get_pool_param_box, get_interest_box, get_logic_box, get_parent_box, \
    get_head_child
from helpers.serializer import encode_long, encode_long_tuple, encode_int_tuple, encode_long_pair, encode_coll_int
from logger import set_logger

logger = set_logger(__name__)


def find_quote_by_nft(pool, quote_nft):
    """Find the quote configuration matching the given quote NFT."""
    for quote in pool["quotes"]:
        if quote["quoteNFT"] == quote_nft:
            return quote
    return None


def calculate_secondary_collateral_value(secondary_dex_boxes, collateral_tokens, secondary_collateral_config):
    """
    Calculate the ERG value of secondary collateral tokens using their DEX boxes.
    Returns total ERG value and ordered asset amounts/IDs.

    IMPORTANT: ordered_amounts and ordered_asset_ids are returned in the order of
    secondary_collateral_config (which matches secondaryDexNfts order in logic script).
    The logic script validates that fOrderedQuotedAssetIds matches dexBox.tokens(2)._1
    for each index.
    """
    total_value = 0
    ordered_amounts = []
    ordered_asset_ids = []

    # Create a mapping from asset token ID to its amount in collateral
    token_amounts = {token["tokenId"]: token["amount"] for token in collateral_tokens}

    for i, secondary in enumerate(secondary_collateral_config):
        dex_box = secondary_dex_boxes[i]
        # dex_fee must come from DEX box R4, not config - logic script uses dexBox.R4[Int].get
        dex_fee = int(dex_box["additionalRegisters"]["R4"]["renderedValue"])

        # The asset ID must come from the DEX box's token(2), not the config
        # This is what the logic script validates: reportedAssetId == dexTokenId
        asset_id = dex_box["assets"][2]["tokenId"]

        # Get the amount of this token in the collateral
        input_amount = token_amounts.get(asset_id, 0)
        ordered_amounts.append(input_amount)
        ordered_asset_ids.append(asset_id)

        if input_amount > 0:
            dex_reserves_erg = dex_box["value"]
            dex_reserves_token = dex_box["assets"][2]["amount"]

            # Calculate collateral market value in ERG using DEX formula from logic_script
            # collateralMarketValue = (dexReservesErg * inputAmount * dexFee) /
            #   ((dexReservesToken + (dexReservesToken * Slippage / 100)) * DexFeeDenom +
            #   (inputAmount * dexFee))
            numerator = dex_reserves_erg * input_amount * dex_fee
            denominator = ((dex_reserves_token + (dex_reserves_token * SLIPPAGE // 100)) * DEX_FEE_DENOM +
                          (input_amount * dex_fee))
            collateral_market_value = numerator // denominator
            total_value += collateral_market_value

    return total_value, ordered_amounts, ordered_asset_ids


def calculate_aggregate_threshold(box_value, primary_threshold, secondary_values_and_thresholds, total_box_value):
    """
    Calculate the weighted aggregate threshold based on contribution of each asset.
    From logic_script:
    aggregateThresholdPrimarySum = (boxToQuote.value * LargeMultiplier * primaryThreshold) / totalBoxValue
    aggregateThresholdSecondarySum = sum of (collateralMarketValue * LargeMultiplier * threshold) / totalBoxValue
    aggregateThreshold = aggregateThresholdPrimarySum + aggregateThresholdSecondarySum
    validAggregateThreshold = aggregateThreshold / LargeMultiplier == max(fAggregateThreshold, 1001L)

    Note: box_value is the full boxToQuote.value (collateral_supplied), NOT reduced by MaxNetworkFee.
    The division by LargeMultiplier happens ONCE at the end on the total sum.
    """
    # Primary contribution - uses boxToQuote.value directly
    aggregate = (box_value * LargeMultiplier * primary_threshold) // total_box_value

    # Secondary contributions
    for value, threshold in secondary_values_and_thresholds:
        if value > 0:
            aggregate += (value * LargeMultiplier * threshold) // total_box_value

    # Single division at the end, matching: aggregateThreshold / LargeMultiplier
    return aggregate // LargeMultiplier


def bad_encode_arr(items):
    """Encode array of byte arrays (works up to size 9)."""
    resp = "1a0" + format(len(items), 'x')
    for item in items:
        resp += "20" + item
    return resp


def process_borrow_proxy_box_v1(pool, box, latest_tx, fee=TX_FEE):
    pool_box, borrowed = latest_pool_info(pool, latest_tx)

    collateral_supplied = box["value"] - MIN_BOX_VALUE - TX_FEE
    try:
        dex_box = get_dex_box(box["additionalRegisters"]["R8"]["renderedValue"])
    except Exception:
        return

    if not dex_box:
        logger.debug("No Dex Box Found")
        return

    parent_interest_box = get_parent_box(pool["parent"], pool["PARENT_NFT"])
    head_child_interest_box = get_head_child(pool["child"], pool["CHILD_NFT"], pool["parent"], pool["PARENT_NFT"], parent_interest_box)

    if not head_child_interest_box or not parent_interest_box:
        logger.warning("No Interest Box Found")
        return

    child_interest_length = len(json.loads(head_child_interest_box["additionalRegisters"]["R4"]["renderedValue"]))
    parent_interest_length = len(json.loads(parent_interest_box["additionalRegisters"]["R4"]["renderedValue"]))
    user_tree = box["additionalRegisters"]["R4"]["renderedValue"]
    amount_to_borrow = int(box["additionalRegisters"]["R5"]["renderedValue"])
    final_borrowed = borrowed + amount_to_borrow
    pool_param_box = get_pool_param_box(pool["parameter"], pool["PARAMETER_NFT"])
    net_height = current_height() - 20

    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": pool["pool"],
                    "value": pool_box["value"],
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
                            "amount": MAX_BORROW_TOKENS - final_borrowed
                        },
                        {
                            "tokenId": pool_box["assets"][3]["tokenId"],
                            "amount": pool_box["assets"][3]["amount"] - amount_to_borrow
                        },
                    ],
                    "registers": {
                    }
                },
                {
                    "address": pool["collateral"],
                    "value": collateral_supplied,
                    "assets": [
                        {
                            "tokenId": pool_box["assets"][2]["tokenId"],
                            "amount": amount_to_borrow
                        }
                    ],
                    "registers": {
                        "R4": box["additionalRegisters"]["R4"]["serializedValue"],
                        "R5": encode_int_tuple([parent_interest_length, child_interest_length - 1]),
                        "R6": box["additionalRegisters"]["R7"]["serializedValue"],
                        "R7": box["additionalRegisters"]["R8"]["serializedValue"],
                        "R8": box["additionalRegisters"]["R9"]["serializedValue"],
                        "R9": encode_long_pair(net_height + pool["proxy_forced_liquidation"], DEFAULT_BUFFER)
                    }
                },
                {
                    "address": tree_to_address(user_tree),
                    "value": MIN_BOX_VALUE - fee + TX_FEE,
                    "assets": [
                        {
                            "tokenId": pool_box["assets"][3]["tokenId"],
                            "amount": amount_to_borrow
                        }
                    ],
                    "registers": {
                        "R4": "0e20" + box["boxId"]
                    }
                }
            ],
            "fee": fee,
            "inputsRaw":
                [box_id_to_binary(pool_box["boxId"]), box_id_to_binary(box["boxId"])],
            "dataInputsRaw":
                [box_id_to_binary(dex_box["boxId"]), box_id_to_binary(parent_interest_box["boxId"]),
                 box_id_to_binary(head_child_interest_box["boxId"]), box_id_to_binary(pool_param_box["boxId"])]
        }

    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)

    obj = {"txId": tx_id,
           "finalBorrowed": final_borrowed}

    if tx_id != ERROR and tx_id != DOUBLE_SPENDING_ATTEMPT:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    elif tx_id == DOUBLE_SPENDING_ATTEMPT:
        logger.info("Double spend, trying with fee: %s", str(fee + 12))
        process_borrow_proxy_box(pool, box, latest_tx, fee + 12)
    else:
        logger.debug("Failed to submit transaction, attempting to refund")
        transaction_to_sign = \
            {
                "requests": [
                    {
                        "address": tree_to_address(user_tree),
                        "value": box["value"] - TX_FEE,
                        "assets": [
                        ],
                        "registers": {
                            "R4": "0e20" + box["boxId"]
                        }
                    }
                ],
                "fee": TX_FEE,
                "inputsRaw":
                    [box_id_to_binary(box["boxId"])],
                "dataInputsRaw":
                    [box_id_to_binary(dex_box["boxId"]), box_id_to_binary(head_child_interest_box["boxId"])]
            }

        logger.debug("Signing Transaction: %s",  json.dumps(transaction_to_sign))
        tx_id = sign_tx(transaction_to_sign)
        if tx_id != -1:
            logger.info("Successfully submitted refund transaction with ID: %s",  tx_id)
        else:
            logger.warning("Failed to process or refund transaction object: %s Failed Refund txID quoted as: %s",
                           json.dumps(transaction_to_sign), tx_id)
        return latest_tx
    return obj




def process_borrow_proxy_box_v2(pool, box, latest_tx, fee=TX_FEE):
    pool_box, borrowedTokens = latest_pool_info(pool, latest_tx)
    collateral_supplied = box["value"] - MIN_BOX_VALUE - TX_FEE
    interest_box = get_interest_box(pool["interest"], pool["INTEREST_NFT"])
    request_amounts = json.loads(box["additionalRegisters"]["R5"]["renderedValue"])
    amount_to_borrow = request_amounts[0]
    loanBorrowTokens = request_amounts[1]

    print(amount_to_borrow)
    print(loanBorrowTokens)

    user_tree = box["additionalRegisters"]["R4"]["renderedValue"]
    final_borrowed = borrowedTokens + loanBorrowTokens
    pool_param_box = get_pool_param_box(pool["parameter"], pool["PARAMETER_NFT"])

    # Read R8 to get the quoteNFT and find the matching quote
    user_quote_nft = box["additionalRegisters"]["R8"]["renderedValue"]
    quote = find_quote_by_nft(pool, user_quote_nft)
    if not quote:
        logger.warning("Quote NFT not found in pool configuration: %s", user_quote_nft)
        return

    # Get the primary DEX box
    primary_dex_nft = quote["primarySupportedCollateral"]["DEXNFT"]
    dex_box = get_dex_box(primary_dex_nft)
    logic_box = get_logic_box(quote["quoteScript"], quote["quoteNFT"])
    net_height = current_height() - 20

    # Get primary DEX values
    dex_initial_val = dex_box["value"]
    dex_tokens = dex_box["assets"][2]["amount"]
    # dex_fee must come from the DEX box R4, not the config - logic script uses primaryDexBox.R4[Int].get
    dex_fee = int(dex_box["additionalRegisters"]["R4"]["renderedValue"])

    # Get secondary DEX configuration
    secondary_collateral = quote.get("secondarySupportedCollateral", [])
    has_secondary = len(secondary_collateral) > 0

    # Get collateral tokens from proxy box (excluding ERG value)
    collateral_tokens = box.get("assets", [])

    # Fetch secondary DEX boxes if any
    secondary_dex_boxes = []
    if has_secondary:
        for secondary in secondary_collateral:
            secondary_dex_box = get_dex_box(secondary["DEXNFT"])
            if not secondary_dex_box:
                logger.warning("Secondary DEX box not found: %s", secondary["DEXNFT"])
                return
            secondary_dex_boxes.append(secondary_dex_box)

    # Calculate secondary collateral value in ERG
    secondary_erg_value = 0
    ordered_amounts = []
    ordered_asset_ids = []
    if has_secondary:
        secondary_erg_value, ordered_amounts, ordered_asset_ids = calculate_secondary_collateral_value(
            secondary_dex_boxes, collateral_tokens, secondary_collateral
        )

    # Calculate total box value for quote price calculation (from logic_script)
    # totalBoxValue = boxToQuote.value + collateralValueInErgs - MaximumNetworkFee
    # boxToQuote.value = collateral_supplied (the output collateral box value)
    # collateralValueInErgs = secondary_erg_value (computed from secondary tokens via DEX)
    total_box_value = collateral_supplied + secondary_erg_value - MAX_NETWORK_FEE

    # Calculate quote price using primary DEX (tokens received if we liquidate total collateral)
    # From logic_script: quotePrice = (yAssets * totalBoxValue * dexFee) /
    #   ((xAssets + (xAssets * Slippage / SlippageDenom)) * DexFeeDenom + (totalBoxValue * dexFee))
    # Use integer division (//) to match ErgoScript BigInt division behavior
    quote_price = (dex_tokens * total_box_value * dex_fee) // \
                  ((dex_initial_val + (dex_initial_val * SLIPPAGE // 100)) * DEX_FEE_DENOM +
                   (total_box_value * dex_fee))

    # Load iReport from logic box
    iReport = json.loads(logic_box["additionalRegisters"]["R4"]["renderedValue"])
    borrowLimit = iReport[0]
    penalty = iReport[3]
    minimumValue = iReport[4]
    bufferGap = iReport[5]

    # Get thresholds from logic box R6 - needed for both secondary and primary-only cases
    asset_thresholds = json.loads(logic_box["additionalRegisters"]["R6"]["renderedValue"])
    primary_threshold = asset_thresholds[0]

    # Calculate aggregate threshold
    if has_secondary:
        secondary_thresholds = asset_thresholds[1:]

        # Calculate ERG value for each secondary asset
        # Use the same values computed in calculate_secondary_collateral_value for consistency
        secondary_values_and_thresholds = []
        token_amounts = {token["tokenId"]: token["amount"] for token in collateral_tokens}
        for i, secondary in enumerate(secondary_collateral):
            dex_b = secondary_dex_boxes[i]
            # Use asset ID from DEX box, not config
            asset_id = dex_b["assets"][2]["tokenId"]
            input_amount = token_amounts.get(asset_id, 0)
            if input_amount > 0:
                dex_reserves_erg = dex_b["value"]
                dex_reserves_token = dex_b["assets"][2]["amount"]
                # Use dex_fee from DEX box R4, not config
                sec_dex_fee = int(dex_b["additionalRegisters"]["R4"]["renderedValue"])
                numerator = dex_reserves_erg * input_amount * sec_dex_fee
                denominator = ((dex_reserves_token + (dex_reserves_token * SLIPPAGE // 100)) * DEX_FEE_DENOM +
                              (input_amount * sec_dex_fee))
                sec_value = numerator // denominator
                secondary_values_and_thresholds.append((sec_value, secondary_thresholds[i] if i < len(secondary_thresholds) else primary_threshold))

        # box_value = boxToQuote.value = collateral_supplied (the actual collateral box value)
        # total_box_value = boxToQuote.value + collateralValueInErgs - MaxNetworkFee
        #                 = collateral_supplied + secondary_erg_value - MAX_NETWORK_FEE
        # Note: total_box_value already has the subtraction, so just pass it directly
        aggregateThreshold = calculate_aggregate_threshold(
            collateral_supplied, primary_threshold,
            secondary_values_and_thresholds, total_box_value
        )
    else:
        # Simple case: single collateral type (no secondary tokens)
        # aggregateThresholdPrimarySum = (boxToQuote.value * LargeMultiplier * primaryThreshold) / totalBoxValue
        # aggregateThreshold = aggregateThresholdPrimarySum / LargeMultiplier
        # Use integer division to match ErgoScript
        aggregateThreshold = (collateral_supplied * LargeMultiplier * primary_threshold) // total_box_value // LargeMultiplier

    # Build collateral box assets - include secondary tokens if present
    collateral_box_assets = [
        {
            "tokenId": pool_box["assets"][2]["tokenId"],
            "amount": loanBorrowTokens
        }
    ]
    # Add any secondary collateral tokens from the proxy box
    for token in collateral_tokens:
        collateral_box_assets.append({
            "tokenId": token["tokenId"],
            "amount": token["amount"]
        })

    # Build dataInputsRaw - add secondary DEX boxes if present
    data_inputs_raw = [
        box_id_to_binary(interest_box["boxId"]),
        box_id_to_binary(pool_param_box["boxId"]),
        box_id_to_binary(dex_box["boxId"])
    ]
    for sec_dex_box in secondary_dex_boxes:
        data_inputs_raw.append(box_id_to_binary(sec_dex_box["boxId"]))

    # Build R7 (ordered asset amounts) and R8 (ordered asset IDs) for logic box output
    # From logic_script: fOrderedAssetAmounts = outLogic.R7, fOrderedQuotedAssetIds = outLogic.R8
    if has_secondary:
        r7_value = encode_long_tuple(ordered_amounts)
        r8_value = bad_encode_arr(ordered_asset_ids)
    else:
        r7_value = "1100"  # Empty long array
        r8_value = "1a00"  # Empty byte array collection

    # R9 helper indices: [boxIndex, dexStartIndex]
    # boxIndex = 2 means OUTPUTS(1) which is the collateral box
    # dexStartIndex = 2 means CONTEXT.dataInputs(2) which is where the primary DEX is
    r9_indices = [2, 2]  # Collateral is output index 1 (1+1=2), primary DEX is data input index 2
    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": pool["pool"],
                    "value": pool_box["value"],
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
                            "amount": MAX_BORROW_TOKENS - final_borrowed
                        },
                        {
                            "tokenId": pool_box["assets"][3]["tokenId"],
                            "amount": pool_box["assets"][3]["amount"] - amount_to_borrow
                        },
                    ],
                    "registers": {
                        "R4": "0101",
                        "R5": "0101",
                        "R6": "0101",
                        "R7": "0101",
                        "R8": "0101",
                        "R9": "0101"
                    }
                },
                {
                    "address": pool["collateral"],
                    "value": collateral_supplied,
                    "assets": collateral_box_assets,
                    "registers": {
                        "R4": box["additionalRegisters"]["R4"]["serializedValue"],
                        "R5": box["additionalRegisters"]["R9"]["serializedValue"],
                        "R6": encode_long(100000000),
                        "R7": box["additionalRegisters"]["R8"]["serializedValue"],
                        "R8": box["additionalRegisters"]["R7"]["serializedValue"],
                        "R9": encode_long_tuple([aggregateThreshold, penalty, bufferGap, minimumValue, 0, current_height() + 5, iReport[7], iReport[8]]),
                    }
                },
                {
                    "address": tree_to_address(user_tree),
                    "value": MIN_BOX_VALUE - fee + TX_FEE,
                    "assets": [
                        {
                            "tokenId": pool_box["assets"][3]["tokenId"],
                            "amount": amount_to_borrow
                        }
                    ],
                    "registers": {
                        "R4": "0e20" + box["boxId"]
                    }
                },
                {
                    "address": quote["quoteScript"],
                    "value": MIN_BOX_VALUE,
                    "assets": [
                        {
                            "tokenId": logic_box["assets"][0]["tokenId"],
                            "amount": 1
                        }
                    ],
                    "registers": {
                        "R4": encode_long_tuple([borrowLimit, quote_price, aggregateThreshold, penalty, minimumValue, bufferGap, 0, iReport[7], iReport[8], iReport[9]]),
                        "R5": logic_box["additionalRegisters"]["R5"]["serializedValue"],
                        "R6": logic_box["additionalRegisters"]["R6"]["serializedValue"],
                        "R7": r7_value,
                        "R8": r8_value,
                        "R9": encode_coll_int(r9_indices)
                    }
                }
            ],
            "fee": fee,
            "inputsRaw":
                [box_id_to_binary(pool_box["boxId"]), box_id_to_binary(box["boxId"]), box_id_to_binary(logic_box["boxId"])],
            "dataInputsRaw": data_inputs_raw
        }
    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)

    obj = {"txId": tx_id,
           "finalBorrowed": final_borrowed}
    if tx_id != ERROR and tx_id != DOUBLE_SPENDING_ATTEMPT:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    elif tx_id == DOUBLE_SPENDING_ATTEMPT:
        logger.info("Double spend, trying with fee: %s", str(fee + 12))
        process_borrow_proxy_box(pool, box, latest_tx, fee + 12)
    else:
        logger.debug("Failed to submit transaction, attempting to refund")
        transaction_to_sign = \
            {
                "requests": [
                    {
                        "address": tree_to_address(user_tree),
                        "value": box["value"] - TX_FEE,
                        "assets": [
                        ],
                        "registers": {
                            "R4": "0e20" + box["boxId"]
                        }
                    }
                ],
                "fee": TX_FEE,
                "inputsRaw":
                    [box_id_to_binary(box["boxId"])],
                "dataInputsRaw":
                    [box_id_to_binary(dex_box["boxId"])]
            }

        logger.debug("Signing Transaction: %s",  json.dumps(transaction_to_sign))
        tx_id = sign_tx(transaction_to_sign)
        if tx_id != -1:
            logger.info("Successfully submitted refund transaction with ID: %s",  tx_id)
        else:
            logger.warning("Failed to process or refund transaction object: %s Failed Refund txID quoted as: %s",
                           json.dumps(transaction_to_sign), tx_id)
        return latest_tx
    return obj


def t_borrow_proxy_job(pool, curr_tx_obj):
    return job_processor(pool, pool["proxy_borrow"], curr_tx_obj, process_borrow_proxy_box_v1, process_borrow_proxy_box_v2,"borrow", 1535250)
