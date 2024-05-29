import json
import time
from math import floor, sqrt

import numpy as np
import scipy.stats as stats

from consts import DEX_ADDRESS, INTEREST_MULTIPLIER, LIQUIDATION_THRESHOLD, SIG_USD_ID, ERG_USD_DEX_NFT, SIG_RSV_ID, \
    ERG_RSV_DEX_NFT, BORROW_TOKEN_ID, CDF_ADDRESS, CDF_NFT
from helpers.explorer_calls import get_unspent_boxes_by_address
from helpers.generic_calls import logger
from helpers.node_calls import first_output_from_mempool_tx


def get_dex_box(token, start_limit=5, max_limit=200):
    """
    Get the dex box with the specified token from unspent boxes.

    :param token: The token ID to search for.
    :param start_limit: The initial number of boxes to search.
    :param max_limit: The maximum number of boxes to search.
    :return: The dex box containing the specified token, or None if not found.
    """
    limit = start_limit

    while limit <= max_limit:
        unspent_boxes = get_unspent_boxes_by_address(DEX_ADDRESS, limit)

        for box in unspent_boxes:
            try:
                if box["assets"][0]["tokenId"] == token:
                    return box
            except Exception as e:
                logger.info(e)

        limit *= 2  # Double the limit for the next iteration

    logger.warning("Could not find dex_box")
    return None

def get_pool_box_from_tx(tx):
    return first_output_from_mempool_tx(tx)


def get_pool_box(pool_address, pool_nft):
    """
    Find and return the Ergo pool box in the unspent boxes associated with the specified address.

    Returns:
        dict: The Ergo pool box if found.
        None: If the Ergo pool box is not found.
    """
    potential_boxes = get_unspent_boxes_by_address(pool_address)
    for box in potential_boxes:
        if len(box["assets"]) > 0 and box["assets"][0]["tokenId"] == pool_nft:
            return box
    logger.warning("Could not find pool box")
    return None


def get_parent_box(address, nft):
    found_boxes = get_unspent_boxes_by_address(address)
    for parent_box in found_boxes:
        if parent_box["assets"] and parent_box["assets"][0]["tokenId"] == nft:
            return parent_box


def get_head_child(child_address, child_nft, parent_address, parent_nft, parent_box = None):
    found_boxes = get_unspent_boxes_by_address(child_address)
    time.sleep(0.5)
    if not parent_box:
        parent_box = get_parent_box(parent_address, parent_nft)
    for box in found_boxes:
        if box["assets"] and box["assets"][0]["tokenId"] == child_nft:
            if int(box["additionalRegisters"]["R6"]["renderedValue"]) == len(json.loads(parent_box["additionalRegisters"]["R4"]["renderedValue"])):
                return box


def get_interest_box(address, nft):
    res = get_unspent_boxes_by_address(address)
    for box in res:
        if box["assets"][0]["tokenId"] == nft:
            return box
    logger.warning("Could not find interest box")
    return None


def get_interest_param_box(address, nft):
    potential_boxes = get_unspent_boxes_by_address(address)
    for box in potential_boxes:
        if len(box["assets"]) > 0 and box["assets"][0]["tokenId"] == nft:
            return box
    logger.warning("Could not find pool box")
    return None


def calculate_service_fee(change_amount, thresholds):
    step_one_threshold = thresholds[0]
    step_two_threshold = thresholds[1]
    divisor_one = 160
    divisor_two = 200
    divisor_three = 250

    if change_amount <= step_one_threshold:
        return change_amount / divisor_one
    elif change_amount <= step_two_threshold:
        return (change_amount - step_one_threshold) / divisor_two + step_one_threshold / divisor_one
    else:
        return (change_amount - step_two_threshold - step_one_threshold) / divisor_three + step_two_threshold / divisor_two + step_one_threshold / divisor_one


def calculate_final_amount(total_amount, thresholds, precision=0.01):
    lower_bound = 0
    upper_bound = total_amount
    mid_point = (upper_bound + lower_bound) / 2.0
    counter = 0

    while counter < 200 and abs(total_amount - calculate_service_fee(mid_point, thresholds) - mid_point) > precision:
        counter += 1
        mid_point = (upper_bound + lower_bound) / 2.0
        if mid_point + calculate_service_fee(mid_point, thresholds) > total_amount:
            upper_bound = mid_point
        else:
            lower_bound = mid_point

    service_fee = calculate_service_fee(mid_point, thresholds)
    return int(service_fee)


def get_pool_param_box(param_address, param_nft):
    potential_boxes = get_unspent_boxes_by_address(param_address)
    for box in potential_boxes:
        if len(box["assets"]) > 0 and box["assets"][0]["tokenId"] == param_nft:
            return box
    logger.warning("Could not find pool box")
    return None


def get_dex_box_from_tx(tx):
    return first_output_from_mempool_tx(tx)


def apply_interest(rates, start, base):
    index = start
    while index < len(rates):
        base = floor(rates[index]  * base/ INTEREST_MULTIPLIER)
        index += 1
    return base


def get_base_child(children, child_index):
    for child in children:
        if int(child["additionalRegisters"]["R6"]["renderedValue"]) == child_index:
            return child


def total_owed(principal, loan_indexes, parent_box, head_child, children):
    """
    Calculate the total owed amount based on the interest rates in the given interest box.

    Args:
        principal: The initial amount.
        start_index: The index to start calculating interest from.
        interest_box: The interest box containing interest rates.

    Returns:
        The total owed amount after applying interest rates.
    """
    loan_parent_index = loan_indexes[0]
    loan_child_index = loan_indexes[1]
    parent_interest_rates = json.loads(parent_box["additionalRegisters"]["R4"]["renderedValue"])
    base_child = get_base_child(children, loan_parent_index)
    num_children = len(parent_interest_rates)
    compounded_interest = INTEREST_MULTIPLIER

    base_child_rates = json.loads(base_child["additionalRegisters"]["R4"]["renderedValue"])
    compounded_interest = apply_interest(base_child_rates, loan_child_index, compounded_interest)

    if num_children == loan_parent_index:
        return floor(principal * compounded_interest / INTEREST_MULTIPLIER)
    else:
        head_child_rates = json.loads(head_child["additionalRegisters"]["R4"]["renderedValue"])
        compounded_interest = apply_interest(head_child_rates, 0, compounded_interest)
        if num_children == loan_parent_index + 1:
            return principal * compounded_interest / INTEREST_MULTIPLIER
        else:
            return apply_interest(parent_interest_rates, loan_parent_index + 1, compounded_interest) * principal / INTEREST_MULTIPLIER


def liquidation_allowed_susd(box, parent_box, head_child, children, nft, liquidation_threshold, height):
    """
    Check if liquidation is allowed for a given box and interest box.

    Args:
        box: The box to check for liquidation.
        interest_box: The interest box containing interest rates.

    Returns:
        bool: True if liquidation is allowed, False otherwise.
    """
    try:
        dex_box = get_dex_box(nft)
        loan_amount = int(box["assets"][0]["amount"])
        loan_indexes = json.loads(box["additionalRegisters"]["R5"]["renderedValue"])
        liquidation_forced = json.loads(box["additionalRegisters"]["R9"]["renderedValue"])[0]
        total_due = total_owed(loan_amount, loan_indexes, parent_box, head_child, children)
        total_due += 2
        collateral_amount = int(box["value"] - 4000000)
        collateral_value = ((int(dex_box["assets"][2]["amount"]) * collateral_amount * int(
            dex_box["additionalRegisters"]["R4"]["renderedValue"])) /
                            ((int(dex_box["value"]) +
                              (int(dex_box["value"]) * 2) / 100) *
                             1000 +
                             collateral_amount *
                             int(dex_box["additionalRegisters"]["R4"]["renderedValue"])))
        if int(liquidation_forced) < int(height):
            return [True, total_due]
        return [collateral_value <= ((total_due * liquidation_threshold) / 1000), total_due]
    except (KeyError, IndexError, ValueError, TypeError):
        logger.exception("Error captured when calculating liquidation_allowed for box %s", json.dumps(box))
        return [False, False]


def get_children_boxes(address, nft):
    found_boxes = get_unspent_boxes_by_address(address)
    res = []
    for box in found_boxes:
        if box["assets"] and box["assets"][0]["tokenId"] == nft:
            res.append(box)
    return res


def liquidation_allowed(box, parent_box, head_child, children, height):
    """
    Check if liquidation is allowed for a given box and interest box.

    Args:
        box: The box to check for liquidation.
        interest_box: The interest box containing interest rates.

    Returns:
        bool: True if liquidation is allowed, False otherwise.
    """
    try:
        asset_token_id = box["assets"][0]['tokenId']

        if asset_token_id == SIG_USD_ID:
            dex_box = get_dex_box(ERG_USD_DEX_NFT)
        elif asset_token_id == SIG_RSV_ID:
            dex_box = get_dex_box(ERG_RSV_DEX_NFT)
        else:
            return False

        collateral_value = ((int(dex_box["value"]) * int(box["assets"][0]["amount"]) * int(dex_box["additionalRegisters"]["R4"]["renderedValue"])) /
        ((int(dex_box["assets"][2]["amount"]) +
          (int(dex_box["assets"][2]["amount"]) * 2) / 100) *
         1000 +
         int(box["assets"][0]["amount"]) *
         int(dex_box["additionalRegisters"]["R4"]["renderedValue"])) - 4000000)
        liquidation_forced = json.loads(box["additionalRegisters"]["R9"]["renderedValue"])[0]
        loan_amount = int(box["assets"][1]["amount"])
        loan_indexes = json.loads(box["additionalRegisters"]["R5"]["renderedValue"])
        total_due = total_owed(loan_amount, loan_indexes, parent_box, head_child, children)
        if int(liquidation_forced) < int(height):
            return [True, total_due]
        return [collateral_value <= ((total_due * LIQUIDATION_THRESHOLD) / 1000)
            and box["assets"][1]["tokenId"] == BORROW_TOKEN_ID, total_due]
    except (KeyError, IndexError, ValueError, TypeError):
        logger.exception("Error captured when calculating liquidation_allowed for box %s", json.dumps(box))
        return [False, False]


def get_CDF_box():
    found_boxes = get_unspent_boxes_by_address(CDF_ADDRESS)
    res = []
    for box in found_boxes:
        if box["assets"] and box["assets"][0]["tokenId"] == CDF_NFT:
            return box
    return None

def calculate_call_price(S, σ, r, K, t_hint, t_block):
    P = 1000000
    minutes_in_a_year = 262800

    t = floor((t_block - t_hint) * P / minutes_in_a_year)
    print(t)

    i = S / K
    y = floor(sqrt(sqrt(sqrt(i))) * P)
    x = y - P

    lnSK = (
                   x -
                   floor((x * x) / (2 * P)) +
                   floor((x * x * x) / (3 * P * P)) -
                   floor((x * x * x * x) / (4 * P * P * P)) +
                   floor((x * x * x * x * x) / (5 * P * P * P * P)) -
                   floor((x * x * x * x * x * x) / (6 * P * P * P * P * P))
           ) * 8

    sqrtT = floor(sqrt(t / P) * P)
    print(σ)
    print(sqrtT)
    d11 = floor((P * P * lnSK) / (σ * sqrtT))
    d12 = floor((t * P * r) / (σ * sqrtT))
    d13 = floor((σ * t) / (2 * sqrtT))
    d1 = d11 + d12 + d13
    d2 = d1 - floor((σ * sqrtT) / P)
    print(d1)
    print(d2)

    j = floor(r * t / P)
    ans = (
            P -
            j +
            floor((j * j) / (2 * P)) -
            floor((j * j * j) / (6 * P * P)) +
            floor((j * j * j * j) / (24 * P * P * P))
    )

    def calculate_cdf(d_in, x_values, cdf_values):
        i = 0
        d = max(d_in, -d_in)
        while i < len(x_values):
            if x_values[i] > d:
                if d_in < 0:
                    return (P - cdf_values[i - 1], i - 1)
                return (cdf_values[i - 1], i - 1)
            i += 1
        if d_in < 0:
            (P - cdf_values[i - 1], i - 1)
        return (cdf_values[i - 1], i - 1)

    # Generate the values from 0 to 3.1 with increments of 0.005
    x_values = np.arange(0, 3.105, 0.02)
    cdf_values = stats.norm.cdf(x_values).tolist()
    cdf_values = [floor(val * P) for val in cdf_values]
    x_vals = x_values.tolist()
    x_vals = [floor(val * P) for val in x_vals]

    nd1, nd1i = calculate_cdf(d1, x_vals, cdf_values)
    nd2, nd2i = calculate_cdf(d2, x_vals, cdf_values)
    return [floor((nd1 * S)) - floor((nd2 * K * ans) / (P)), y, sqrtT, nd1i, nd2i]


def get_spot_price():
    return 122

def get_volatility():
    return 650000
