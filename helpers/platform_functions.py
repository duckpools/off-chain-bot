import json
import time
from math import floor

from consts import DEX_ADDRESS, INTEREST_MULTIPLIER, LIQUIDATION_THRESHOLD, SIG_USD_ID, ERG_USD_DEX_NFT, SIG_RSV_ID, \
    ERG_RSV_DEX_NFT, BORROW_TOKEN_ID, REQUEST_DELAY
from helpers.explorer_calls import get_unspent_boxes_by_address
from helpers.generic_calls import logger, get_request
from helpers.node_calls import first_output_from_mempool_tx
from helpers.serializer import extract_number


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


def liquidation_allowed_susd(box, interest_box, nft, liquidation_threshold, height):
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
        liquidation_forced = json.loads(box["additionalRegisters"]["R6"]["renderedValue"])[0]
        borrow_token_value = extract_number(interest_box["additionalRegisters"]["R5"]["renderedValue"])
        total_due = loan_amount * borrow_token_value / 10000000000000000
        # total_due += 2
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


def get_all_boxes_by_token_id(
        token_id,
        limit=100,
        max_retries=5,
        delay=REQUEST_DELAY,
        progress_interval=10,
        headers=None
):
    """
    Fetch all boxes for a given token ID from the Ergo Platform API.

    :param token_id: The token ID to search for
    :param limit: Number of items per request (default: 100)
    :param max_retries: Maximum number of retries per request (default: 5)
    :param delay: Delay between retries in seconds (default: REQUEST_DELAY)
    :param progress_interval: Print progress every N requests (default: 10)
    :param headers: Custom headers for requests (default: None, uses global headers)
    :return: List of all boxes for the token ID
    :raises: Exception if unable to fetch data after retries
    """

    base_url = 'https://api.ergoplatform.com/api/v1/boxes/byTokenId/'
    all_boxes = []
    offset = 0
    total = None
    request_count = 0

    print(f"Starting to fetch boxes for token ID: {token_id}")

    while True:
        request_count += 1

        # Show progress periodically
        if request_count % progress_interval == 0 or request_count == 1:
            progress = f"{len(all_boxes)}/{total}" if total is not None else str(len(all_boxes))
            print(f"Progress: Request #{request_count}, Boxes collected: {progress}")

        # Construct URL with parameters
        url = f"{base_url}{token_id}?offset={offset}&limit={limit}"

        # Make request using the provided get_request function
        response = get_request(url, headers=headers, max_retries=max_retries, delay=delay)

        # Handle different response types
        if response is None:
            raise Exception(f"Failed to fetch data after {max_retries} retries")

        if response == 404:
            print(f"Token ID '{token_id}' not found (404)")
            return []

        # Parse JSON response
        try:
            data = response.json()
        except ValueError as e:
            raise Exception(f"Failed to parse JSON response: {e}")

        # Set total on first successful response
        if total is None:
            total = data.get('total', 0)
            print(f"Total boxes to fetch: {total}")

            if total == 0:
                print("No boxes found for this token ID")
                return []

        # Add boxes from current response
        items = data.get('items', [])
        if items:
            all_boxes.extend(items)
            offset += len(items)

        # Check if we've collected all boxes
        if len(all_boxes) >= total or len(items) == 0:
            break

    print(f"Completed! Collected {len(all_boxes)} boxes in {request_count} requests")
    return all_boxes


def get_transaction_timestamp(transaction_id, max_retries=5, delay=REQUEST_DELAY, headers=None):
    """
    Fetch the timestamp of a transaction from the Ergo Platform API.

    :param transaction_id: The transaction ID to fetch
    :param max_retries: Maximum number of retries per request (default: 5)
    :param delay: Delay between retries in seconds (default: REQUEST_DELAY)
    :param headers: Custom headers for requests (default: None, uses global headers)
    :return: Transaction timestamp, or None if not found/error
    """

    base_url = 'https://api.ergoplatform.com/api/v1/transactions/'
    url = f"{base_url}{transaction_id}"

    # Make request using the provided get_request function
    response = get_request(url, headers=headers, max_retries=max_retries, delay=delay)

    # Handle different response types
    if response is None:
        print(f"Failed to fetch transaction after {max_retries} retries")
        return None

    if response == 404:
        print(f"Transaction '{transaction_id}' not found (404)")
        return None

    # Parse JSON response
    try:
        data = response.json()
        timestamp = data.get('timestamp')
        return timestamp
    except ValueError as e:
        print(f"Failed to parse JSON response: {e}")
        return None