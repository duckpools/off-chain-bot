import json

from consts import MIN_BOX_VALUE, TX_FEE, NULL_TX_OBJ, ERROR, LargeMultiplier, MAX_NETWORK_FEE, SLIPPAGE, DEX_FEE_DENOM
from helpers.explorer_calls import get_box_from_id_explorer
from helpers.job_helpers import job_processor
from helpers.node_calls import box_id_to_binary, sign_tx, tree_to_address
from helpers.platform_functions import get_interest_box, get_dex_box, get_logic_box, get_parent_box, get_head_child, \
    get_children_boxes, get_base_child
from helpers.serializer import encode_long_tuple, encode_coll_int
from logger import set_logger

logger = set_logger(__name__)


def find_quote_by_nft(pool, quote_nft):
    """Find the quote configuration matching the given quote NFT."""
    for quote in pool["quotes"]:
        if quote["quoteNFT"] == quote_nft:
            return quote
    return None


def bad_encode_arr(items):
    """Encode array of byte arrays (works up to size 9)."""
    resp = "1a0" + format(len(items), 'x')
    for item in items:
        resp += "20" + item
    return resp


def refund_repay_proxy_box(box):
    transaction_to_sign = \
    {
        "requests": [
            {
                "address": tree_to_address(box["additionalRegisters"]["R6"]["renderedValue"]),
                "value": box["value"] - TX_FEE,
                "assets": [
                    {
                        "tokenId": box["assets"][0]["tokenId"],
                        "amount": box["assets"][0]["amount"]
                    }
                ],
                "registers": {
                }
            }
        ],
        "fee": TX_FEE,
        "inputsRaw":
            [box_id_to_binary(box["boxId"])],
        "dataInputsRaw":
            []
    }

    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)
    if tx_id != ERROR:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    else:
        logger.info("Failed to submit transaction, attempting to refund")
    return

def process_repay_partial_proxy_box_v1(pool, box, empty):
    if box["assets"][0]["tokenId"] != pool["CURRENCY_ID"]:
        return

    collateral_box = box["additionalRegisters"]["R4"]["renderedValue"]
    final_borrow_tokens = int(box["additionalRegisters"]["R5"]["renderedValue"])
    whole_collateral_box = get_box_from_id_explorer(collateral_box)
    logger.debug("Whole collateral box: ", whole_collateral_box)
    if not whole_collateral_box or whole_collateral_box["spentTransactionId"] is not None:
        refund_repay_proxy_box(box)
        return

    parent_box = get_parent_box(pool["parent"], pool["PARENT_NFT"])
    head_child = get_head_child(pool["child"], pool["CHILD_NFT"], pool["parent"], pool["PARENT_NFT"])
    children = get_children_boxes(pool["child"], pool["CHILD_NFT"])
    loan_indexes = json.loads(whole_collateral_box["additionalRegisters"]["R5"]["renderedValue"])
    loan_parent_index = loan_indexes[0]
    base_child = get_base_child(children, loan_parent_index)
    interest_box = get_interest_box(pool["child"], pool["CHILD_NFT"])
    dex_nft = whole_collateral_box["additionalRegisters"]["R7"]["renderedValue"]
    dex_box = get_dex_box(dex_nft)

    if not interest_box:
        logger.debug("No Interest Box Found")
        return

    transaction_to_sign = \
        {
            "requests": [
                {
                    "address": whole_collateral_box["address"],
                    "value": whole_collateral_box["value"],
                    "assets": [
                        {
                            "tokenId": whole_collateral_box["assets"][0]["tokenId"],
                            "amount": final_borrow_tokens
                        }
                    ],
                    "registers": {
                        "R4": whole_collateral_box["additionalRegisters"]["R4"]["serializedValue"],
                        "R5": whole_collateral_box["additionalRegisters"]["R5"]["serializedValue"],
                        "R6": whole_collateral_box["additionalRegisters"]["R6"]["serializedValue"],
                        "R7": whole_collateral_box["additionalRegisters"]["R7"]["serializedValue"],
                        "R8": whole_collateral_box["additionalRegisters"]["R8"]["serializedValue"],
                        "R9": whole_collateral_box["additionalRegisters"]["R9"]["serializedValue"]
                    }
                },
                {
                    "address": pool["repayment"],
                    "value": MIN_BOX_VALUE + TX_FEE,
                    "assets": [
                        {
                            "tokenId": whole_collateral_box["assets"][0]["tokenId"],
                            "amount": int(whole_collateral_box["assets"][0]["amount"]) - final_borrow_tokens
                        },
                        {
                            "tokenId": box["assets"][0]["tokenId"],
                            "amount": box["assets"][0]["amount"]
                        }
                    ],
                    "registers": {
                    }

                }
            ],
            "fee": TX_FEE,
            "inputsRaw":
                [box_id_to_binary(box["boxId"]), box_id_to_binary(collateral_box)],
            "dataInputsRaw":
                [box_id_to_binary(base_child["boxId"]),box_id_to_binary(parent_box["boxId"]),
                  box_id_to_binary(head_child["boxId"]), box_id_to_binary(dex_box["boxId"])]
        }

    logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
    tx_id = sign_tx(transaction_to_sign)
    if tx_id != ERROR:
        logger.info("Successfully submitted transaction with ID: %s", tx_id)
    else:
        logger.info("Failed to submit transaction, attempting to refund")
        refund_repay_proxy_box(box)
    return


def process_repay_partial_proxy_box_v2(pool, box, empty):
    if len(box["assets"]) == 0 or box["assets"][0]["tokenId"] != pool["CURRENCY_ID"]:
        return

    try:
        collateral_box_id = box["additionalRegisters"]["R4"]["renderedValue"]
        final_borrow_tokens = int(box["additionalRegisters"]["R5"]["renderedValue"])
        whole_collateral_box = get_box_from_id_explorer(collateral_box_id)
        logger.debug("Whole collateral box: %s", whole_collateral_box)
        if not whole_collateral_box or whole_collateral_box["spentTransactionId"] is not None:
            refund_repay_proxy_box(box)
            return

        interest_box = get_interest_box(pool["interest"], pool["INTEREST_NFT"])
        if not interest_box:
            logger.debug("No Interest Box Found")
            return

        # Get quote by NFT from collateral box R7
        collateral_quote_nft = whole_collateral_box["additionalRegisters"]["R7"]["renderedValue"]
        quote = find_quote_by_nft(pool, collateral_quote_nft)
        if not quote:
            logger.warning("Quote NFT not found in pool configuration: %s", collateral_quote_nft)
            refund_repay_proxy_box(box)
            return

        # Get primary DEX box and logic box
        primary_dex_nft = quote["primarySupportedCollateral"]["DEXNFT"]
        dex_box = get_dex_box(primary_dex_nft)
        if not dex_box:
            logger.warning("Primary DEX box not found")
            refund_repay_proxy_box(box)
            return

        logic_box = get_logic_box(quote["quoteScript"], quote["quoteNFT"])
        if not logic_box:
            logger.warning("Logic box not found")
            refund_repay_proxy_box(box)
            return

        # Read values from DEX box (NOT from config)
        dex_initial_val = dex_box["value"]
        dex_tokens = dex_box["assets"][2]["amount"]
        dex_fee = int(dex_box["additionalRegisters"]["R4"]["renderedValue"])

        # Read threshold from logic box R6
        asset_thresholds = json.loads(logic_box["additionalRegisters"]["R6"]["renderedValue"])
        primary_threshold = asset_thresholds[0]

        # Get iReport for output logic box
        iReport = json.loads(logic_box["additionalRegisters"]["R4"]["renderedValue"])

        # Collateral value
        collateral_value = whole_collateral_box["value"]

        # Detect secondary collateral tokens (tokens beyond the borrow token at index 0)
        secondary_collateral_config = quote.get("secondarySupportedCollateral", [])
        collateral_tokens = whole_collateral_box["assets"][1:] if len(whole_collateral_box["assets"]) > 1 else []

        # Calculate secondary collateral ERG value if present
        secondary_erg_value = 0
        secondary_dex_boxes = []
        ordered_amounts = []
        ordered_asset_ids = []
        secondary_values_and_thresholds = []

        # ALWAYS process all assets defined in the quote config, even if collateral box doesn't have them
        if len(secondary_collateral_config) > 0:
            token_amounts = {token["tokenId"]: token["amount"] for token in collateral_tokens}
            secondary_thresholds = asset_thresholds[1:] if len(asset_thresholds) > 1 else []

            for i, secondary in enumerate(secondary_collateral_config):
                sec_dex_box = get_dex_box(secondary["DEXNFT"])
                if not sec_dex_box:
                    logger.warning("Secondary DEX box not found: %s", secondary["DEXNFT"])
                    refund_repay_proxy_box(box)
                    return
                secondary_dex_boxes.append(sec_dex_box)

                # Get asset ID from DEX box (not from config)
                asset_id = sec_dex_box["assets"][2]["tokenId"]
                input_amount = token_amounts.get(asset_id, 0)  # Will be 0 if asset not in collateral box
                ordered_amounts.append(input_amount)
                ordered_asset_ids.append(asset_id)

                if input_amount > 0:
                    sec_dex_fee = int(sec_dex_box["additionalRegisters"]["R4"]["renderedValue"])
                    sec_dex_reserves_erg = sec_dex_box["value"]
                    sec_dex_reserves_token = sec_dex_box["assets"][2]["amount"]

                    # DEX formula for secondary collateral ERG value
                    sec_value = (sec_dex_reserves_erg * input_amount * sec_dex_fee) // \
                        (((sec_dex_reserves_token * (100 + SLIPPAGE)) // 100) * DEX_FEE_DENOM +
                         (input_amount * sec_dex_fee))

                    secondary_erg_value += sec_value
                    threshold = secondary_thresholds[i] if i < len(secondary_thresholds) else primary_threshold
                    secondary_values_and_thresholds.append((sec_value, threshold))

        # Calculate total box value
        total_box_value = collateral_value + secondary_erg_value - MAX_NETWORK_FEE

        # Calculate liquidation value (quote price) using integer division
        # IMPORTANT: Must calculate slippage before division to avoid integer division truncation
        liquidation_value = (dex_tokens * total_box_value * dex_fee) // \
            (((dex_initial_val * (100 + SLIPPAGE)) // 100) * DEX_FEE_DENOM +
             (total_box_value * dex_fee))

        # Calculate aggregate threshold (weighted by contribution)
        aggregate_sum = (collateral_value * LargeMultiplier * primary_threshold) // total_box_value
        for sec_value, sec_threshold in secondary_values_and_thresholds:
            aggregate_sum += (sec_value * LargeMultiplier * sec_threshold) // total_box_value
        aggregateThreshold = aggregate_sum // LargeMultiplier
        print(aggregateThreshold)
        print(iReport[0], liquidation_value, aggregateThreshold, iReport[3], iReport[4], iReport[5], iReport[6], iReport[7], iReport[8], iReport[9])

        # Build output collateral assets - preserve all secondary tokens
        output_collateral_assets = [
            {"tokenId": whole_collateral_box["assets"][0]["tokenId"], "amount": final_borrow_tokens}
        ]
        for token in collateral_tokens:
            output_collateral_assets.append({"tokenId": token["tokenId"], "amount": token["amount"]})

        # Encode R7 (ordered amounts) and R8 (ordered asset IDs)
        # ALWAYS encode if there are secondary assets defined in the quote config
        if len(secondary_collateral_config) > 0:
            r7_value = encode_long_tuple(ordered_amounts)
            r8_value = bad_encode_arr(ordered_asset_ids)
        else:
            r7_value = "1100"  # Empty long array
            r8_value = "1a00"  # Empty byte array collection
        # R9: [boxIndex, dexStartIndex]
        # Output collateral is at OUTPUTS(0), so boxIndex = 1
        # Primary DEX is at dataInputs(1), so dexStartIndex = 1
        r9_value = encode_coll_int([1, 1])

        # Build data inputs - include secondary DEX boxes
        data_inputs_raw = [
            box_id_to_binary(interest_box["boxId"]),
            box_id_to_binary(dex_box["boxId"])
        ]
        for sec_dex in secondary_dex_boxes:
            data_inputs_raw.append(box_id_to_binary(sec_dex["boxId"]))

        transaction_to_sign = \
            {
                "requests": [
                    {
                        "address": whole_collateral_box["address"],
                        "value": whole_collateral_box["value"],
                        "assets": output_collateral_assets,
                        "registers": {
                            "R4": whole_collateral_box["additionalRegisters"]["R4"]["serializedValue"],
                            "R5": whole_collateral_box["additionalRegisters"]["R5"]["serializedValue"],
                            "R6": whole_collateral_box["additionalRegisters"]["R6"]["serializedValue"],
                            "R7": whole_collateral_box["additionalRegisters"]["R7"]["serializedValue"],
                            "R8": whole_collateral_box["additionalRegisters"]["R8"]["serializedValue"],
                            "R9": whole_collateral_box["additionalRegisters"]["R9"]["serializedValue"]
                        }
                    },
                    {
                        "address": pool["repayment"],
                        "value": MIN_BOX_VALUE + TX_FEE,
                        "assets": [
                            {
                                "tokenId": whole_collateral_box["assets"][0]["tokenId"],
                                "amount": int(whole_collateral_box["assets"][0]["amount"]) - final_borrow_tokens
                            },
                            {
                                "tokenId": box["assets"][0]["tokenId"],
                                "amount": box["assets"][0]["amount"]
                            }
                        ],
                        "registers": {
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
                            "R4": encode_long_tuple([iReport[0], liquidation_value, aggregateThreshold, iReport[3], iReport[4], iReport[5], iReport[6], iReport[7], iReport[8], iReport[9]]),
                            "R5": logic_box["additionalRegisters"]["R5"]["serializedValue"],
                            "R6": logic_box["additionalRegisters"]["R6"]["serializedValue"],
                            "R7": r7_value,
                            "R8": r8_value,
                            "R9": r9_value
                        }
                    }
                ],
                "fee": TX_FEE,
                "inputsRaw":
                    [box_id_to_binary(box["boxId"]), box_id_to_binary(collateral_box_id), box_id_to_binary(logic_box["boxId"])],
                "dataInputsRaw": data_inputs_raw
            }
        print(transaction_to_sign)
        logger.debug("Signing Transaction: %s", json.dumps(transaction_to_sign))
        tx_id = sign_tx(transaction_to_sign)
        if tx_id != ERROR:
            logger.info("Successfully submitted transaction with ID: %s", tx_id)
        else:
            logger.info("Failed to submit transaction, attempting to refund")
            refund_repay_proxy_box(box)

    except Exception as e:
        logger.error("Exception during partial repay transaction processing: %s", str(e))
        refund_repay_proxy_box(box)

    return


def t_partial_repay_proxy_job(pool):
    job_processor(pool, pool["proxy_partial_repay"], NULL_TX_OBJ, process_repay_partial_proxy_box_v1, process_repay_partial_proxy_box_v2, "PARTIAL REPAYMENT", 1535250)
