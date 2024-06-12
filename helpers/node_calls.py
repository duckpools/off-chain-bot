import json

import requests

from consts import ERROR, DOUBLE_SPENDING_ATTEMPT, HTTP_OK, HTTP_NOT_FOUND, TX_FEE
from client_consts import node_url, headers, node_pass, node_address
from helpers.generic_calls import logger, get_request


def unlock_wallet():
    response = requests.post(f"{node_url}/wallet/unlock", json={"pass": node_pass}, headers=headers)
    logger.debug(f"Unlock wallet response status code: {response.status_code}")
    return response.status_code


def current_height():
    return json.loads(get_request(node_url + "/blocks/lastHeaders/1").text)[0]['height']


def tree_to_address(addr):
    return json.loads(get_request(node_url + "/utils/ergoTreeToAddress/" + addr).text)["address"]


def box_id_to_binary(box_id):
    return json.loads(get_request(node_url + "/utxo/withPool/byIdBinary/" + box_id).text)["bytes"]


def sign_tx(tx):
    """
    Signs a transaction by sending it to the node, then logs and returns the response.

    This function makes a POST request to the "/wallet/transaction/send" endpoint of the node with
    the given transaction. It logs the full text of the response and its status code, and then prints them.
    If the response text contains "Double spending attempt", it returns a predefined error code for that.
    If the status code is not 200, it returns a generic error code.
    If the status code is 200, it attempts to parse the response text as JSON and return it.

    If a requests exception occurs during the POST request, it is logged and a generic error code is returned.
    If a JSON decoding error occurs when parsing the response, it is logged and a generic error code is returned.

    :param tx: The transaction to be signed and sent.
    :return: The parsed JSON response if successful, or an error code if not.
    :raises: Does not raise any exceptions, but logs errors and returns error codes.
    """
    try:
        res = requests.post(node_url + "/wallet/transaction/send", json=tx, headers=headers)
    except requests.exceptions.RequestException as e:
        logger.error("Request error: %s", e)
        return ERROR

    logger.debug("Request Response: %s", res.text)
    print(res.text)
    print(res.status_code)

    if "Double spending attempt" in res.text:
        return DOUBLE_SPENDING_ATTEMPT
    elif res.status_code != HTTP_OK:
        return ERROR

    try:
        return json.loads(res.text)
    except json.JSONDecodeError as e:
        logger.error("Failed to decode JSON: %s", e)
        return ERROR


def first_output_from_mempool_tx(tx):
    """
    Get the first output of a specific transaction from mempool.

    The function sends a GET request to retrieve a list of unconfirmed transactions.
    It then iterates over these transactions looking for the one matching the given ID.
    If found, it returns the first output of this transaction.

    :param tx: The ID of the transaction to search for.
    :return: The first output of the transaction if found, None otherwise.
    """

    try:
        response = get_request(node_url + "/transactions/unconfirmed?limit=100&offset=0")
        transactions = json.loads(response.text)
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        logger.error("Error while getting unconfirmed transactions: %s", e)
        return None

    for transaction in transactions:
        if transaction["id"] == tx:
            return transaction["outputs"][0]

    logger.info("No transaction found with id: %s", tx)
    return None


def get_box_from_id(box_id):
    """
    Get the UTXO box by its ID.

    The function sends a GET request to retrieve the UTXO box by its ID.

    :param box_id: The ID of the UTXO box to retrieve.
    :return: The UTXO box if found, None if not found, or an error code if an error occurred.
    """
    try:
        response = get_request(f"{node_url}/utxo/byId/{box_id}")

        if response == HTTP_NOT_FOUND:
            logger.warning(f"Box not found with ID: {box_id}")
            return None

        return json.loads(response.text)
    except requests.exceptions.RequestException as e:
        logger.error(f"Error while getting box by ID: {e}")
        return ERROR
    except json.JSONDecodeError as e:
        logger.error(f"Error while decoding response: {e}")
        return ERROR

def generate_dummy_script(node_address):
    script_payload = {
        "source": f"PK(\"{node_address}\") && HEIGHT >= -1"
    }
    try:
        # Making the POST request
        response = requests.post(f"{node_url}/script/p2sAddress", json=script_payload, headers=headers)

        # Checking if the request was successful
        if response.status_code == 200:
            # Parse the JSON response
            parsed_response = json.loads(response.text)
            return parsed_response["address"]

        else:
            print(f"Error: Received status code {response.status_code}")
            print(f"Message: {response.text}")
            return None

    except requests.RequestException as e:
        print(f"An error occurred while making the request: {e}")
        return None


def mint_token(recipient, name, description, decimals, amount, ergValue=2000000):
    transaction_to_sign = \
        {
            "requests": [
                {
                  "address": recipient,
                  "ergValue": 2000000,
                  "amount": 1,
                  "name": name,
                  "description": description,
                  "decimals": 0,
                  "registers": {
                  }
                }
            ],
            "fee": TX_FEE,
            "inputsRaw":
                [],
            "dataInputsRaw":
                []
        }
    sign_tx(transaction_to_sign)


def clean_node(fee):
    unspent_boxes_url = f"https://api.ergoplatform.com/api/v1/boxes/unspent/byAddress/{node_address}?limit=50"
    response = requests.get(unspent_boxes_url)
    if response.status_code != 200:
        raise Exception(f"Failed to get unspent boxes: {response.text}")

    unspent_boxes = response.json()["items"]
    inputs_raw = []
    total_value = 0
    tokens_held = []
    for box in unspent_boxes:
        box_id = box['boxId']
        total_value += int(box["value"])
        box_info_url = f"{node_url}/utxo/withPool/byIdBinary/{box_id}"
        box_response = requests.get(box_info_url)
        if box["assets"]:
            for asset in box["assets"]:
                tokens_held.append(
                    {
                        "tokenId": asset["tokenId"],
                        "amount": asset["amount"]
                    }
                )
        if box_response.status_code != 200:
            raise Exception(f"Failed to get box info for {box_id}: {box_response.text}")

        inputs_raw.append(box_response.json()["bytes"])

    # Step 3: Construct the transaction object
    transaction = {
        "requests": [
            {
                "address": node_address,
                "value": total_value - fee,
                "assets": tokens_held,
                "registers": {"R4": "0400"}
            }
        ],
        "fee": fee,
        "inputsRaw": inputs_raw,
        "dataInputsRaw": []
    }
    return sign_tx(transaction)
