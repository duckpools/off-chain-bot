"""
Auto Balance Module for Token Pools

This module handles automatic rebalancing of collateral boxes within groups.
When collateral boxes in the same group have prices that differ by more than 10%,
a rebalancing transaction is constructed to redistribute collateral.

Autobalance Box Structure (at auto_balance_address):
    - R4: Coll[Byte] (32 bytes / 64 hex chars) - Spend NFT ID to match against collateral R8[:64]
    - R5: Coll[Coll[Byte]] - Array of special bytes, each entry groups collateral boxes
          whose R8[64:] (last 8 bytes / 16 hex chars) matches

Collateral Box R8 Structure:
    - First 32 bytes (64 hex chars): Spend NFT ID
    - Last 8 bytes (16 hex chars): Special bytes linking to group

Required pool configuration:
    - "auto_balance_address": Address where autobalance configuration boxes are located
    - "collateral": Address where collateral boxes are located
    - "version": Must be 2
"""

import json

from consts import SLIPPAGE, DEX_FEE_DENOM, MAX_NETWORK_FEE, TX_FEE, MIN_BOX_VALUE, ERROR, LargeMultiplier
from helpers.explorer_calls import get_unspent_boxes_by_address
from helpers.node_calls import box_id_to_binary, sign_tx, current_height
from helpers.platform_functions import get_dex_box, get_interest_box, get_logic_box
from helpers.serializer import encode_long_tuple, encode_coll_int, encode_long, parse_coll_bytes
from logger import set_logger

logger = set_logger(__name__)

# Threshold for triggering rebalance (10% difference)
BALANCE_THRESHOLD_PERCENT = 0.10


def bad_encode_arr(items):
    """Encode array of byte arrays (Coll[Coll[Byte]]) for register values."""
    resp = "1a0" + format(len(items), 'x')
    for item in items:
        resp += "20" + item
    return resp


def merge_token_arrays(existing_tokens, tokens_to_add):
    """
    Merge token arrays, adding amounts to existing tokens or appending new ones.

    Args:
        existing_tokens: List of token dicts from the destination box
        tokens_to_add: List of token dicts to add/merge

    Returns:
        List of merged token dicts with updated amounts
    """
    result = {t["tokenId"]: int(t["amount"]) for t in existing_tokens}
    for token in tokens_to_add:
        token_id = token["tokenId"]
        amount = int(token["amount"])
        if token_id in result:
            result[token_id] += amount
        else:
            result[token_id] = amount
    return [{"tokenId": k, "amount": v} for k, v in result.items() if v > 0]


def get_autobalance_boxes(pool):
    """
    Fetch all autobalance configuration boxes from the configured address.

    Args:
        pool: Pool configuration dict

    Returns:
        List of autobalance boxes, or empty list if address not configured
    """
    auto_balance_address = pool.get("auto_balance_address")
    if not auto_balance_address:
        return []

    try:
        boxes = get_unspent_boxes_by_address(auto_balance_address)
        return boxes
    except Exception as e:
        logger.error("Error fetching autobalance boxes: %s", str(e))
        return []


def get_collateral_boxes_for_spend_nft(pool, spend_nft_id):
    """
    Get all active collateral boxes that reference the given spend NFT in R8.

    The collateral box R8 contains:
        - First 32 bytes (64 hex chars): Spend NFT ID
        - Last 8 bytes (16 hex chars): Special bytes for grouping

    Args:
        pool: Pool configuration dict
        spend_nft_id: The spend NFT token ID to match against R8[:64]

    Returns:
        List of collateral boxes with matching spend NFT
    """
    collateral_address = pool.get("collateral")
    if not collateral_address:
        return []

    try:
        all_collateral_boxes = get_unspent_boxes_by_address(collateral_address, limit=200)
        matching_boxes = []

        for box in all_collateral_boxes:
            try:
                # R8 contains spendNFT (32 bytes) + specialBytes (8 bytes)
                # Extract first 32 bytes (64 hex chars) for matching
                box_r8 = box["additionalRegisters"]["R8"]["renderedValue"]
                box_spend_nft = box_r8[:64]  # First 32 bytes in hex
                if box_spend_nft == spend_nft_id:
                    matching_boxes.append(box)
            except (KeyError, TypeError):
                continue

        return matching_boxes
    except Exception as e:
        logger.error("Error fetching collateral boxes: %s", str(e))
        return []


def parse_special_bytes_list(r5_value):
    """
    Parse R5 register value containing Coll[Coll[Byte]].

    R5 is a nested array where each inner array contains special bytes
    that identify a group of collateral boxes.

    The rendered value for Coll[Coll[Byte]] comes as a bracket array with
    comma-separated hex strings like "[019bc6ca0c2d6e1c, abcd1234...]"
    which is not valid JSON (hex strings are unquoted).

    Args:
        r5_value: The R5 register value (bracket array format or list)

    Returns:
        List of special bytes strings (each 16 hex chars representing 8 bytes)
    """
    try:
        return parse_coll_bytes(r5_value)
    except Exception as e:
        logger.error("Error parsing special bytes from R5: %s", str(e))
        return []


def group_collateral_by_special_bytes(collateral_boxes, special_bytes_list):
    """
    Group collateral boxes by their special bytes (R8 suffix).

    Each collateral box's R8 register contains:
        - First 64 hex chars: Spend NFT ID
        - Last 16 hex chars: Special bytes for grouping

    Boxes are grouped together if their special bytes match one of the
    entries in the special_bytes_list from the autobalance box R5.

    Args:
        collateral_boxes: List of collateral boxes (already filtered by spend NFT)
        special_bytes_list: List of special bytes strings from autobalance box R5

    Returns:
        Dict mapping special_bytes -> list of collateral boxes in that group
    """
    groups = {sb: [] for sb in special_bytes_list}

    for box in collateral_boxes:
        try:
            # Extract special bytes from R8 (last 16 hex chars = 8 bytes)
            box_r8 = box["additionalRegisters"]["R8"]["renderedValue"]
            box_special_bytes = box_r8[64:]  # Last 8 bytes in hex

            # Check if this box belongs to any group
            if box_special_bytes in groups:
                groups[box_special_bytes].append(box)
        except (KeyError, TypeError):
            continue

    return groups


def find_quote_for_collateral(pool, collateral_box):
    """
    Find the quote configuration for a collateral box based on its R7 quote NFT.

    Args:
        pool: Pool configuration dict
        collateral_box: The collateral box

    Returns:
        Quote configuration dict, or None if not found
    """
    try:
        quote_nft = collateral_box["additionalRegisters"]["R7"]["renderedValue"]
        for quote in pool.get("quotes", []):
            if quote["quoteNFT"] == quote_nft:
                return quote
        return None
    except (KeyError, TypeError):
        return None


def price_collateral_box(collateral_box, pool, quote):
    """
    Calculate the price/value of a collateral box in quote tokens.

    Pricing follows the v2 pool pattern:
    1. Get ERG value from collateral box
    2. Convert secondary collateral tokens to ERG value via their DEX boxes
    3. Calculate total ERG value (minus network fee)
    4. Convert total ERG to quote tokens via primary DEX

    Args:
        collateral_box: The collateral box to price
        pool: Pool configuration
        quote: Quote configuration for this collateral

    Returns:
        int: Price value in quote tokens, or None on error
    """
    try:
        # Get primary DEX box
        primary_dex_nft = quote["primarySupportedCollateral"]["DEXNFT"]
        dex_box = get_dex_box(primary_dex_nft)
        if not dex_box:
            logger.error("Could not find primary DEX box for pricing")
            return None

        # Read DEX values
        dex_initial_val = dex_box["value"]
        dex_tokens = dex_box["assets"][2]["amount"]
        dex_fee = int(dex_box["additionalRegisters"]["R4"]["renderedValue"])

        # Get collateral value (ERG in the box)
        collateral_value = collateral_box["value"]

        # Handle secondary collateral if present
        secondary_erg_value = 0
        secondary_collateral_config = quote.get("secondarySupportedCollateral", [])
        collateral_tokens = collateral_box["assets"][1:] if len(collateral_box["assets"]) > 1 else []

        if secondary_collateral_config and collateral_tokens:
            token_amounts = {token["tokenId"]: token["amount"] for token in collateral_tokens}

            for secondary in secondary_collateral_config:
                sec_dex_box = get_dex_box(secondary["DEXNFT"])
                if not sec_dex_box:
                    continue

                asset_id = sec_dex_box["assets"][2]["tokenId"]
                input_amount = token_amounts.get(asset_id, 0)

                if input_amount > 0:
                    sec_dex_fee = int(sec_dex_box["additionalRegisters"]["R4"]["renderedValue"])
                    sec_dex_reserves_erg = sec_dex_box["value"]
                    sec_dex_reserves_token = sec_dex_box["assets"][2]["amount"]

                    sec_value = (sec_dex_reserves_erg * input_amount * sec_dex_fee) // \
                        (((sec_dex_reserves_token * (100 + SLIPPAGE)) // 100) * DEX_FEE_DENOM +
                         (input_amount * sec_dex_fee))
                    secondary_erg_value += sec_value

        # Calculate total box value
        total_box_value = collateral_value + secondary_erg_value - MAX_NETWORK_FEE

        # Calculate quote price (value in quote tokens)
        quote_price = (dex_tokens * total_box_value * dex_fee) // \
            (((dex_initial_val * (100 + SLIPPAGE)) // 100) * DEX_FEE_DENOM +
             (total_box_value * dex_fee))

        return quote_price

    except Exception as e:
        logger.error("Error pricing collateral box: %s", str(e))
        return None


def check_balance_threshold(prices):
    """
    Check if any two prices in a group differ by more than 10%.

    Args:
        prices: Dict mapping box_id -> price value

    Returns:
        Tuple of (needs_rebalance: bool, imbalanced_box_ids: list)
            - needs_rebalance: True if any pair differs by more than 10%
            - imbalanced_box_ids: List of all box IDs in the imbalanced group
    """
    if len(prices) < 2:
        return False, []

    price_list = list(prices.items())
    imbalanced = False

    # Compare all pairs
    for i in range(len(price_list)):
        for j in range(i + 1, len(price_list)):
            box_id_1, price_1 = price_list[i]
            box_id_2, price_2 = price_list[j]

            if price_1 <= 0 or price_2 <= 0:
                continue

            min_price = min(price_1, price_2)
            diff_ratio = abs(price_1 - price_2) / min_price

            if diff_ratio > BALANCE_THRESHOLD_PERCENT:
                imbalanced = True
                logger.debug(
                    "Imbalance detected: box %s (price=%d) vs box %s (price=%d), diff=%.2f%%",
                    box_id_1, price_1, box_id_2, price_2, diff_ratio * 100
                )
                break

        if imbalanced:
            break

    if imbalanced:
        return True, list(prices.keys())
    return False, []


def construct_autobalance_transaction(pool, autobalance_box, imbalanced_boxes, group_boxes, quote):
    """
    Build and submit a transaction to redistribute collateral between boxes.

    Uses the adjustCollateral contract path with NFT proof authorization.
    Redistributes assets from higher-value to lower-value collateral box to reach midpoint.

    Transaction structure:
        Inputs: [autobalance_box, collateral_1, collateral_2, logic_box_1, logic_box_2]
        Outputs: [quote_1, collateral_1, quote_2, collateral_2, autobalance_box]

    Args:
        pool: Pool configuration
        autobalance_box: The autobalance configuration box (NFT proof)
        imbalanced_boxes: List of box IDs that need rebalancing
        group_boxes: List of actual collateral box objects in the group
        quote: Quote configuration

    Returns:
        Transaction ID on success, None on failure
    """
    try:
        # Ensure we have exactly 2 collateral boxes
        if len(group_boxes) != 2:
            logger.warning("Auto-balance requires exactly 2 collateral boxes, got %d", len(group_boxes))
            return None

        collateral_1 = group_boxes[0]
        collateral_2 = group_boxes[1]

        # Price both collateral boxes
        price_1 = price_collateral_box(collateral_1, pool, quote)
        price_2 = price_collateral_box(collateral_2, pool, quote)

        if price_1 is None or price_2 is None:
            logger.error("Failed to price collateral boxes")
            return None

        logger.debug("Collateral prices: box1=%d, box2=%d", price_1, price_2)

        # Identify higher and lower value boxes
        if price_1 >= price_2:
            high_box, low_box = collateral_1, collateral_2
            high_price, low_price = price_1, price_2
        else:
            high_box, low_box = collateral_2, collateral_1
            high_price, low_price = price_2, price_1

        # Calculate redistribution to reach midpoint
        midpoint = (high_price + low_price) // 2
        reduction_amount = high_price - midpoint

        # Calculate reduction percentage (as fraction with high precision)
        # reduction_pct = reduction_amount / high_price
        # We'll use this to proportionally reduce ERG and tokens

        high_value = high_box["value"]
        low_value = low_box["value"]

        # ERG to transfer (proportional to price reduction, keeping MIN_BOX_VALUE)
        # reduction_pct = reduction_amount / high_price
        erg_to_transfer = ((high_value - MIN_BOX_VALUE) * reduction_amount) // high_price

        # Ensure boxes maintain minimum value
        if high_value - erg_to_transfer < MIN_BOX_VALUE:
            erg_to_transfer = high_value - MIN_BOX_VALUE

        # Get tokens from both boxes (skip index 0 which is borrow token)
        high_tokens = high_box["assets"][1:] if len(high_box["assets"]) > 1 else []
        low_tokens = low_box["assets"][1:] if len(low_box["assets"]) > 1 else []

        # Calculate tokens to transfer from high to low
        tokens_to_transfer = []
        high_tokens_reduced = []
        for token in high_tokens:
            token_amount = int(token["amount"])
            transfer_amount = (token_amount * reduction_amount) // high_price
            remaining = token_amount - transfer_amount
            if remaining > 0:
                high_tokens_reduced.append({
                    "tokenId": token["tokenId"],
                    "amount": remaining
                })
            if transfer_amount > 0:
                tokens_to_transfer.append({
                    "tokenId": token["tokenId"],
                    "amount": transfer_amount
                })

        # Merge transferred tokens into low box tokens
        low_tokens_merged = merge_token_arrays(low_tokens, tokens_to_transfer)

        # Get interest box for loan calculations
        interest_box = get_interest_box(pool["interest"], pool["INTEREST_NFT"])
        if not interest_box:
            logger.error("Interest box not found")
            return None

        # Get logic boxes for quotes (using same quote NFT for both)
        logic_box = get_logic_box(quote["quoteScript"], quote["quoteNFT"])
        if not logic_box:
            logger.error("Logic box not found")
            return None

        # Get primary DEX box for pricing
        primary_dex_nft = quote["primarySupportedCollateral"]["DEXNFT"]
        dex_box = get_dex_box(primary_dex_nft)
        if not dex_box:
            logger.error("Primary DEX box not found")
            return None

        # Get secondary DEX boxes if needed
        secondary_collateral_config = quote.get("secondarySupportedCollateral", [])
        secondary_dex_boxes = []
        for secondary in secondary_collateral_config:
            sec_dex_box = get_dex_box(secondary["DEXNFT"])
            if sec_dex_box:
                secondary_dex_boxes.append(sec_dex_box)

        # Parse existing iReport from logic box
        iReport = json.loads(logic_box["additionalRegisters"]["R4"]["renderedValue"])
        asset_thresholds = json.loads(logic_box["additionalRegisters"]["R6"]["renderedValue"])

        # Calculate quote prices for each output collateral
        dex_initial_val = dex_box["value"]
        dex_tokens = dex_box["assets"][2]["amount"]
        dex_fee = int(dex_box["additionalRegisters"]["R4"]["renderedValue"])

        # Calculate values for high box output (reduced)
        high_out_value = high_value - erg_to_transfer - (TX_FEE // 2)
        high_out_secondary_erg = _calculate_secondary_value(high_tokens_reduced, secondary_dex_boxes, secondary_collateral_config)
        high_total_box_value = high_out_value + high_out_secondary_erg - MAX_NETWORK_FEE
        high_quote_price = (dex_tokens * high_total_box_value * dex_fee) // \
            (((dex_initial_val * (100 + SLIPPAGE)) // 100) * DEX_FEE_DENOM + (high_total_box_value * dex_fee))

        # Calculate values for low box output (increased)
        low_out_value = low_value + erg_to_transfer - (TX_FEE // 2)
        low_out_secondary_erg = _calculate_secondary_value(low_tokens_merged, secondary_dex_boxes, secondary_collateral_config)
        low_total_box_value = low_out_value + low_out_secondary_erg - MAX_NETWORK_FEE
        low_quote_price = (dex_tokens * low_total_box_value * dex_fee) // \
            (((dex_initial_val * (100 + SLIPPAGE)) // 100) * DEX_FEE_DENOM + (low_total_box_value * dex_fee))

        # Calculate aggregate thresholds
        primary_threshold = asset_thresholds[0]
        high_aggregate = _calculate_aggregate_threshold(
            high_out_value, high_out_secondary_erg, high_total_box_value + MAX_NETWORK_FEE,
            primary_threshold, asset_thresholds, high_tokens_reduced, secondary_dex_boxes, secondary_collateral_config
        )
        low_aggregate = _calculate_aggregate_threshold(
            low_out_value, low_out_secondary_erg, low_total_box_value + MAX_NETWORK_FEE,
            primary_threshold, asset_thresholds, low_tokens_merged, secondary_dex_boxes, secondary_collateral_config
        )

        # Parse loan settings from collateral boxes
        high_loan_settings = json.loads(high_box["additionalRegisters"]["R9"]["renderedValue"])
        low_loan_settings = json.loads(low_box["additionalRegisters"]["R9"]["renderedValue"])

        # Get threshold and penalty from quote report (indices 2, 3)
        iThresholdQuoted = iReport[2] if len(iReport) > 2 else high_loan_settings[0]
        iPenaltyQuoted = iReport[3] if len(iReport) > 3 else high_loan_settings[1]

        # Build R7/R8 for quote outputs (ordered asset amounts/IDs)
        if secondary_collateral_config:
            high_ordered_amounts, high_ordered_ids = _get_ordered_assets(high_tokens_reduced, secondary_dex_boxes)
            low_ordered_amounts, low_ordered_ids = _get_ordered_assets(low_tokens_merged, secondary_dex_boxes)
            high_r7 = encode_long_tuple(high_ordered_amounts)
            high_r8 = bad_encode_arr(high_ordered_ids)
            low_r7 = encode_long_tuple(low_ordered_amounts)
            low_r8 = bad_encode_arr(low_ordered_ids)
        else:
            high_r7 = "1100"  # Empty long array
            high_r8 = "1a00"  # Empty byte array collection
            low_r7 = "1100"
            low_r8 = "1a00"

        # Determine output order based on input order
        # Inputs: [autobalance, high, low, logic1, logic2] or [autobalance, col1, col2, logic1, logic2]
        # We need to maintain the original order from group_boxes
        if high_box == collateral_1:
            col1_out, col2_out = high_box, low_box
            col1_value, col2_value = high_out_value, low_out_value
            col1_tokens, col2_tokens = high_tokens_reduced, low_tokens_merged
            col1_quote_price, col2_quote_price = high_quote_price, low_quote_price
            col1_aggregate, col2_aggregate = high_aggregate, low_aggregate
            col1_r7, col2_r7 = high_r7, low_r7
            col1_r8, col2_r8 = high_r8, low_r8
            col1_settings, col2_settings = high_loan_settings, low_loan_settings
        else:
            col1_out, col2_out = low_box, high_box
            col1_value, col2_value = low_out_value, high_out_value
            col1_tokens, col2_tokens = low_tokens_merged, high_tokens_reduced
            col1_quote_price, col2_quote_price = low_quote_price, high_quote_price
            col1_aggregate, col2_aggregate = low_aggregate, high_aggregate
            col1_r7, col2_r7 = low_r7, high_r7
            col1_r8, col2_r8 = low_r8, high_r8
            col1_settings, col2_settings = low_loan_settings, high_loan_settings

        # Build collateral output 1 assets
        col1_assets = [{"tokenId": collateral_1["assets"][0]["tokenId"], "amount": collateral_1["assets"][0]["amount"]}]
        col1_assets.extend(col1_tokens)

        # Build collateral output 2 assets
        col2_assets = [{"tokenId": collateral_2["assets"][0]["tokenId"], "amount": collateral_2["assets"][0]["amount"]}]
        col2_assets.extend(col2_tokens)

        # Build quote output 1 (R9[0] = 2 since collateral 1 is at OUTPUTS[1])
        quote_1_output = {
            "address": quote["quoteScript"],
            "value": logic_box["value"],
            "assets": [{"tokenId": logic_box["assets"][0]["tokenId"], "amount": 1}],
            "registers": {
                "R4": encode_long_tuple([
                    iReport[0], col1_quote_price, col1_aggregate, iReport[3],
                    iReport[4], iReport[5], iReport[6], iReport[7], iReport[8], iReport[9]
                ]),
                "R5": logic_box["additionalRegisters"]["R5"]["serializedValue"],
                "R6": logic_box["additionalRegisters"]["R6"]["serializedValue"],
                "R7": col1_r7,
                "R8": col1_r8,
                "R9": encode_coll_int([2, 1])  # collateral at OUTPUTS[1], DEX at dataInputs[1]
            }
        }

        # Build collateral output 1
        collateral_1_output = {
            "address": pool["collateral"],
            "value": col1_value,
            "assets": col1_assets,
            "registers": {
                "R4": collateral_1["additionalRegisters"]["R4"]["serializedValue"],
                "R5": collateral_1["additionalRegisters"]["R5"]["serializedValue"],
                "R6": encode_long(100000000),  # Reset to defaultBuffer
                "R7": collateral_1["additionalRegisters"]["R7"]["serializedValue"],
                "R8": collateral_1["additionalRegisters"]["R8"]["serializedValue"],
                "R9": encode_long_tuple([
                    iThresholdQuoted, iPenaltyQuoted,
                    col1_settings[2], col1_settings[3], col1_settings[4],
                    col1_settings[5], col1_settings[6], col1_settings[7]
                ])
            }
        }

        # Build quote output 2 (R9[0] = 4 since collateral 2 is at OUTPUTS[3])
        quote_2_output = {
            "address": quote["quoteScript"],
            "value": logic_box["value"],
            "assets": [{"tokenId": logic_box["assets"][0]["tokenId"], "amount": 1}],
            "registers": {
                "R4": encode_long_tuple([
                    iReport[0], col2_quote_price, col2_aggregate, iReport[3],
                    iReport[4], iReport[5], iReport[6], iReport[7], iReport[8], iReport[9]
                ]),
                "R5": logic_box["additionalRegisters"]["R5"]["serializedValue"],
                "R6": logic_box["additionalRegisters"]["R6"]["serializedValue"],
                "R7": col2_r7,
                "R8": col2_r8,
                "R9": encode_coll_int([4, 1])  # collateral at OUTPUTS[3], DEX at dataInputs[1]
            }
        }

        # Build collateral output 2
        collateral_2_output = {
            "address": pool["collateral"],
            "value": col2_value,
            "assets": col2_assets,
            "registers": {
                "R4": collateral_2["additionalRegisters"]["R4"]["serializedValue"],
                "R5": collateral_2["additionalRegisters"]["R5"]["serializedValue"],
                "R6": encode_long(100000000),  # Reset to defaultBuffer
                "R7": collateral_2["additionalRegisters"]["R7"]["serializedValue"],
                "R8": collateral_2["additionalRegisters"]["R8"]["serializedValue"],
                "R9": encode_long_tuple([
                    iThresholdQuoted, iPenaltyQuoted,
                    col2_settings[2], col2_settings[3], col2_settings[4],
                    col2_settings[5], col2_settings[6], col2_settings[7]
                ])
            }
        }

        # Build autobalance box output (recreated exactly the same)
        autobalance_output = {
            "address": autobalance_box["address"],
            "value": autobalance_box["value"],
            "assets": autobalance_box["assets"],
            "registers": {
                "R4": autobalance_box["additionalRegisters"]["R4"]["serializedValue"],
                "R5": autobalance_box["additionalRegisters"]["R5"]["serializedValue"],
                "R6": autobalance_box["additionalRegisters"]["R6"]["serializedValue"] if "R6" in autobalance_box["additionalRegisters"] else None,
                "R7": autobalance_box["additionalRegisters"]["R7"]["serializedValue"] if "R7" in autobalance_box["additionalRegisters"] else None,
                "R8": autobalance_box["additionalRegisters"]["R8"]["serializedValue"] if "R8" in autobalance_box["additionalRegisters"] else None,
                "R9": autobalance_box["additionalRegisters"]["R9"]["serializedValue"] if "R9" in autobalance_box["additionalRegisters"] else None,
            }
        }
        # Remove None registers
        autobalance_output["registers"] = {k: v for k, v in autobalance_output["registers"].items() if v is not None}

        # Build data inputs
        data_inputs_raw = [
            box_id_to_binary(interest_box["boxId"]),
            box_id_to_binary(dex_box["boxId"])
        ]
        for sec_dex in secondary_dex_boxes:
            data_inputs_raw.append(box_id_to_binary(sec_dex["boxId"]))

        # Assemble transaction
        transaction_to_sign = {
            "requests": [
                quote_1_output,
                collateral_1_output,
                quote_2_output,
                collateral_2_output,
                autobalance_output
            ],
            "fee": TX_FEE,
            "inputsRaw": [
                box_id_to_binary(autobalance_box["boxId"]),
                box_id_to_binary(collateral_1["boxId"]),
                box_id_to_binary(collateral_2["boxId"]),
                box_id_to_binary(logic_box["boxId"]),
                box_id_to_binary(logic_box["boxId"]),  # Same logic box used twice
            ],
            "dataInputsRaw": data_inputs_raw
        }

        logger.debug("Signing autobalance transaction: %s", json.dumps(transaction_to_sign))
        tx_id = sign_tx(transaction_to_sign)

        if tx_id != ERROR and tx_id != -1:
            logger.info("Successfully submitted autobalance transaction: %s", tx_id)
            return tx_id
        else:
            logger.warning("Failed to submit autobalance transaction")
            return None

    except Exception as e:
        logger.error("Error constructing autobalance transaction: %s", str(e))
        return None


def _calculate_secondary_value(tokens, secondary_dex_boxes, secondary_collateral_config):
    """Calculate ERG value of secondary collateral tokens."""
    if not secondary_collateral_config or not tokens:
        return 0

    token_amounts = {t["tokenId"]: int(t["amount"]) for t in tokens}
    total_value = 0

    for i, secondary in enumerate(secondary_collateral_config):
        if i >= len(secondary_dex_boxes):
            continue
        sec_dex_box = secondary_dex_boxes[i]
        asset_id = sec_dex_box["assets"][2]["tokenId"]
        input_amount = token_amounts.get(asset_id, 0)

        if input_amount > 0:
            sec_dex_fee = int(sec_dex_box["additionalRegisters"]["R4"]["renderedValue"])
            sec_dex_reserves_erg = sec_dex_box["value"]
            sec_dex_reserves_token = sec_dex_box["assets"][2]["amount"]

            sec_value = (sec_dex_reserves_erg * input_amount * sec_dex_fee) // \
                (((sec_dex_reserves_token * (100 + SLIPPAGE)) // 100) * DEX_FEE_DENOM +
                 (input_amount * sec_dex_fee))
            total_value += sec_value

    return total_value


def _calculate_aggregate_threshold(erg_value, secondary_erg_value, total_box_value,
                                   primary_threshold, asset_thresholds, tokens,
                                   secondary_dex_boxes, secondary_collateral_config):
    """Calculate weighted aggregate threshold for collateral."""
    if total_box_value <= 0:
        return primary_threshold

    aggregate_sum = (erg_value * LargeMultiplier * primary_threshold) // total_box_value

    if secondary_collateral_config and tokens:
        token_amounts = {t["tokenId"]: int(t["amount"]) for t in tokens}
        secondary_thresholds = asset_thresholds[1:] if len(asset_thresholds) > 1 else []

        for i, secondary in enumerate(secondary_collateral_config):
            if i >= len(secondary_dex_boxes):
                continue
            sec_dex_box = secondary_dex_boxes[i]
            asset_id = sec_dex_box["assets"][2]["tokenId"]
            input_amount = token_amounts.get(asset_id, 0)

            if input_amount > 0:
                sec_dex_fee = int(sec_dex_box["additionalRegisters"]["R4"]["renderedValue"])
                sec_dex_reserves_erg = sec_dex_box["value"]
                sec_dex_reserves_token = sec_dex_box["assets"][2]["amount"]

                sec_value = (sec_dex_reserves_erg * input_amount * sec_dex_fee) // \
                    (((sec_dex_reserves_token * (100 + SLIPPAGE)) // 100) * DEX_FEE_DENOM +
                     (input_amount * sec_dex_fee))

                threshold = secondary_thresholds[i] if i < len(secondary_thresholds) else primary_threshold
                aggregate_sum += (sec_value * LargeMultiplier * threshold) // total_box_value

    return aggregate_sum // LargeMultiplier


def _get_ordered_assets(tokens, secondary_dex_boxes):
    """Get ordered asset amounts and IDs matching DEX box order."""
    ordered_amounts = []
    ordered_ids = []

    token_amounts = {t["tokenId"]: int(t["amount"]) for t in tokens}

    for sec_dex_box in secondary_dex_boxes:
        asset_id = sec_dex_box["assets"][2]["tokenId"]
        amount = token_amounts.get(asset_id, 0)
        ordered_amounts.append(amount)
        ordered_ids.append(asset_id)

    return ordered_amounts, ordered_ids


def auto_balance_job(pool):
    """
    Main entry point for auto balance job.

    Called once per token pool per block from main.py loop.
    Checks for auto balance opportunities within collateral groups.
    Only runs for v2 pools with auto_balance_address configured.

    Flow:
        1. Fetch autobalance configuration boxes from auto_balance_address
        2. For each autobalance box:
            a. Extract spend NFT ID from R4
            b. Parse special bytes list from R5
            c. Get all collateral boxes matching the spend NFT
            d. Group collateral boxes by special bytes
            e. Price each box in each group
            f. Check for >10% price imbalance
            g. If imbalanced, construct rebalance transaction

    Args:
        pool: Pool configuration dict
    """
    # Only run for v2 pools
    if pool.get("version") != 2:
        return

    # Check if pool has auto_balance_address configured
    if "auto_balance_address" not in pool:
        return

    logger.info("Starting auto balance job for pool")

    # Fetch autobalance configuration boxes
    autobalance_boxes = get_autobalance_boxes(pool)
    if not autobalance_boxes:
        logger.debug("No autobalance boxes found")
        return

    logger.info("Found %d autobalance boxes", len(autobalance_boxes))

    for ab_box in autobalance_boxes:
        try:
            # Extract spend NFT ID from R4 (32 bytes = 64 hex chars)
            if "R4" not in ab_box.get("additionalRegisters", {}):
                logger.debug("Autobalance box missing R4 register")
                continue

            spend_nft_id = ab_box["additionalRegisters"]["R4"]["renderedValue"]
            logger.debug("Processing autobalance box with spend NFT: %s", spend_nft_id[:16] + "...")

            # Parse special bytes list from R5
            if "R5" not in ab_box.get("additionalRegisters", {}):
                logger.debug("Autobalance box missing R5 register")
                continue

            r5_value = ab_box["additionalRegisters"]["R5"]["renderedValue"]
            special_bytes_list = parse_special_bytes_list(r5_value)

            if not special_bytes_list:
                logger.debug("No special bytes found in R5")
                continue

            logger.debug("Found %d special bytes groups", len(special_bytes_list))

            # Get all collateral boxes matching this spend NFT
            collateral_boxes = get_collateral_boxes_for_spend_nft(pool, spend_nft_id)
            logger.debug("Found %d collateral boxes for spend NFT", len(collateral_boxes))

            if not collateral_boxes:
                continue

            # Group collateral boxes by special bytes
            groups = group_collateral_by_special_bytes(collateral_boxes, special_bytes_list)

            # Process each group
            for special_bytes, group_boxes in groups.items():
                if len(group_boxes) < 2:
                    logger.debug("Group %s has fewer than 2 boxes, skipping", special_bytes[:8] + "...")
                    continue

                logger.debug("Processing group %s with %d boxes", special_bytes[:8] + "...", len(group_boxes))

                try:
                    # Price each box in the group
                    prices = {}
                    quote = None

                    for box in group_boxes:
                        box_quote = find_quote_for_collateral(pool, box)
                        if not box_quote:
                            logger.debug("No quote found for box %s", box["boxId"])
                            continue

                        if quote is None:
                            quote = box_quote

                        try:
                            price = price_collateral_box(box, pool, box_quote)
                            prices[box["boxId"]] = price
                        except NotImplementedError:
                            logger.debug("price_collateral_box not implemented, skipping pricing")
                            break
                        except Exception as e:
                            logger.error("Error pricing box %s: %s", box["boxId"], str(e))
                            continue

                    if len(prices) < 2:
                        logger.debug("Insufficient priced boxes in group, skipping")
                        continue

                    # Check for imbalance (>10% difference)
                    needs_rebalance, imbalanced_box_ids = check_balance_threshold(prices)

                    if needs_rebalance:
                        logger.info(
                            "Imbalance detected in group %s: %d boxes need rebalancing",
                            special_bytes[:8] + "...", len(imbalanced_box_ids)
                        )

                        try:
                            # Construct and submit rebalance transaction
                            tx_id = construct_autobalance_transaction(
                                pool, ab_box, imbalanced_box_ids, group_boxes, quote
                            )
                            if tx_id:
                                logger.info("Auto balance transaction successful: %s", tx_id)
                        except NotImplementedError:
                            logger.debug("construct_autobalance_transaction not implemented")
                        except Exception as e:
                            logger.error("Error constructing autobalance transaction: %s", str(e))
                    else:
                        logger.debug("Group %s is balanced", special_bytes[:8] + "...")

                except Exception as e:
                    logger.error("Error processing group %s: %s", special_bytes[:8] + "...", str(e))
                    continue

        except Exception as e:
            logger.error("Error processing autobalance box %s: %s",
                        ab_box.get("boxId", "unknown"), str(e))
            continue
