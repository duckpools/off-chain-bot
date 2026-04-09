import json
import math
import time
from math import floor

from consts import PENALTY_DENOMINATION, MIN_BOX_VALUE, TX_FEE, DEFAULT_BUFFER, LargeMultiplier, MAX_NETWORK_FEE, \
    SLIPPAGE, DEX_FEE_DENOM
from helpers.explorer_calls import get_unspent_boxes_by_address, get_dummy_box
from helpers.node_calls import tree_to_address, box_id_to_binary, get_box_from_id, sign_tx, current_height
from helpers.platform_functions import get_dex_box, get_dex_box_from_tx, \
    liquidation_allowed_susd, get_interest_box, get_logic_box
from helpers.serializer import encode_long, encode_long_tuple, encode_coll_int
from token_pools.t_liquidation_v2_multi import create_multi_collateral_liquidation_tx
from logger import set_logger

logger = set_logger(__name__)


def bad_encode_arr(items):
    """Encode array of byte arrays (works up to size 9)."""
    resp = "1a0" + format(len(items), 'x')
    for item in items:
        resp += "20" + item
    return resp


def calculate_quote_values(box, dex_box, quote, logic_box, collateral_value=None):
    """Calculate quote price and aggregate threshold for a collateral box."""
    dex_initial_val = dex_box["value"]
    dex_tokens = dex_box["assets"][2]["amount"]
    dex_fee = int(dex_box["additionalRegisters"]["R4"]["renderedValue"])

    asset_thresholds = json.loads(logic_box["additionalRegisters"]["R6"]["renderedValue"])
    primary_threshold = asset_thresholds[0]

    if collateral_value is None:
        collateral_value = box["value"]

    secondary_collateral_config = quote.get("secondarySupportedCollateral", [])
    collateral_tokens = box["assets"][1:] if len(box["assets"]) > 1 else []

    secondary_erg_value = 0
    secondary_dex_boxes = []
    ordered_amounts = []
    ordered_asset_ids = []
    secondary_values_and_thresholds = []

    if len(secondary_collateral_config) > 0:
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

    quote_price = (dex_tokens * total_box_value * dex_fee) // \
        (((dex_initial_val * (100 + SLIPPAGE)) // 100) * DEX_FEE_DENOM +
         (total_box_value * dex_fee))

    aggregate_sum = (collateral_value * LargeMultiplier * primary_threshold) // total_box_value
    for sec_value, sec_threshold in secondary_values_and_thresholds:
        aggregate_sum += (sec_value * LargeMultiplier * sec_threshold) // total_box_value
    aggregate_threshold = aggregate_sum // LargeMultiplier

    return {
        "quote_price": quote_price,
        "aggregate_threshold": aggregate_threshold,
        "ordered_amounts": ordered_amounts,
        "ordered_asset_ids": ordered_asset_ids,
        "secondary_dex_boxes": secondary_dex_boxes
    }


def build_quote_output(logic_box, quote_script, quote_price, aggregate_threshold,
                        ordered_amounts, ordered_asset_ids, r9_indices):
    """Build the quote/logic box output with proper registers."""
    iReport = json.loads(logic_box["additionalRegisters"]["R4"]["renderedValue"])

    if len(ordered_amounts) > 0:
        r7_value = encode_long_tuple(ordered_amounts)
        r8_value = bad_encode_arr(ordered_asset_ids)
    else:
        r7_value = "1100"
        r8_value = "1a00"
    return {
        "address": quote_script,
        "value": logic_box["value"],
        "assets": [
            {"tokenId": logic_box["assets"][0]["tokenId"], "amount": 1}
        ],
        "registers": {
            "R4": encode_long_tuple([iReport[0], quote_price, aggregate_threshold, iReport[3],
                                     iReport[4], iReport[5], iReport[6], iReport[7], iReport[8], iReport[9]]),
            "R5": logic_box["additionalRegisters"]["R5"]["serializedValue"],
            "R6": logic_box["additionalRegisters"]["R6"]["serializedValue"],
            "R7": r7_value,
            "R8": r8_value,
            "R9": encode_coll_int(r9_indices)
        }
    }


def build_data_inputs(interest_box, dex_box, secondary_dex_boxes):
    """Build data inputs list: [interest_box, primary_dex_box, secondary_dex_boxes...]"""
    data_inputs = [
        box_id_to_binary(interest_box["boxId"]),
        box_id_to_binary(dex_box["boxId"])
    ]
    for sec_dex in secondary_dex_boxes:
        data_inputs.append(box_id_to_binary(sec_dex["boxId"]))
    return data_inputs


def create_prep_transaction(pool, box, interest_box, dex_box, logic_box, dummy_script):
    """
    Create prep liquidation transaction (readyToLiquidate path).
    Sets the buffer liquidation height on the collateral box.
    """
    quote = pool["quotes"][1]
    dummy_box = get_dummy_box(dummy_script)
    curr_height = current_height()

    loan_settings = json.loads(box["additionalRegisters"]["R9"]["renderedValue"])
    buffer_gap = loan_settings[2]

    # Collateral successor value after TX_FEE deduction - must match what the logic script sees
    # via boxToQuote = OUTPUTS(fBoxIndex - 1) when fBoxIndex > 0
    successor_value = box["value"] - TX_FEE

    quote_values = calculate_quote_values(box, dex_box, quote, logic_box, collateral_value=successor_value)
    if not quote_values:
        return None

    # Contract requires: fBufferLiquidation > HEIGHT + iBufferGap && < HEIGHT + iBufferGap + 5
    new_buffer_liquidation = curr_height + buffer_gap + 2

    # Collateral successor: same box with updated R6, R9 preserved
    collateral_assets = [{"tokenId": box["assets"][0]["tokenId"], "amount": box["assets"][0]["amount"]}]
    for token in box["assets"][1:]:
        collateral_assets.append({"tokenId": token["tokenId"], "amount": token["amount"]})

    # Quote box: fBoxIndex=1 (OUTPUTS[0] = collateral successor), dexStartIndex=1
    quote_output = build_quote_output(
        logic_box, quote["quoteScript"],
        quote_values["quote_price"], quote_values["aggregate_threshold"],
        quote_values["ordered_amounts"], quote_values["ordered_asset_ids"],
        [1, 1]
    )
    logger.debug("Prep liquidation path")

    transaction_to_sign = {
        "requests": [
            {
                "address": box["address"],
                "value": box["value"] - TX_FEE,
                "assets": collateral_assets,
                "registers": {
                    "R4": box["additionalRegisters"]["R4"]["serializedValue"],
                    "R5": box["additionalRegisters"]["R5"]["serializedValue"],
                    "R6": encode_long(new_buffer_liquidation),
                    "R7": box["additionalRegisters"]["R7"]["serializedValue"],
                    "R8": box["additionalRegisters"]["R8"]["serializedValue"],
                    "R9": box["additionalRegisters"]["R9"]["serializedValue"]
                }
            },
            quote_output,
            {
                "address": dummy_box["address"],
                "value": dummy_box["value"],
                "assets": [
                    {"tokenId": dummy_box["assets"][0]["tokenId"], "amount": dummy_box["assets"][0]["amount"]},
                    {"tokenId": dummy_box["assets"][1]["tokenId"], "amount": dummy_box["assets"][1]["amount"]}
                ],
                "registers": {}
            }
        ],
        "fee": TX_FEE,
        "inputsRaw": [
            box_id_to_binary(box["boxId"]),
            box_id_to_binary(logic_box["boxId"]),
            box_id_to_binary(dummy_box["boxId"]),

        ],
        "dataInputsRaw": build_data_inputs(interest_box, dex_box, quote_values["secondary_dex_boxes"])
    }
    return transaction_to_sign


def create_liquidation_transaction(pool, dex_box, box, dex_initial_val, dex_tokens, tokens_to_liquidate,
                                    liquidation_value, client_amount, lp_tokens, dex_box_address,
                                    total_due, interest_box, logic_box, dummy_script):
    """
    Create actual liquidation transaction (liquidate path).
    Swaps collateral ERG for tokens via DEX and creates repayment box.
    """
    quote = pool["quotes"][1]
    dummy_box = get_dummy_box(dummy_script)

    loan_settings = json.loads(box["additionalRegisters"]["R9"]["renderedValue"])
    liquidation_penalty = loan_settings[1]  # iPenalty

    collateral_value = liquidation_value
    borrower_share = math.floor(
        ((collateral_value - total_due) * (PENALTY_DENOMINATION - liquidation_penalty)) / PENALTY_DENOMINATION)
    user = tree_to_address(box["additionalRegisters"]["R4"]["renderedValue"])

    quote_values = calculate_quote_values(box, dex_box, quote, logic_box)
    if not quote_values:
        return None

    # Quote box: fBoxIndex=-1 (INPUTS[0] = collateral box), dexStartIndex=1
    quote_output = build_quote_output(
        logic_box, quote["quoteScript"],
        quote_values["quote_price"], quote_values["aggregate_threshold"],
        quote_values["ordered_amounts"], quote_values["ordered_asset_ids"],
        [-1, 1]
    )

    data_inputs = build_data_inputs(interest_box, dex_box, quote_values["secondary_dex_boxes"])

    if borrower_share < 1:
        print("here")
        transaction_to_sign = {
            "requests": [
                {
                    "address": dex_box_address,
                    "value": dex_initial_val + tokens_to_liquidate,
                    "assets": [
                        {"tokenId": dex_box["assets"][0]["tokenId"], "amount": str(dex_box["assets"][0]["amount"])},
                        {"tokenId": dex_box["assets"][1]["tokenId"], "amount": str(lp_tokens)},
                        {"tokenId": dex_box["assets"][2]["tokenId"], "amount": str(dex_tokens - liquidation_value)}
                    ],
                    "registers": {
                        "R4": quote["primarySupportedCollateral"]["dexFeeSerialized"]
                    }
                },
                {
                    "address": pool["repayment"],
                    "value": MIN_BOX_VALUE + TX_FEE,
                    "assets": [
                        {"tokenId": box["assets"][0]["tokenId"], "amount": box["assets"][0]["amount"]},
                        {"tokenId": dex_box["assets"][2]["tokenId"], "amount": str(liquidation_value)}
                    ],
                    "registers": {}
                },
                quote_output
            ],
            "fee": TX_FEE,
            "inputsRaw": [
                box_id_to_binary(box["boxId"]),
                box_id_to_binary(dex_box["boxId"]),
                box_id_to_binary(dummy_box["boxId"]),
                box_id_to_binary(logic_box["boxId"])
            ],
            "dataInputsRaw": data_inputs
        }
    else:
        print("there")
        transaction_to_sign = {
            "requests": [
                {
                    "address": dex_box_address,
                    "value": dex_initial_val + tokens_to_liquidate,
                    "assets": [
                        {"tokenId": dex_box["assets"][0]["tokenId"], "amount": str(dex_box["assets"][0]["amount"])},
                        {"tokenId": dex_box["assets"][1]["tokenId"], "amount": str(lp_tokens)},
                        {"tokenId": dex_box["assets"][2]["tokenId"],
                         "amount": str(dex_tokens - liquidation_value - client_amount)}
                    ],
                    "registers": {
                        "R4": quote["primarySupportedCollateral"]["dexFeeSerialized"]
                    }
                },
                {
                    "address": pool["repayment"],
                    "value": MIN_BOX_VALUE + TX_FEE,
                    "assets": [
                        {"tokenId": box["assets"][0]["tokenId"], "amount": box["assets"][0]["amount"]},
                        {"tokenId": dex_box["assets"][2]["tokenId"],
                         "amount": str(liquidation_value - borrower_share + client_amount)}
                    ],
                    "registers": {}
                },
                {
                    "address": user,
                    "value": MIN_BOX_VALUE / 2,
                    "assets": [
                        {"tokenId": dex_box["assets"][2]["tokenId"], "amount": str(borrower_share)}
                    ],
                    "registers": {}
                },

                quote_output
            ],
            "fee": TX_FEE,
            "inputsRaw": [
                box_id_to_binary(box["boxId"]),
                box_id_to_binary(dex_box["boxId"]),
                box_id_to_binary(dummy_box["boxId"]),
                box_id_to_binary(logic_box["boxId"])
            ],
            "dataInputsRaw": data_inputs
        }
    return transaction_to_sign


def get_dex_box_and_tokens(transaction, nft):
    """
    Get the dex box, its LP tokens, and address from a transaction.
    """
    if transaction is None:
        dex_box = get_dex_box(nft)
        dex_box_contents = get_box_from_id(dex_box['boxId'])
        lp_tokens = dex_box_contents["assets"][1]["amount"]
        dex_box_address = dex_box["address"]
    else:
        dex_box = get_dex_box_from_tx(transaction)
        lp_tokens = dex_box["assets"][1]["amount"]
        dex_box_address = tree_to_address(dex_box['ergoTree'])

    return dex_box, lp_tokens, dex_box_address


def process_liquidation(pool, box, sig_usd_tx, sig_rsv_tx, total_due, interest_box, dummy_script):
    quote = pool["quotes"][1]
    logic_box = get_logic_box(quote["quoteScript"], quote["quoteNFT"])

    buffer_liquidation = int(box["additionalRegisters"]["R6"]["renderedValue"])
    curr_height = current_height()

    if buffer_liquidation == DEFAULT_BUFFER:
        # Prep liquidation: set buffer on collateral box
        dex_box = get_dex_box(quote["primarySupportedCollateral"]["DEXNFT"])
        transaction_to_sign = create_prep_transaction(pool, box, interest_box, dex_box, logic_box, dummy_script)
        logger.debug("Signing Prep Transaction: %s", json.dumps(transaction_to_sign))
        if transaction_to_sign is None:
            return [sig_usd_tx, sig_rsv_tx]
        tx_id = sign_tx(transaction_to_sign)
        if tx_id != -1 and tx_id != 1409:
            logger.info("Successfully submitted prep liquidation transaction with ID: %s", tx_id)
        else:
            logger.debug("Failed to submit prep liquidation transaction")
        return [sig_usd_tx, sig_rsv_tx]

    elif curr_height >= buffer_liquidation:
        if len(box["assets"]) > 1:
            # Multi-collateral: funding box liquidation (DEX is data input only)
            transaction_to_sign = create_multi_collateral_liquidation_tx(
                pool, box, total_due, interest_box, logic_box, dummy_script)
            if transaction_to_sign is None:
                return [sig_usd_tx, sig_rsv_tx]
            tx_id = sign_tx(transaction_to_sign)
            if tx_id != -1 and tx_id != 1409:
                logger.info("Successfully submitted multi-collateral liquidation: %s", tx_id)
            else:
                logger.debug("Failed to submit multi-collateral liquidation")
            return [sig_usd_tx, sig_rsv_tx]  # DEX not spent, no chaining needed
        else:
            # Existing single-collateral DEX swap flow
            dex_box, lp_tokens, dex_box_address = get_dex_box_and_tokens(
                sig_usd_tx, quote["primarySupportedCollateral"]["DEXNFT"])
            dex_initial_val = dex_box["value"]
            dex_tokens = dex_box["assets"][2]["amount"]
            tokens_to_liquidate = box["value"] - MIN_BOX_VALUE - 3 * TX_FEE
            dex_fee = quote["primarySupportedCollateral"]["dexFee"]
            liquidation_value = floor((dex_tokens * tokens_to_liquidate * dex_fee) /
                                      ((dex_initial_val + floor((dex_initial_val * 2 / 100))) * 1000 +
                                       (tokens_to_liquidate * dex_fee)))
            client_amount = floor((dex_tokens * tokens_to_liquidate * dex_fee) /
                                  ((dex_initial_val + floor((dex_initial_val * 1 / 100))) * 1000 +
                                   (tokens_to_liquidate * dex_fee))) - liquidation_value

            transaction_to_sign = create_liquidation_transaction(
                pool, dex_box, box, dex_initial_val, dex_tokens, tokens_to_liquidate,
                liquidation_value, client_amount, lp_tokens, dex_box_address,
                total_due, interest_box, logic_box, dummy_script)
            logger.debug("Signing Liquidation Transaction: %s", json.dumps(transaction_to_sign))
            if transaction_to_sign is None:
                return [sig_usd_tx, sig_rsv_tx]
            tx_id = sign_tx(transaction_to_sign)

            if tx_id != -1 and tx_id != 1409:
                logger.info("Successfully submitted liquidation transaction with ID: %s", tx_id)
                return [tx_id, sig_rsv_tx]
            else:
                logger.debug("Failed to submit liquidation transaction")
                return [sig_usd_tx, sig_rsv_tx]

    else:
        logger.info("Waiting for buffer to expire (height: %s, buffer: %s)", curr_height, buffer_liquidation)
        return [sig_usd_tx, sig_rsv_tx]


def t_liquidation_job_v2(pool, dummy_script, height):
    time.sleep(1)
    logger.info("Starting %s request processing", "liquidation")
    unspent_proxy_boxes = get_unspent_boxes_by_address(pool["collateral"])
    logger.debug(unspent_proxy_boxes)
    num_unspent_proxy_boxes = len(unspent_proxy_boxes)
    logger.info(f"Found: {num_unspent_proxy_boxes} boxes")

    tx = [None, None]
    interest_box = get_interest_box(pool["interest"], pool["INTEREST_NFT"])
    if len(unspent_proxy_boxes) > 0:
        for box in unspent_proxy_boxes:
            liquidation_response = liquidation_allowed_susd(box, interest_box, pool["quotes"][0]["primarySupportedCollateral"]["DEXNFT"], pool["liquidation_threshold"][0], height)
            if liquidation_response[0] == True:
                transaction_id = box["transactionId"]
                logger.debug(f"Liquidation Proxy Transaction Id: {transaction_id}")
                try:
                    tx = process_liquidation(pool, box, tx[0], tx[1], liquidation_response[1], interest_box, dummy_script)
                except Exception as e:
                    logger.exception(
                        f"Failed to process liquidation box for transaction id: {transaction_id}. Exception: {e}")
