"""
Automatic Repayment using Spend NFT Controller

This module handles automatic repayment of collateral boxes when their quote price
falls below the threshold defined in the spend NFT box.

The collateral contract (R8) contains a spending NFT ID. When a box containing this
NFT is included as an input, the collateral can be spent without returning assets
to the borrower - enabling automatic repayment by the protocol.

Required pool configuration:
    - "spend_nft_address": Address where spend NFT controller boxes are located

Spend NFT Box Structure:
    - Token[0]: The spend NFT ID
    - R4: Coll[Long] containing [threshold, ...] - threshold for triggering repayment
"""

import json

from consts import TX_FEE, MIN_BOX_VALUE, ERROR, SLIPPAGE, DEX_FEE_DENOM, MAX_NETWORK_FEE, LargeMultiplier, \
    BORROW_TOKEN_DENOMINATION
from helpers.explorer_calls import get_unspent_boxes_by_address
from helpers.node_calls import box_id_to_binary, sign_tx, tree_to_address, current_height
from helpers.platform_functions import get_interest_box, get_dex_box, get_logic_box
from helpers.serializer import extract_number, encode_long_tuple, encode_coll_int
from logger import set_logger

logger = set_logger(__name__)


def find_quote_by_nft(pool, quote_nft):
    """Find the quote configuration matching the given quote NFT."""
    for quote in pool.get("quotes", []):
        if quote["quoteNFT"] == quote_nft:
            return quote
    return None


def bad_encode_arr(items):
    """Encode array of byte arrays (works up to size 9)."""
    resp = "1a0" + format(len(items), 'x')
    for item in items:
        resp += "20" + item
    return resp


def get_spend_nft_boxes(pool):
    """
    Fetch all spend NFT boxes from the configured address.

    Args:
        pool: Pool configuration dict

    Returns:
        List of spend NFT boxes, or empty list if address not configured
    """
    spend_nft_address = pool.get("spend_nft_address")
    if not spend_nft_address:
        return []

    try:
        boxes = get_unspent_boxes_by_address(spend_nft_address)
        return boxes
    except Exception as e:
        logger.error("Error fetching spend NFT boxes: %s", str(e))
        return []


def get_collateral_boxes_for_nft(pool, spend_nft_id):
    """
    Get all active collateral boxes that reference the given spend NFT in R8.

    Args:
        pool: Pool configuration dict
        spend_nft_id: The spend NFT token ID to match against R8

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


def find_action_box_for_loan(spend_nft_boxes, collateral_box):
    """
    Find the action box that links to this loan via specialBytes.

    The loan's R8 contains spendNFT (32 bytes) + specialBytes (8 bytes).
    The action box's R8 contains the specialBytes that matches the loan's R8 suffix.

    Args:
        spend_nft_boxes: List of action boxes (spend NFT boxes)
        collateral_box: The loan collateral box

    Returns:
        The matching action box, or None if not found
    """
    try:
        # Extract specialBytes from loan R8 (last 8 bytes = 16 hex chars)
        loan_r8 = collateral_box["additionalRegisters"]["R8"]["renderedValue"]
        special_bytes = loan_r8[64:]  # Last 8 bytes in hex

        for action_box in spend_nft_boxes:
            try:
                closure_id = action_box["additionalRegisters"]["R8"]["renderedValue"]
                if closure_id == special_bytes:
                    return action_box
            except (KeyError, TypeError):
                continue
        return None
    except (KeyError, TypeError):
        return None


def calculate_quote_price(collateral_box, pool, quote):
    """
    Calculate the current quote price for a collateral box.

    Args:
        collateral_box: The collateral box to evaluate
        pool: Pool configuration
        quote: Quote configuration from pool

    Returns:
        Tuple of (quote_price, total_owed) or (None, None) on error
    """
    try:
        # Get interest box to calculate total owed
        interest_box = get_interest_box(pool["interest"], pool["INTEREST_NFT"])
        if not interest_box:
            return None, None

        # Get primary DEX box
        primary_dex_nft = quote["primarySupportedCollateral"]["DEXNFT"]
        dex_box = get_dex_box(primary_dex_nft)
        if not dex_box:
            return None, None

        # Calculate total owed
        loan_amount = int(collateral_box["assets"][0]["amount"])
        borrow_token_value = extract_number(interest_box["additionalRegisters"]["R5"]["renderedValue"])
        total_owed = loan_amount * borrow_token_value // BORROW_TOKEN_DENOMINATION

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

        # Calculate quote price (value in loan tokens)
        quote_price = (dex_tokens * total_box_value * dex_fee) // \
            (((dex_initial_val * (100 + SLIPPAGE)) // 100) * DEX_FEE_DENOM +
             (total_box_value * dex_fee))

        return quote_price, total_owed

    except Exception as e:
        logger.error("Error calculating quote price: %s", str(e))
        return None, None


def needs_automatic_repayment(collateral_box, threshold, pool, quote, height_spend=0):
    """
    Check if a collateral box's quote price is below the threshold or height has passed.

    Args:
        collateral_box: The collateral box to check
        threshold: The threshold from spend NFT box (as percentage * 1000, e.g., 1250 = 125%)
        pool: Pool configuration
        quote: Quote configuration
        height_spend: The height at which automatic repayment is allowed (0 = disabled)

    Returns:
        Tuple of (needs_repayment: bool, quote_price, total_owed)
    """
    quote_price, total_owed = calculate_quote_price(collateral_box, pool, quote)

    if quote_price is None or total_owed is None:
        return False, None, None

    # Check if quote price is below threshold
    # threshold is like 1250 meaning 125% (1250/1000)
    # Condition: quote_price <= total_owed * threshold / 1000
    threshold_value = (total_owed * threshold) // 1000
    print(threshold_value)
    print(threshold)
    print(quote_price)

    # Check height-based condition
    curr_height = current_height()
    height_condition = height_spend > 0 and curr_height >= height_spend

    needs_repayment = quote_price <= threshold_value or height_condition

    return needs_repayment, quote_price, total_owed


def get_funding_box(quote_fund_address, currency_id, min_amount):
    """
    Find a funding box with sufficient currency tokens.

    Args:
        quote_fund_address: Address to search for funding boxes
        currency_id: The currency token ID needed
        min_amount: Minimum amount of currency tokens required

    Returns:
        Funding box if found, None otherwise
    """
    try:
        boxes = get_unspent_boxes_by_address(quote_fund_address)
        for box in boxes:
            for asset in box.get("assets", []):
                if asset["tokenId"] == currency_id and int(asset["amount"]) >= min_amount:
                    return box
        return None
    except Exception as e:
        logger.error("Error fetching funding boxes: %s", str(e))
        return None


def process_automatic_repayment(pool, spend_nft_box, collateral_box, quote):
    """
    Build and submit an automatic repayment transaction.

    The transaction uses the spend NFT to authorize spending the collateral
    without returning assets to the borrower. A funding box provides the
    currency tokens for repayment and receives the collateral in return.

    Args:
        pool: Pool configuration
        spend_nft_box: The box containing the spend NFT
        collateral_box: The collateral box to repay
        quote: Quote configuration for this collateral

    Returns:
        Transaction ID on success, None on failure
    """
    try:
        # Check for quote_fund address
        quote_fund_address = quote.get("quote_fund")
        if not quote_fund_address:
            logger.warning("Quote missing quote_fund address")
            return None
        interest_box = get_interest_box(pool["interest"], pool["INTEREST_NFT"])
        if not interest_box:
            logger.warning("Interest box not found for automatic repayment")
            return None
        # Get primary DEX box
        primary_dex_nft = quote["primarySupportedCollateral"]["DEXNFT"]
        dex_box = get_dex_box(primary_dex_nft)
        if not dex_box:
            logger.warning("Primary DEX box not found")
            return None

        # Get logic box for quoting
        logic_box = get_logic_box(quote["quoteScript"], quote["quoteNFT"])
        if not logic_box:
            logger.warning("Logic box not found")
            return None

        # Calculate values for the quote
        dex_initial_val = dex_box["value"]
        dex_tokens = dex_box["assets"][2]["amount"]
        dex_fee = int(dex_box["additionalRegisters"]["R4"]["renderedValue"])

        asset_thresholds = json.loads(logic_box["additionalRegisters"]["R6"]["renderedValue"])
        primary_threshold = asset_thresholds[0]
        iReport = json.loads(logic_box["additionalRegisters"]["R4"]["renderedValue"])

        collateral_value = collateral_box["value"]

        # Handle secondary collateral
        secondary_collateral_config = quote.get("secondarySupportedCollateral", [])
        collateral_tokens = collateral_box["assets"][1:] if len(collateral_box["assets"]) > 1 else []
        secondary_erg_value = 0
        secondary_dex_boxes = []
        ordered_amounts = []
        ordered_asset_ids = []
        secondary_values_and_thresholds = []

        if secondary_collateral_config:
            token_amounts = {token["tokenId"]: token["amount"] for token in collateral_tokens}
            secondary_thresholds = asset_thresholds[1:] if len(asset_thresholds) > 1 else []

            for i, secondary in enumerate(secondary_collateral_config):
                sec_dex_box = get_dex_box(secondary["DEXNFT"])
                if not sec_dex_box:
                    logger.warning("Secondary DEX box not found: %s", secondary["DEXNFT"])
                    return None
                secondary_dex_boxes.append(sec_dex_box)

                asset_id = sec_dex_box["assets"][2]["tokenId"]
                input_amount = token_amounts.get(asset_id, 0)
                ordered_amounts.append(input_amount)
                ordered_asset_ids.append(asset_id)

                if input_amount > 0:
                    sec_dex_fee = int(sec_dex_box["additionalRegisters"]["R4"]["renderedValue"])
                    sec_dex_reserves_erg = sec_dex_box["value"]
                    sec_dex_reserves_token = sec_dex_box["assets"][2]["amount"]

                    sec_value = (sec_dex_reserves_erg * input_amount * sec_dex_fee) // \
                        (((sec_dex_reserves_token * (100 + SLIPPAGE)) // 100) * DEX_FEE_DENOM +
                         (input_amount * sec_dex_fee))

                    secondary_erg_value += sec_value
                    threshold = secondary_thresholds[i] if i < len(secondary_thresholds) else primary_threshold
                    secondary_values_and_thresholds.append((sec_value, threshold))

        total_box_value = collateral_value + secondary_erg_value - MAX_NETWORK_FEE

        liquidation_value = (dex_tokens * total_box_value * dex_fee) // \
            (((dex_initial_val * (100 + SLIPPAGE)) // 100) * DEX_FEE_DENOM +
             (total_box_value * dex_fee))

        aggregate_sum = (collateral_value * LargeMultiplier * primary_threshold) // total_box_value
        for sec_value, sec_threshold in secondary_values_and_thresholds:
            aggregate_sum += (sec_value * LargeMultiplier * sec_threshold) // total_box_value
        aggregateThreshold = aggregate_sum // LargeMultiplier

        # Calculate total owed for repayment
        loan_amount = int(collateral_box["assets"][0]["amount"])
        borrow_token_value = extract_number(interest_box["additionalRegisters"]["R5"]["renderedValue"])
        total_owed = loan_amount * borrow_token_value // BORROW_TOKEN_DENOMINATION

        # Get user address from spend NFT box R4 for leftover collateral
        user_address = tree_to_address(spend_nft_box["additionalRegisters"]["R4"]["renderedValue"])

        # Get fee allowance from R6 settings (index 1) - matches contract logic
        settings = json.loads(spend_nft_box["additionalRegisters"]["R6"]["renderedValue"]) if isinstance(
            spend_nft_box["additionalRegisters"]["R6"]["renderedValue"], str
        ) else spend_nft_box["additionalRegisters"]["R6"]["renderedValue"]
        fee_allowance = settings[1] if len(settings) > 1 else 0

        # Apply fee allowance to get adjusted quote price (matches contract)
        adjusted_quote_price = liquidation_value - (liquidation_value * fee_allowance // 1000)

        # Calculate user's proportional share of leftover collateral
        PROPORTION_DENOM = 1000
        if adjusted_quote_price > total_owed:
            user_proportion = ((adjusted_quote_price - total_owed) * PROPORTION_DENOM) // adjusted_quote_price

            # User's ERG share: (collateralErg * proportion / 1000) - TX_FEE
            user_erg = (collateral_value * user_proportion // PROPORTION_DENOM) - TX_FEE
            if user_erg < MIN_BOX_VALUE:
                user_erg = MIN_BOX_VALUE

            # User's token shares (collateral tokens are index 1+)
            user_tokens = []
            for token in collateral_tokens:
                token_amount = int(token["amount"])
                user_token_amount = (token_amount * user_proportion) // PROPORTION_DENOM
                if user_token_amount > 0:
                    user_tokens.append({
                        "tokenId": token["tokenId"],
                        "amount": user_token_amount
                    })
        else:
            # Debt exceeds or equals collateral value - user gets nothing
            user_proportion = 0
            user_erg = 0
            user_tokens = []

        # Find a funding box with enough currency
        repayment_amount = total_owed + 1  # Slightly over to ensure repayment succeeds
        funding_box = get_funding_box(quote_fund_address, pool["CURRENCY_ID"], repayment_amount)
        if not funding_box:
            logger.warning("No funding box found with sufficient currency at %s", quote_fund_address)
            return None

        logger.info("Found funding box %s with sufficient funds", funding_box["boxId"])

        # Build funding box output assets - deduct currency, add collateral tokens
        funding_output_assets = []
        for asset in funding_box.get("assets", []):
            if asset["tokenId"] == pool["CURRENCY_ID"]:
                # Deduct the repayment amount
                new_amount = int(asset["amount"]) - repayment_amount
                if new_amount > 0:
                    funding_output_assets.append({
                        "tokenId": asset["tokenId"],
                        "amount": new_amount
                    })
            else:
                # Keep other assets unchanged
                funding_output_assets.append({
                    "tokenId": asset["tokenId"],
                    "amount": asset["amount"]
                })

        # Add collateral tokens to funding box output (secondary collateral)
        # Deduct user's proportional share from what goes to funder
        user_token_amounts = {t["tokenId"]: t["amount"] for t in user_tokens}
        for token in collateral_tokens:
            token_id = token["tokenId"]
            token_amount = int(token["amount"])
            # Deduct user's share
            user_share = user_token_amounts.get(token_id, 0)
            funder_token_amount = token_amount - user_share

            if funder_token_amount > 0:
                # Check if token already exists in funding box
                existing = next((a for a in funding_output_assets if a["tokenId"] == token_id), None)
                if existing:
                    existing["amount"] = int(existing["amount"]) + funder_token_amount
                else:
                    funding_output_assets.append({
                        "tokenId": token_id,
                        "amount": funder_token_amount
                    })

        # Encode registers for logic box output
        if secondary_collateral_config:
            r7_value = encode_long_tuple(ordered_amounts)
            r8_value = bad_encode_arr(ordered_asset_ids)
        else:
            r7_value = "1100"
            r8_value = "1a00"

        # R9: [boxIndex, dexStartIndex]
        # Collateral is at INPUTS(2), so boxIndex = -2 - 1 = -3
        # Primary DEX is at dataInputs(1), so dexStartIndex = 1
        r9_value = encode_coll_int([-3, 1])

        # Build data inputs
        data_inputs_raw = [
            box_id_to_binary(interest_box["boxId"]),
            box_id_to_binary(dex_box["boxId"])
        ]
        for sec_dex in secondary_dex_boxes:
            data_inputs_raw.append(box_id_to_binary(sec_dex["boxId"]))

        # Collateral ERG goes to funder (minus tx fees, repayment box value, logic box value, and user's share)
        # Repayment box needs MIN_BOX_VALUE + TX_FEE, logic box needs logic_box["value"], plus TX_FEE for transaction fee
        funder_erg_value = funding_box["value"] + collateral_value - MIN_BOX_VALUE - 2 * TX_FEE - logic_box["value"] - user_erg

        # Build transaction outputs
        # Inputs: spend_nft_box, funding_box, collateral_box, logic_box
        # Outputs: repayment_box, logic_box, user_box (if applicable), funding_box (with collateral), spend_nft_box
        output_requests = [
            {
                "address": pool["repayment"],
                "value": MIN_BOX_VALUE + TX_FEE,
                "assets": [
                    {
                        "tokenId": collateral_box["assets"][0]["tokenId"],
                        "amount": collateral_box["assets"][0]["amount"]
                    },
                    {
                        "tokenId": pool["CURRENCY_ID"],
                        "amount": repayment_amount
                    }
                ],
                "registers": {}
            },
            {
                "address": quote["quoteScript"],
                "value": logic_box["value"],
                "assets": [
                    {
                        "tokenId": logic_box["assets"][0]["tokenId"],
                        "amount": 1
                    }
                ],
                "registers": {
                    "R4": encode_long_tuple([iReport[0], liquidation_value, aggregateThreshold, iReport[3], iReport[4], iReport[5], iReport[6], iReport[7], iReport[8], iReport[9]]),
                    "R5": logic_box["additionalRegisters"]["R5"]["serializedValue"],
                    "R6": logic_box["additionalRegisters"]["R6"]["serializedValue"],
                    "R7": r7_value,
                    "R8": r8_value,
                    "R9": r9_value
                }
            }
        ]

        # Add user box if they have a share of leftover collateral
        if user_proportion > 0:
            user_box_output = {
                "address": user_address,
                "value": user_erg,
                "assets": user_tokens,
                "registers": {}
            }
            output_requests.append(user_box_output)

        # Add funding box output
        output_requests.append({
            "address": funding_box["address"],
            "value": funder_erg_value,
            "assets": funding_output_assets,
            "registers": {}
        })

        # Add spend NFT box output (must be recreated)
        output_requests.append({
            "address": spend_nft_box["address"],
            "value": spend_nft_box["value"],
            "assets": spend_nft_box["assets"],
            "registers": {
                "R4": spend_nft_box["additionalRegisters"]["R4"]["serializedValue"],
                "R5": spend_nft_box["additionalRegisters"]["R5"]["serializedValue"],
                "R6": spend_nft_box["additionalRegisters"]["R6"]["serializedValue"],
                "R7": spend_nft_box["additionalRegisters"]["R7"]["serializedValue"],
                "R8": spend_nft_box["additionalRegisters"]["R8"]["serializedValue"],
                "R9": spend_nft_box["additionalRegisters"]["R9"]["serializedValue"],
            }
        })

        transaction_to_sign = {
            "requests": output_requests,
            "fee": TX_FEE,
            "inputsRaw": [
                box_id_to_binary(spend_nft_box["boxId"]),      # INPUTS(0)
                box_id_to_binary(funding_box["boxId"]),         # INPUTS(1)
                box_id_to_binary(collateral_box["boxId"]),      # INPUTS(2)
                box_id_to_binary(logic_box["boxId"]),           # INPUTS(3)
            ],
            "dataInputsRaw": data_inputs_raw
        }

        logger.debug("Signing automatic repayment transaction: %s", json.dumps(transaction_to_sign))
        tx_id = sign_tx(transaction_to_sign)

        if tx_id != ERROR and tx_id != -1:
            logger.info("Successfully submitted automatic repayment transaction: %s", tx_id)
            return tx_id
        else:
            logger.warning("Failed to submit automatic repayment transaction")
            return None

    except Exception as e:
        logger.error("Error processing automatic repayment: %s", str(e))
        return None


def automatic_repayment_job(pool):
    """
    Main entry point for automatic repayment job.

    Called once per pool per block from main.py loop.
    Checks for automatic repayment opportunities using spend NFTs.
    Only runs for v2 pools.

    Args:
        pool: Pool configuration dict
    """
    # Only run for v2 pools
    if pool.get("version") != 2:
        return

    # Check if pool has spend_nft_address configured
    if "spend_nft_address" not in pool:
        return

    logger.info("Starting automatic repayment job for pool")

    # Fetch spend NFT boxes
    spend_nft_boxes = get_spend_nft_boxes(pool)
    if not spend_nft_boxes:
        logger.debug("No spend NFT boxes found")
        return

    logger.info("Found %d spend NFT boxes", len(spend_nft_boxes))
    for spend_nft_box in spend_nft_boxes:
        try:
            # Extract threshold from spend NFT box R6
            if "R6" not in spend_nft_box.get("additionalRegisters", {}):
                logger.debug("Spend NFT box missing R6 register")
                continue

            threshold_data = spend_nft_box["additionalRegisters"]["R6"]["renderedValue"]
            logger.debug("Spend NFT box R6 renderedValue: %s (type: %s)", threshold_data, type(threshold_data).__name__)

            # Parse threshold and height_spend based on type
            # R6 contains settings: [liquidationThreshold, feeAllowance, heightSpend]
            if isinstance(threshold_data, (int, float)):
                threshold = int(threshold_data)
                height_spend = 0  # No height constraint if single value
            elif isinstance(threshold_data, list):
                threshold = int(threshold_data[0])
                height_spend = int(threshold_data[2]) if len(threshold_data) > 2 else 0
            elif isinstance(threshold_data, str):
                # Try to parse as JSON array first, then as plain number
                if threshold_data.startswith('['):
                    parsed = json.loads(threshold_data)
                    threshold = int(parsed[0])
                    height_spend = int(parsed[2]) if len(parsed) > 2 else 0
                else:
                    # Plain number string
                    threshold = int(threshold_data)
                    height_spend = 0
            else:
                logger.warning("Unexpected R6 format: %s", type(threshold_data))
                continue
            # Get spend NFT ID
            if not spend_nft_box.get("assets"):
                continue
            spend_nft_id = spend_nft_box["assets"][0]["tokenId"]

            logger.debug("Processing spend NFT %s with threshold %d", spend_nft_id, threshold)

            # Find collateral boxes with this spend NFT
            collateral_boxes = get_collateral_boxes_for_nft(pool, spend_nft_id)
            logger.debug("Found %d collateral boxes for spend NFT", len(collateral_boxes))

            for collateral_box in collateral_boxes:
                try:
                    # Verify specialBytes link: loan R8[64:] must match action box R8
                    matched_action_box = find_action_box_for_loan([spend_nft_box], collateral_box)
                    if not matched_action_box:
                        # This collateral box doesn't link to this specific action box
                        continue

                    # Get quote NFT from spend NFT box R7
                    quote_nft = spend_nft_box["additionalRegisters"]["R7"]["renderedValue"]
                    print("qu", quote_nft)
                    quote = find_quote_by_nft(pool, quote_nft)
                    print(quote, "dd")
                    if not quote:
                        logger.debug("No matching quote found for NFT %s", quote_nft)
                        continue

                    # Check if repayment is needed
                    needs_repay, quote_price, total_owed = needs_automatic_repayment(
                        collateral_box, threshold, pool, quote, height_spend
                    )
                    print(needs_repay, quote_price, total_owed)
                    if needs_repay:
                        logger.info(
                            "Collateral box %s needs repayment: quote_price=%s, total_owed=%s, threshold=%s",
                            collateral_box["boxId"], quote_price, total_owed, threshold
                        )

                        # Execute automatic repayment
                        tx_id = process_automatic_repayment(pool, spend_nft_box, collateral_box, quote)
                        if tx_id:
                            logger.info("Automatic repayment successful: %s", tx_id)
                            # Only process one repayment per spend NFT box per run
                            break
                    else:
                        logger.debug(
                            "Collateral box %s healthy: quote_price=%s, threshold_value=%s",
                            collateral_box["boxId"], quote_price, (total_owed * threshold) // 1000 if total_owed else None
                        )

                except Exception as e:
                    logger.error("Error processing collateral box %s: %s",
                               collateral_box.get("boxId", "unknown"), str(e))
                    continue

        except Exception as e:
            logger.error("Error processing spend NFT box %s: %s",
                        spend_nft_box.get("boxId", "unknown"), str(e))
            continue
