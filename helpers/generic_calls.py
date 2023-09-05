import time

import requests

from consts import REQUEST_DELAY
from client_consts import headers
from logger import set_logger

logger = set_logger(__name__)


def get_request(url, headers=headers, max_retries=5, delay=REQUEST_DELAY):
    """
    Perform an HTTP GET request with retries upon receiving a non-200 status code.

    :param url: The URL to send the GET request to.
    :param headers: The headers to include in the GET request.
    :param max_retries: The maximum number of retries before giving up.
    :return: The response object, or 404 if the final status code is 404.
    """
    for attempt in range(max_retries):
        response = requests.get(url, headers)
        if response.status_code == 200:
            return response
        if response.status_code == 404:
            return 404
        logger.warning(f"Attempt {attempt + 1}: Failed to get a valid response for URL: {url}")
        time.sleep(delay)
    logger.error(f"Failed to get a valid response after {max_retries} retries for URL: {url}")
    return None
