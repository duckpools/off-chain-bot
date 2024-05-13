import json
import secrets
import requests

from consts import HTTP_NOT_FOUND
from client_consts import explorer_url, node_address, wallet_details
from helpers.generic_calls import logger, get_request


def get_unspent_boxes_by_address(addr, limit=70, offset=0):
    return json.loads(get_request(f"{explorer_url}/boxes/unspent/byAddress/{addr}?limit={limit}&offset={offset}").text)['items']

def get_box_from_id_explorer(box_id):
    """
    Get the UTXO box by its ID from Ergo platform explorer API.

    The function sends a GET request to retrieve the UTXO box by its ID.

    :param box_id: The ID of the UTXO box to retrieve.
    :return: The UTXO box if found, None if not found, or an error code if an error occurred.
    """
    try:
        response = get_request(f"{explorer_url}/boxes/{box_id}")

        if response == HTTP_NOT_FOUND:
            logger.warning(f"Box not found with ID: {box_id}")
            return None

        return json.loads(response.text)
    except requests.exceptions.RequestException as e:
        logger.error(f"Error while getting box by ID from explorer: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Error while decoding response from explorer: {e}")
        return None


# To do get randomised box
def get_dummy_box(dummy_script):
    boxes_json = get_unspent_boxes_by_address(dummy_script, 300)

    if not boxes_json:
        raise ValueError("No boxes found.")

    return secrets.choice(boxes_json)

def get_balance(node_address):
    url = f"https://api.ergoplatform.com/api/v1/addresses/{node_address}/balance/total"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()["confirmed"]["nanoErgs"]
    else:
        return None
def get_transactions(node_address):
    url = f"https://api.ergoplatform.com/api/v1/addresses/{node_address}/transactions"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()["total"]
    else:
        return None

if wallet_details == "true":
    balance = get_balance(node_address)/1000000000
    transaction = get_transactions(node_address)
    if balance:
        logger.info(f"The balance of {node_address} is {balance}")
    else:
        logger.info(f"Failed to retrieve balance for {address}")
    if transaction:
        logger.info(f"The total transaction count is {transaction}")
    else:
        logger.info(f"Failed to retrieve transactions for {node_address}")
else:
    logger.info("Skipping balance and transaction retrieval as wallet_details is set to 'false'")