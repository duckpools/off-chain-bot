import json
import time
from math import floor

from consts import DEX_ADDRESS, INTEREST_MULTIPLIER, LIQUIDATION_THRESHOLD, SIG_USD_ID, ERG_USD_DEX_NFT, SIG_RSV_ID, \
    ERG_RSV_DEX_NFT, BORROW_TOKEN_ID
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

def get_logic_box(address, nft):
    potential_boxes = get_unspent_boxes_by_address(address)
    for box in potential_boxes:
        if len(box["assets"]) > 0 and box["assets"][0]["tokenId"] == nft:
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


def add_pool_to_list(pools_list, new_pool):
    pools_list.append(new_pool)
    return pools_list

def format_dict_to_python_string(data):
    """
    Converts the dictionary back to a Python code representation with proper formatting.
    """
    formatted_str = '{\n'
    for key, value in data.items():
        if isinstance(value, str):
            formatted_str += f"    '{key}': '{value}',\n"
        elif isinstance(value, bool):
            # Correct capitalization for boolean values
            value_str = 'True' if value else 'False'
            formatted_str += f"    '{key}': {value_str},\n"
        elif isinstance(value, list):
            formatted_str += f"    '{key}': {value},\n"
        else:
            formatted_str += f"    '{key}': {value},\n"
    formatted_str += '}'
    return formatted_str

def format_list_to_python_string(data):
    """
    Converts the list back to a Python code representation with proper formatting.
    """
    formatted_str = '[\n'
    for item in data:
        formatted_str += '    ' + format_dict_to_python_string(item) + ',\n'
    formatted_str += ']'
    return formatted_str

def update_pools_in_file(new_pool):
    file_path = "proposed_pools.py"
    with open(file_path, 'r') as file:
        lines = file.readlines()

    start_idx = end_idx = None
    for i, line in enumerate(lines):
        if 'pools =' in line:
            start_idx = i
        if start_idx is not None and line.strip() == ']':
            end_idx = i
            break

    if start_idx is not None and end_idx is not None:
        pools_lines = lines[start_idx:end_idx+1]
        pools_str = ''.join(pools_lines)
        import re
        pools_str = re.sub(r'#.*', '', pools_str)  # Remove comments for safe parsing
        pools_str = pools_str.split('=', 1)[1].strip()

        # Convert string to list using ast.literal_eval
        import ast
        try:
            pools_list = ast.literal_eval(pools_str)
        except SyntaxError:
            pools_list = []

        # Append the new pool to the list
        updated_pools_list = add_pool_to_list(pools_list, new_pool)

        # Format the updated list to a Python string without extra brackets
        formatted_pools_str = 'pools = ' + format_list_to_python_string(updated_pools_list) + '\n'

        # Replace the old pools list in the lines
        updated_lines = lines[:start_idx] + [formatted_pools_str] + lines[end_idx+1:]
    else:
        # Handle the case where pools are defined but empty or not properly defined
        updated_pools_list = add_pool_to_list([], new_pool)
        formatted_pools_str = 'pools = ' + format_list_to_python_string(updated_pools_list) + '\n'
        updated_lines = lines + [formatted_pools_str]

    with open(file_path, 'w') as file:
        file.writelines(updated_lines)
