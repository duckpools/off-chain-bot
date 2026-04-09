"""
Multi-Collateral Funding Box Liquidation

For loans with multiple collateral assets (assets[1:] has >1 token), a DEX swap
is impractical. Instead, liquidation uses a funding box where the funder provides
currency tokens and receives the collateral in return. DEX boxes remain as data
inputs for quoting only.
"""

import json

from consts import PENALTY_DENOMINATION, MIN_BOX_VALUE, TX_FEE
from helpers.explorer_calls import get_dummy_box
from helpers.node_calls import tree_to_address, box_id_to_binary
from helpers.platform_functions import get_dex_box
from token_pools.repayments.automatic_repayment_spend_nft import get_funding_box
from logger import set_logger

logger = set_logger(__name__)


def create_multi_collateral_liquidation_tx(pool, box, total_due, interest_box, logic_box, dummy_script):
    """
    Create a liquidation transaction for multi-collateral loans using a funding box.

    Instead of swapping through the DEX (which only works for single-collateral),
    a funder provides currency tokens for repayment and receives the collateral.

    Args:
        pool: Pool configuration dict
        box: The collateral box being liquidated
        total_due: Total amount owed on the loan
        interest_box: The interest box for this pool
        logic_box: The quote/logic box
        dummy_script: Address for the dummy/fee box

    Returns:
        Unsigned transaction dict, or None on failure
    """
    from token_pools.t_liquidation_susd_v2 import calculate_quote_values, build_quote_output, build_data_inputs

    quote = pool["quotes"][1]

    # Get primary DEX box (data input only, not spent)
    dex_box = get_dex_box(quote["primarySupportedCollateral"]["DEXNFT"])
    if not dex_box:
        logger.warning("Primary DEX box not found for multi-collateral liquidation")
        return None

    # Calculate quote values (liquidation_value, thresholds, secondary DEX data)
    quote_values = calculate_quote_values(box, dex_box, quote, logic_box)
    if not quote_values:
        logger.warning("Failed to calculate quote values for multi-collateral liquidation")
        return None

    liquidation_value = quote_values["quote_price"]

    # Get loan settings for penalty
    loan_settings = json.loads(box["additionalRegisters"]["R9"]["renderedValue"])
    liquidation_penalty = loan_settings[1]  # iPenalty

    collateral_value = box["value"]
    collateral_tokens = box["assets"][1:]
    user = tree_to_address(box["additionalRegisters"]["R4"]["renderedValue"])

    # Contract formula for borrower share (in currency tokens, not collateral)
    # Matches quacks.py line 498: ((quotePrice - totalOwed) * (PenaltyDenom - iPenalty)) / PenaltyDenom
    borrower_share = ((liquidation_value - total_due) * (PENALTY_DENOMINATION - liquidation_penalty)) // PENALTY_DENOMINATION

    if borrower_share < 1:
        # No borrower output; all currency goes to repayment
        # Contract line 500: repaymentAmount >= quotePrice
        repayment_amount = liquidation_value
        total_currency_needed = repayment_amount
    else:
        # Contract line 502: repaymentAmount >= totalOwed + ((quotePrice - totalOwed) * iPenalty / PenaltyDenom)
        repayment_amount = total_due + ((liquidation_value - total_due) * liquidation_penalty // PENALTY_DENOMINATION)
        total_currency_needed = repayment_amount + borrower_share

    # Find funding box with sufficient currency
    quote_fund_address = quote.get("quote_fund")
    if not quote_fund_address:
        logger.warning("Quote missing quote_fund address for multi-collateral liquidation")
        return None

    funding_box = get_funding_box(quote_fund_address, pool["CURRENCY_ID"], total_currency_needed)
    if not funding_box:
        logger.warning("No funding box found with sufficient currency at %s", quote_fund_address)
        return None

    logger.info("Found funding box %s for multi-collateral liquidation", funding_box["boxId"])

    # Get dummy box
    dummy_box = get_dummy_box(dummy_script)

    # Build funding box output assets - deduct total currency spent, add ALL collateral tokens
    funding_output_assets = []
    for asset in funding_box.get("assets", []):
        if asset["tokenId"] == pool["CURRENCY_ID"]:
            new_amount = int(asset["amount"]) - total_currency_needed
            if new_amount > 0:
                funding_output_assets.append({
                    "tokenId": asset["tokenId"],
                    "amount": new_amount
                })
        else:
            funding_output_assets.append({
                "tokenId": asset["tokenId"],
                "amount": asset["amount"]
            })

    # Funder gets ALL collateral tokens (no user share deduction — borrower gets currency, not collateral)
    for token in collateral_tokens:
        token_id = token["tokenId"]
        token_amount = int(token["amount"])
        if token_amount > 0:
            existing = next((a for a in funding_output_assets if a["tokenId"] == token_id), None)
            if existing:
                existing["amount"] = int(existing["amount"]) + token_amount
            else:
                funding_output_assets.append({
                    "tokenId": token_id,
                    "amount": token_amount
                })

    # Quote output: collateral at INPUTS(0), DEX starts at dataInputs(1)
    quote_output = build_quote_output(
        logic_box, quote["quoteScript"],
        quote_values["quote_price"], quote_values["aggregate_threshold"],
        quote_values["ordered_amounts"], quote_values["ordered_asset_ids"],
        [-1, 1]
    )

    # Data inputs: interest_box, primary DEX, secondary DEX boxes
    data_inputs = build_data_inputs(interest_box, dex_box, quote_values["secondary_dex_boxes"])

    # Funder ERG: gets all collateral ERG, no borrower ERG deduction (borrower gets currency tokens + dust ERG)
    if borrower_share >= 1:
        funder_erg_value = funding_box["value"] + collateral_value - 2 * MIN_BOX_VALUE - 2 * TX_FEE - logic_box["value"]
    else:
        funder_erg_value = funding_box["value"] + collateral_value - MIN_BOX_VALUE - 2 * TX_FEE - logic_box["value"]

    # Build transaction outputs
    output_requests = [
        # [0] Repayment box
        {
            "address": pool["repayment"],
            "value": MIN_BOX_VALUE + TX_FEE,
            "assets": [
                {"tokenId": box["assets"][0]["tokenId"], "amount": box["assets"][0]["amount"]},
                {"tokenId": pool["CURRENCY_ID"], "amount": repayment_amount}
            ],
            "registers": {}
        },
        # [1] Logic box output
        quote_output,
    ]

    # [2] Borrower box (optional) - gets CURRENCY_ID tokens, not collateral
    # Contract lines 506-507: borrowBox.tokens(0)._1 == PoolCurrencyId, amount >= borrowerShare
    if borrower_share >= 1:
        output_requests.append({
            "address": user,
            "value": MIN_BOX_VALUE,
            "assets": [
                {"tokenId": pool["CURRENCY_ID"], "amount": borrower_share}
            ],
            "registers": {}
        })

    # [next] Funding box output - funder gets ALL collateral, loses currency
    output_requests.append({
        "address": funding_box["address"],
        "value": funder_erg_value,
        "assets": funding_output_assets,
        "registers": {}
    })

    transaction_to_sign = {
        "requests": output_requests,
        "fee": TX_FEE,
        "inputsRaw": [
            box_id_to_binary(box["boxId"]),          # INPUTS(0) - collateral box
            box_id_to_binary(funding_box["boxId"]),   # INPUTS(1) - funding box
            box_id_to_binary(dummy_box["boxId"]),     # INPUTS(2) - dummy/fee box
            box_id_to_binary(logic_box["boxId"]),     # INPUTS(3) - logic box
        ],
        "dataInputsRaw": data_inputs
    }

    logger.debug("Multi-collateral liquidation transaction: %s", json.dumps(transaction_to_sign))
    return transaction_to_sign
