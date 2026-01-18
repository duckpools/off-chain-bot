"""
Auto Balance Module for Token Pools

This module handles automatic rebalancing of collateral boxes within groups.
When collateral boxes in the same group have prices that differ by more than 10%,
a rebalancing transaction is constructed to redistribute collateral.

Autobalance Box Structure (at auto_balance_address):
    - R4: Coll[Byte] (32 bytes / 64 hex chars) - Spend NFT ID to match against collateral R8[:64]
    - R5: Coll[Coll[Byte]] - Array of special bytes, each entry groups collateral boxes
          whose R8[64:] (last 8 bytes / 16 hex chars) matches
    - R9: Coll[Coll[Byte]] - Array of special bytes where index i contains the expected
          special bytes for the collateral box at INPUTS[i]. This enforces input ordering
          as the collateral contract checks: R9[selfIndex] == collateral.R8[64:]

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
from helpers.platform_functions import get_dex_box, get_interest_box, get_logic_box, get_logic_boxes
from helpers.serializer import encode_long_tuple, encode_coll_int, encode_long, parse_coll_bytes
from logger import set_logger

logger = set_logger(__name__)

# Threshold for triggering rebalance (10% difference)
BALANCE_THRESHOLD_PERCENT = 0.10


def print_logic_script_checks(
    logic_input,
    logic_output,
    box_to_quote,
    dex_boxes,
    is_output_box
):
    """
    Print detailed debug information for logic script contract validation.

    The logic script validates quote calculations and settings preservation.
    Main path requires all sigmaProp conditions to be satisfied.
    """
    print(f"\n{'='*80}")
    print(f"LOGIC SCRIPT DEBUG - Quote Box Validation")
    print(f"{'='*80}")

    # Contract constants
    SLIPPAGE = 2
    SLIPPAGE_DENOM = 100
    DEX_FEE_DENOM = 1000
    MAXIMUM_NETWORK_FEE = 5000000
    LARGE_MULTIPLIER = 1000000000000

    print(f"\n--- CONTRACT CONSTANTS ---")
    print(f"  Slippage: {SLIPPAGE}")
    print(f"  SlippageDenom: {SLIPPAGE_DENOM}")
    print(f"  DexFeeDenom: {DEX_FEE_DENOM}")
    print(f"  MaximumNetworkFee: {MAXIMUM_NETWORK_FEE}")
    print(f"  LargeMultiplier: {LARGE_MULTIPLIER}")

    # Extract input logic box (SELF) values
    print(f"\n--- INPUT LOGIC BOX (SELF) ---")
    print(f"  Box ID: {logic_input['boxId']}")
    print(f"  Value: {logic_input['value']}")
    print(f"  Token: {logic_input['assets'][0]['tokenId'][:32]}...")

    i_report_raw = logic_input["additionalRegisters"]["R4"]["renderedValue"]
    if isinstance(i_report_raw, str):
        i_report = json.loads(i_report_raw)
    else:
        i_report = i_report_raw

    print(f"  R4 (iReport): {i_report}")
    print(f"    - iBorrowLimit (0): {i_report[0]}")
    print(f"    - iMinimumValue (4): {i_report[4]}")
    print(f"    - iBufferGap (5): {i_report[5]}")
    print(f"    - iMinimumLoanAmount (6): {i_report[6]}")
    print(f"    - iShortLoanFee (7): {i_report[7]}")
    print(f"    - iShortLoanDuration (8): {i_report[8]}")
    print(f"    - iMaxBorrowAmount (9): {i_report[9]}")

    i_dex_nfts_raw = logic_input["additionalRegisters"]["R5"]["renderedValue"]
    i_asset_thresholds_raw = logic_input["additionalRegisters"]["R6"]["renderedValue"]
    if isinstance(i_asset_thresholds_raw, str):
        i_asset_thresholds = json.loads(i_asset_thresholds_raw)
    else:
        i_asset_thresholds = i_asset_thresholds_raw

    print(f"  R5 (iDexNfts): {i_dex_nfts_raw[:50] if isinstance(i_dex_nfts_raw, str) else i_dex_nfts_raw}...")
    print(f"  R6 (iAssetThresholds): {i_asset_thresholds}")

    # Extract output logic box (outLogic) values
    print(f"\n--- OUTPUT LOGIC BOX (outLogic) ---")
    print(f"  Value: {logic_output['value']}")

    f_report_raw = logic_output["registers"]["R4"]
    print(f"  R4 (fReport - encoded): {f_report_raw[:50]}...")

    f_dex_nfts_raw = logic_output["registers"]["R5"]
    f_asset_thresholds_raw = logic_output["registers"]["R6"]
    f_ordered_amounts_raw = logic_output["registers"]["R7"]
    f_ordered_asset_ids_raw = logic_output["registers"]["R8"]
    f_helper_indices_raw = logic_output["registers"]["R9"]

    print(f"  R5 (fDexNfts - encoded): {f_dex_nfts_raw[:50]}...")
    print(f"  R6 (fAssetThresholds - encoded): {f_asset_thresholds_raw[:50]}...")
    print(f"  R7 (fOrderedAssetAmounts - encoded): {f_ordered_amounts_raw}")
    print(f"  R8 (fOrderedQuotedAssetIds - encoded): {f_ordered_asset_ids_raw[:50] if len(f_ordered_asset_ids_raw) > 50 else f_ordered_asset_ids_raw}...")
    print(f"  R9 (fHelperIndices - encoded): {f_helper_indices_raw}")

    # Box to quote
    print(f"\n--- BOX TO QUOTE ---")
    print(f"  Box ID: {box_to_quote['boxId'] if 'boxId' in box_to_quote else 'OUTPUT (building)'}")
    box_value = box_to_quote.get('value', 0)
    print(f"  Value: {box_value}")
    box_tokens = box_to_quote.get('assets', [])
    print(f"  Tokens: {len(box_tokens)} tokens")
    for i, token in enumerate(box_tokens):
        print(f"    [{i}] {token['tokenId'][:32]}... amount={token['amount']}")

    # DEX boxes
    print(f"\n--- DEX BOXES (dataInputs) ---")
    if dex_boxes:
        primary_dex = dex_boxes[0]
        print(f"  Primary DEX Box:")
        print(f"    Box ID: {primary_dex['boxId']}")
        print(f"    Value (xAssets): {primary_dex['value']}")
        primary_token = primary_dex['assets'][2] if len(primary_dex['assets']) > 2 else None
        if primary_token:
            print(f"    Token[2] (yAssets): {primary_token['tokenId'][:32]}... amount={primary_token['amount']}")
        primary_dex_fee_raw = primary_dex["additionalRegisters"]["R4"]["renderedValue"]
        if isinstance(primary_dex_fee_raw, str):
            primary_dex_fee = int(primary_dex_fee_raw)
        else:
            primary_dex_fee = primary_dex_fee_raw
        print(f"    R4 (dexFee): {primary_dex_fee}")
        print(f"    NFT: {primary_dex['assets'][0]['tokenId'][:32]}...")

        for i, sec_dex in enumerate(dex_boxes[1:], 1):
            print(f"\n  Secondary DEX Box [{i}]:")
            print(f"    Box ID: {sec_dex['boxId']}")
            print(f"    Value: {sec_dex['value']}")
            sec_token = sec_dex['assets'][2] if len(sec_dex['assets']) > 2 else None
            if sec_token:
                print(f"    Token[2]: {sec_token['tokenId'][:32]}... amount={sec_token['amount']}")
            sec_dex_fee_raw = sec_dex["additionalRegisters"]["R4"]["renderedValue"]
            if isinstance(sec_dex_fee_raw, str):
                sec_dex_fee = int(sec_dex_fee_raw)
            else:
                sec_dex_fee = sec_dex_fee_raw
            print(f"    R4 (dexFee): {sec_dex_fee}")

    # Validation checks
    print(f"\n{'='*60}")
    print("LOGIC SCRIPT SIGMAPROP CONDITIONS")
    print(f"{'='*60}")

    # scriptRetained
    check_script = logic_output["address"] == logic_input["address"] if "address" in logic_output else "CHECK MANUALLY"
    print(f"\n  1. scriptRetained (outLogic.propositionBytes == SELF.propositionBytes):")
    print(f"     Result: {check_script}")

    # quoteSettingsRetained
    check_dex_nfts = f_dex_nfts_raw == logic_input["additionalRegisters"]["R5"]["serializedValue"]
    check_thresholds = f_asset_thresholds_raw == logic_input["additionalRegisters"]["R6"]["serializedValue"]
    print(f"\n  2. quoteSettingsRetained (fDexNfts == iDexNfts && fAssetThresholds == iAssetThresholds):")
    print(f"     fDexNfts == iDexNfts: {check_dex_nfts}")
    print(f"       Output R5: {f_dex_nfts_raw[:32]}...")
    print(f"       Input R5:  {logic_input['additionalRegisters']['R5']['serializedValue'][:32]}...")
    print(f"     fAssetThresholds == iAssetThresholds: {check_thresholds}")
    print(f"       Output R6: {f_asset_thresholds_raw[:32]}...")
    print(f"       Input R6:  {logic_input['additionalRegisters']['R6']['serializedValue'][:32]}...")

    # Quote price calculation
    print(f"\n  3. validQuote (quotePrice == fQuotePrice):")
    if dex_boxes and primary_token:
        x_assets = primary_dex['value']
        y_assets = primary_token['amount']

        # Calculate collateral value in ERGs from secondary tokens
        collateral_tokens = box_tokens[1:] if len(box_tokens) > 1 else []
        collateral_value_in_ergs = 0

        print(f"     Calculating totalBoxValue:")
        print(f"       boxToQuote.value: {box_value}")

        for i, sec_dex in enumerate(dex_boxes[1:]):
            if i < len(collateral_tokens):
                sec_token = sec_dex['assets'][2]
                input_amount = collateral_tokens[i]['amount']
                sec_dex_fee_raw = sec_dex["additionalRegisters"]["R4"]["renderedValue"]
                sec_dex_fee = int(sec_dex_fee_raw) if isinstance(sec_dex_fee_raw, str) else sec_dex_fee_raw
                sec_reserves_erg = sec_dex['value']
                sec_reserves_token = sec_token['amount']

                # collateralMarketValue formula from contract
                slippage_adjusted = sec_reserves_token + (sec_reserves_token * SLIPPAGE // 100)
                collateral_market_value = (sec_reserves_erg * input_amount * sec_dex_fee) // (
                    slippage_adjusted * DEX_FEE_DENOM + (input_amount * sec_dex_fee)
                )
                collateral_value_in_ergs += collateral_market_value
                print(f"       Secondary [{i}] collateralMarketValue: {collateral_market_value}")

        total_box_value = box_value + collateral_value_in_ergs - MAXIMUM_NETWORK_FEE
        print(f"       collateralValueInErgs: {collateral_value_in_ergs}")
        print(f"       totalBoxValue: {total_box_value}")

        # Quote price formula
        slippage_adjusted_primary = x_assets + (x_assets * SLIPPAGE // SLIPPAGE_DENOM)
        quote_price = (y_assets * total_box_value * primary_dex_fee) // (
            slippage_adjusted_primary * DEX_FEE_DENOM + (total_box_value * primary_dex_fee)
        )
        print(f"     Calculated quotePrice: {quote_price}")
        print(f"       xAssets (primaryDex.value): {x_assets}")
        print(f"       yAssets (primaryDex.tokens[2].amount): {y_assets}")
        print(f"       dexFee: {primary_dex_fee}")

    # Aggregate threshold calculation
    print(f"\n  4. validAggregateThreshold (aggregateThreshold / LargeMultiplier == max(fAggregateThreshold, 1001)):")
    primary_threshold = i_asset_thresholds[0]
    print(f"     primaryThreshold: {primary_threshold}")
    if dex_boxes:
        agg_primary = (box_value * LARGE_MULTIPLIER * primary_threshold) // total_box_value
        print(f"     aggregateThresholdPrimarySum: {agg_primary}")

        agg_secondary = 0
        for i, sec_dex in enumerate(dex_boxes[1:]):
            if i < len(collateral_tokens) and i + 1 < len(i_asset_thresholds):
                input_amount = collateral_tokens[i]['amount']
                if input_amount > 0:
                    sec_token = sec_dex['assets'][2]
                    sec_dex_fee_raw = sec_dex["additionalRegisters"]["R4"]["renderedValue"]
                    sec_dex_fee = int(sec_dex_fee_raw) if isinstance(sec_dex_fee_raw, str) else sec_dex_fee_raw
                    sec_reserves_erg = sec_dex['value']
                    sec_reserves_token = sec_token['amount']

                    slippage_adjusted = sec_reserves_token + (sec_reserves_token * SLIPPAGE // 100)
                    collateral_market_value = (sec_reserves_erg * input_amount * sec_dex_fee) // (
                        slippage_adjusted * DEX_FEE_DENOM + (input_amount * sec_dex_fee)
                    )
                    threshold = i_asset_thresholds[i + 1]
                    contribution = (collateral_market_value * LARGE_MULTIPLIER * threshold) // total_box_value
                    agg_secondary += contribution
                    print(f"     Secondary [{i}] contribution: {contribution} (threshold={threshold})")

        aggregate_threshold = agg_primary + agg_secondary
        final_agg = aggregate_threshold // LARGE_MULTIPLIER
        print(f"     aggregateThreshold: {aggregate_threshold}")
        print(f"     aggregateThreshold / LargeMultiplier: {final_agg}")
        print(f"     Expected fAggregateThreshold: max({final_agg}, 1001) = {max(final_agg, 1001)}")

    # validPenalty
    print(f"\n  5. validPenalty (max(min(fAggregatePenalty, 1000), 0) == 30):")
    print(f"     Static penalty required: 30")

    # Settings preservation
    print(f"\n  6. Settings Preservation Checks:")
    print(f"     iBorrowLimit == max(fBorrowLimit, 0): Input={i_report[0]}")
    print(f"     iMinimumValue == max(fMinimumValue, 4000000): Input={i_report[4]}")
    print(f"     iBufferGap == max(fBufferGap, 1): Input={i_report[5]}")
    print(f"     iMinimumLoanAmount == max(fMinimumLoanAmount, 0): Input={i_report[6]}")
    print(f"     iShortLoanFee == max(min(fShortLoanFee, 1000), 0): Input={i_report[7]}")
    print(f"     iShortLoanDuration == max(fShortLoanDuration, 0): Input={i_report[8]}")
    print(f"     iMaxBorrowAmount == max(fMaxBorrowAmount, 0): Input={i_report[9]}")

    # isValidPrimaryDexBox
    print(f"\n  7. isValidPrimaryDexBox (primaryDexBox.tokens(0)._1 == primaryDexNft):")
    if dex_boxes:
        print(f"     primaryDexBox NFT: {primary_dex['assets'][0]['tokenId']}")

    # Asset ordering checks
    print(f"\n  8. Asset Ordering Checks:")
    print(f"     dInsMatchesAssetsSize: (secondary dex boxes count == ordered amounts count)")
    print(f"     matchingOrderedListSize: (fOrderedAssetAmounts.size == fOrderedQuotedAssetIds.size)")
    print(f"     allAssetsCounted: (all collateral tokens appear in ordered list)")
    print(f"     correctNumberOfZeroes: (zeroes in ordered amounts == missing assets)")
    print(f"     assetsOrderedCorrectly: (DEX NFTs match settings, asset IDs match DEX tokens)")

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY - LOGIC SCRIPT VALIDATION")
    print(f"{'='*60}")

    print(f"\n  Core Checks:")
    print(f"    - scriptRetained: {check_script}")
    print(f"    - quoteSettingsRetained (R5): {check_dex_nfts}")
    print(f"    - quoteSettingsRetained (R6): {check_thresholds}")

    print(f"\n  Quote Calculations:")
    if dex_boxes and primary_token:
        print(f"    - totalBoxValue: {total_box_value}")
        print(f"    - quotePrice: {quote_price}")
        print(f"    - aggregateThreshold: {final_agg}")

    print(f"\n  Settings (must match input with bounds):")
    print(f"    - iBorrowLimit: {i_report[0]}")
    print(f"    - iMinimumValue: {i_report[4]}")
    print(f"    - iBufferGap: {i_report[5]}")
    print(f"    - iMinimumLoanAmount: {i_report[6]}")
    print(f"    - iShortLoanFee: {i_report[7]}")
    print(f"    - iShortLoanDuration: {i_report[8]}")
    print(f"    - iMaxBorrowAmount: {i_report[9]}")

    print(f"{'='*80}\n")

    return {
        "script_retained": check_script,
        "dex_nfts_retained": check_dex_nfts,
        "thresholds_retained": check_thresholds,
    }


def print_tx_breakdown(transaction):
    """Print a readable breakdown of transaction outputs."""
    print("Transaction outputs:")
    for i, output in enumerate(transaction.get("requests", [])):
        print(f"\nOutput {i}:")
        print(f"  address: {output.get('address')}")
        print(f"  value: {output.get('value')}")

        assets = output.get("assets", [])
        if assets:
            print("  assets:")
            for asset in assets:
                print(f"    - {asset.get('tokenId')}: {asset.get('amount')}")
        else:
            print("  assets: []")

        registers = output.get("registers", {})
        if registers:
            print("  registers:")
            for reg_key, reg_val in registers.items():
                print(f"    {reg_key}: {reg_val}")
        else:
            print("  registers: {}")


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

    The special_bytes_list from the autobalance box R5 defines which loans
    belong to the same rebalancing group. All collateral boxes whose special
    bytes appear in this list are grouped together for rebalancing.

    Args:
        collateral_boxes: List of collateral boxes (already filtered by spend NFT)
        special_bytes_list: List of special bytes strings from autobalance box R5
                           that define a single rebalancing group

    Returns:
        List of collateral boxes that belong to this rebalancing group
    """
    special_bytes_set = set(special_bytes_list)
    group_boxes = []

    for box in collateral_boxes:
        try:
            # Extract special bytes from R8 (last 16 hex chars = 8 bytes)
            box_r8 = box["additionalRegisters"]["R8"]["renderedValue"]
            box_special_bytes = box_r8[64:]  # Last 8 bytes in hex

            # Check if this box belongs to the group
            if box_special_bytes in special_bytes_set:
                group_boxes.append(box)
        except (KeyError, TypeError):
            continue

    return group_boxes


def order_collateral_by_r9(autobalance_box, collateral_boxes):
    """
    Order collateral boxes based on their required INPUTS positions
    as defined by the autobalance box's R9 register.

    The collateral contract requires:
        autobalance_box.R9[selfIndex] == collateral.R8[64:]

    Where selfIndex is the collateral's position in INPUTS. This means we must
    place each collateral box at the INPUTS index matching the position of its
    special bytes in the R9 array.

    Args:
        autobalance_box: The autobalance box with R9 containing Coll[Coll[Byte]]
                        where each entry's index corresponds to the expected
                        INPUTS position for a collateral with matching special bytes
        collateral_boxes: List of collateral boxes to order

    Returns:
        Tuple of (ordered_collaterals, input_indices) where:
            - ordered_collaterals: List of collateral boxes ordered by their R9 index
            - input_indices: List of actual INPUTS indices where each collateral must be placed
        Returns (None, None) on error
    """
    try:
        if "R9" not in autobalance_box.get("additionalRegisters", {}):
            logger.error("Autobalance box missing R9 register for input ordering")
            return None, None

        r9_value = autobalance_box["additionalRegisters"]["R9"]["renderedValue"]
        r9_array = parse_special_bytes_list(r9_value)

        if not r9_array:
            logger.error("Could not parse R9 special bytes array from autobalance box")
            return None, None

        # Build mapping: special_bytes -> collateral_box
        collateral_by_special_bytes = {}
        for box in collateral_boxes:
            try:
                box_r8 = box["additionalRegisters"]["R8"]["renderedValue"]
                box_special_bytes = box_r8[64:]  # Last 16 hex chars (8 bytes)
                collateral_by_special_bytes[box_special_bytes] = box
            except (KeyError, TypeError) as e:
                logger.error("Collateral box %s missing R8: %s", box.get("boxId", "unknown"), e)
                return None, None

        # Find required INPUTS index for each collateral based on R9
        # R9[i] contains special bytes for collateral expected at INPUTS[i]
        index_to_collateral = {}
        for r9_index, special_bytes in enumerate(r9_array):
            if special_bytes in collateral_by_special_bytes:
                index_to_collateral[r9_index] = collateral_by_special_bytes[special_bytes]

        if len(index_to_collateral) != len(collateral_boxes):
            logger.error(
                "R9 index matching failed: found %d matches for %d collateral boxes. "
                "R9 has %d entries, collateral special bytes: %s",
                len(index_to_collateral),
                len(collateral_boxes),
                len(r9_array),
                list(collateral_by_special_bytes.keys())
            )
            return None, None

        # Sort by R9 index to get proper INPUTS order
        sorted_indices = sorted(index_to_collateral.keys())
        ordered_collaterals = [index_to_collateral[i] for i in sorted_indices]

        logger.debug(
            "Ordered %d collaterals by R9: INPUTS indices %s",
            len(ordered_collaterals),
            sorted_indices
        )

        return ordered_collaterals, sorted_indices

    except Exception as e:
        logger.error("Error ordering collateral boxes by R9: %s", str(e))
        return None, None


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

        # Order collateral boxes based on R9 to satisfy contract requirements
        # The contract checks: autobalance_box.R9[selfIndex] == collateral.R8[64:]
        # where selfIndex is the collateral's position in INPUTS
        ordered_boxes, input_indices = order_collateral_by_r9(autobalance_box, group_boxes)
        if ordered_boxes is None or input_indices is None:
            logger.error("Failed to determine collateral ordering from R9")
            return None

        if len(input_indices) != 2:
            logger.error("Expected exactly 2 input indices from R9, got %d", len(input_indices))
            return None

        collateral_1 = ordered_boxes[0]
        collateral_2 = ordered_boxes[1]
        collateral_1_input_idx = input_indices[0]  # Required INPUTS position for collateral_1
        collateral_2_input_idx = input_indices[1]  # Required INPUTS position for collateral_2

        logger.debug(
            "Collateral input positions from R9: col1 at INPUTS[%d], col2 at INPUTS[%d]",
            collateral_1_input_idx, collateral_2_input_idx
        )

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

        # Get two different logic boxes for quotes (each collateral needs its own logic box input)
        logic_boxes = get_logic_boxes(quote["quoteScript"], quote["quoteNFT"], count=2)
        if len(logic_boxes) < 2:
            logger.error("Need 2 logic boxes, only found %d", len(logic_boxes))
            return None
        logic_box_1 = logic_boxes[0]
        logic_box_2 = logic_boxes[1]

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

        # Parse existing iReport from logic box (both boxes should have same settings)
        iReport = json.loads(logic_box_1["additionalRegisters"]["R4"]["renderedValue"])
        asset_thresholds = json.loads(logic_box_1["additionalRegisters"]["R6"]["renderedValue"])

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

        # Get penalty from quote report (index 3)
        # Note: Threshold (R9[0]) uses calculated col_aggregate, not iReport[2]
        # because collateral contract validates: fLoanSettings(0) == quoteReport(2)
        # and quoteReport(2) = col_aggregate (calculated for each collateral)
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
            "value": logic_box_1["value"],
            "assets": [{"tokenId": logic_box_1["assets"][0]["tokenId"], "amount": 1}],
            "registers": {
                "R4": encode_long_tuple([
                    iReport[0], col1_quote_price, col1_aggregate, iReport[3],
                    iReport[4], iReport[5], iReport[6], iReport[7], iReport[8], iReport[9]
                ]),
                "R5": logic_box_1["additionalRegisters"]["R5"]["serializedValue"],
                "R6": logic_box_1["additionalRegisters"]["R6"]["serializedValue"],
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
                    col1_aggregate, iPenaltyQuoted,  # R9[0] must match quote R4[2]
                    col1_settings[2], col1_settings[3], col1_settings[4],
                    col1_settings[5], col1_settings[6], col1_settings[7]
                ])
            }
        }

        # Build quote output 2 (R9[0] = 4 since collateral 2 is at OUTPUTS[3])
        quote_2_output = {
            "address": quote["quoteScript"],
            "value": logic_box_2["value"],
            "assets": [{"tokenId": logic_box_2["assets"][0]["tokenId"], "amount": 1}],
            "registers": {
                "R4": encode_long_tuple([
                    iReport[0], col2_quote_price, col2_aggregate, iReport[3],
                    iReport[4], iReport[5], iReport[6], iReport[7], iReport[8], iReport[9]
                ]),
                "R5": logic_box_2["additionalRegisters"]["R5"]["serializedValue"],
                "R6": logic_box_2["additionalRegisters"]["R6"]["serializedValue"],
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
                    col2_aggregate, iPenaltyQuoted,  # R9[0] must match quote R4[2]
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

        # Build inputs array with collaterals at their R9-specified positions
        # The autobalance box can be placed anywhere - the contract only requires
        # that R9[selfIndex] matches the collateral's special bytes, where selfIndex
        # is the collateral's position in INPUTS
        max_collateral_idx = max(collateral_1_input_idx, collateral_2_input_idx)

        # Build mapping of index -> box for collaterals
        collateral_positions = {
            collateral_1_input_idx: collateral_1,
            collateral_2_input_idx: collateral_2
        }

        # Other boxes to place (autobalance and logic boxes)
        other_boxes = [autobalance_box, logic_box_1, logic_box_2]
        other_box_idx = 0

        # Build inputs list: collaterals at their R9 positions, other boxes fill gaps
        inputs_raw = []

        for idx in range(0, max_collateral_idx + 1):
            if idx in collateral_positions:
                inputs_raw.append(box_id_to_binary(collateral_positions[idx]["boxId"]))
            else:
                # Fill gap with other box (autobalance or logic box)
                if other_box_idx < len(other_boxes):
                    inputs_raw.append(box_id_to_binary(other_boxes[other_box_idx]["boxId"]))
                    other_box_idx += 1
                else:
                    logger.error("Not enough boxes to fill input gaps")
                    return None

        # Add remaining other boxes after the collateral positions
        while other_box_idx < len(other_boxes):
            inputs_raw.append(box_id_to_binary(other_boxes[other_box_idx]["boxId"]))
            other_box_idx += 1

        print(
            "Built inputs array with %d entries: col1 at %d, col2 at %d",
            len(inputs_raw), collateral_1_input_idx, collateral_2_input_idx
        )

        # Debug: Print input/output value breakdown
        print("\n" + "="*60)
        print("AUTOBALANCE TX VALUE BREAKDOWN")
        print("="*60)

        # Helper to aggregate tokens
        def aggregate_tokens(boxes_with_assets):
            """Aggregate tokens from multiple boxes. Each entry is (name, assets_list)"""
            totals = {}
            for name, assets in boxes_with_assets:
                for asset in assets:
                    token_id = asset.get("tokenId", asset.get("tokenId", "unknown"))
                    amount = int(asset.get("amount", 0))
                    if token_id not in totals:
                        totals[token_id] = {"amount": 0, "sources": []}
                    totals[token_id]["amount"] += amount
                    totals[token_id]["sources"].append(name)
            return totals

        # Build actual input order mapping for accurate debug output
        input_box_order = []
        temp_other_idx = 0
        temp_other_boxes = [("autobalance_box", autobalance_box), ("logic_box_1", logic_box_1), ("logic_box_2", logic_box_2)]
        for idx in range(0, max_collateral_idx + 1):
            if idx == collateral_1_input_idx:
                input_box_order.append(("collateral_1", collateral_1))
            elif idx == collateral_2_input_idx:
                input_box_order.append(("collateral_2", collateral_2))
            else:
                if temp_other_idx < len(temp_other_boxes):
                    input_box_order.append(temp_other_boxes[temp_other_idx])
                    temp_other_idx += 1
        while temp_other_idx < len(temp_other_boxes):
            input_box_order.append(temp_other_boxes[temp_other_idx])
            temp_other_idx += 1

        print("\n--- INPUTS (ERG) ---")
        input_total = 0
        for idx, (name, box) in enumerate(input_box_order):
            print(f"  [{idx}] {name:15}: {box['value']} nanoERG")
            input_total += box['value']
        print(f"  TOTAL INPUTS: {input_total} nanoERG")

        print("\n--- INPUTS (TOKENS) ---")
        input_tokens = aggregate_tokens([
            ("autobalance", autobalance_box.get("assets", [])),
            ("collateral_1", collateral_1.get("assets", [])),
            ("collateral_2", collateral_2.get("assets", [])),
            ("logic_1", logic_box_1.get("assets", [])),
            ("logic_2", logic_box_2.get("assets", [])),
        ])
        for token_id, info in input_tokens.items():
            print(f"  {token_id[:16]}...: {info['amount']} (from {', '.join(info['sources'])})")

        print("\n--- OUTPUTS (ERG) ---")
        output_total = 0
        print(f"  [0] quote_1:         {quote_1_output['value']} nanoERG")
        output_total += quote_1_output['value']
        print(f"  [1] collateral_1:    {collateral_1_output['value']} nanoERG")
        output_total += collateral_1_output['value']
        print(f"  [2] quote_2:         {quote_2_output['value']} nanoERG")
        output_total += quote_2_output['value']
        print(f"  [3] collateral_2:    {collateral_2_output['value']} nanoERG")
        output_total += collateral_2_output['value']
        print(f"  [4] autobalance:     {autobalance_output['value']} nanoERG")
        output_total += autobalance_output['value']
        print(f"  TOTAL OUTPUTS: {output_total} nanoERG")

        print("\n--- OUTPUTS (TOKENS) ---")
        output_tokens = aggregate_tokens([
            ("quote_1", quote_1_output.get("assets", [])),
            ("collateral_1", collateral_1_output.get("assets", [])),
            ("quote_2", quote_2_output.get("assets", [])),
            ("collateral_2", collateral_2_output.get("assets", [])),
            ("autobalance", autobalance_output.get("assets", [])),
        ])
        for token_id, info in output_tokens.items():
            print(f"  {token_id[:16]}...: {info['amount']} (to {', '.join(info['sources'])})")

        print("\n--- TOKEN BALANCE CHECK ---")
        all_token_ids = set(input_tokens.keys()) | set(output_tokens.keys())
        token_balanced = True
        for token_id in all_token_ids:
            in_amt = input_tokens.get(token_id, {}).get("amount", 0)
            out_amt = output_tokens.get(token_id, {}).get("amount", 0)
            diff = in_amt - out_amt
            status = "OK" if diff == 0 else f"DIFF: {diff}"
            if diff != 0:
                token_balanced = False
            print(f"  {token_id[:16]}...: IN={in_amt}, OUT={out_amt} [{status}]")

        print(f"\n--- ERG SUMMARY ---")
        print(f"  TX_FEE:              {TX_FEE} nanoERG")
        print(f"  Outputs + Fee:       {output_total + TX_FEE} nanoERG")
        print(f"  Inputs - (Out+Fee):  {input_total - output_total - TX_FEE} nanoERG")
        if input_total < output_total + TX_FEE:
            print(f"  *** ERG DEFICIT: {output_total + TX_FEE - input_total} nanoERG ***")
        if not token_balanced:
            print(f"  *** TOKEN IMBALANCE DETECTED ***")
        print("="*60 + "\n")

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
            "inputsRaw": inputs_raw,
            "dataInputsRaw": data_inputs_raw
        }


        # Build list of all DEX boxes for logic script validation
        all_dex_boxes = [dex_box] + secondary_dex_boxes

        print(collateral_1)
        print(collateral_2)

        print_tx_breakdown(transaction_to_sign)
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

            # Group collateral boxes by special bytes (all matching boxes form one group)
            group_boxes = group_collateral_by_special_bytes(collateral_boxes, special_bytes_list)

            if len(group_boxes) < 2:
                logger.debug("Group has fewer than 2 boxes, skipping")
                continue

            logger.debug("Processing group with %d boxes", len(group_boxes))

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
                    "Imbalance detected: %d boxes need rebalancing",
                    len(imbalanced_box_ids)
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
                logger.debug("Group is balanced")

        except Exception as e:
            logger.error("Error processing autobalance box %s: %s",
                        ab_box.get("boxId", "unknown"), str(e))
            continue
