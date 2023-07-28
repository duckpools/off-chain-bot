import json

import requests

from consts import explorer_url, HTTP_NOT_FOUND
from helpers.generic_calls import logger, get_request


def get_unspent_boxes_by_address(addr, limit=50):
    return json.loads(get_request(f"{explorer_url}/boxes/unspent/byAddress/{addr}?limit={limit}").text)['items']


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
