from arbitrage.arb_helpers import get_bank_stats, check_n2t_sell_token, check_n2t_buy_token, get_tx_from_mempool
from arbitrage.transaction_builders import n2t_buy_token, bank_sell_token
from consts import pools
from helpers.platform_functions import get_dex_box
import time
import concurrent.futures
from queue import Queue
import requests


# Queue to keep track of pending sell transactions
pending_sells = Queue()

def check_tx_confirmed(tx_id):
    url = f"https://api.ergoplatform.com/api/v1/transactions/{tx_id}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return True
        elif response.status_code == 404:
            return False
        else:
            print(f"Unexpected status code: {response.status_code}")
            return False
    except requests.RequestException as e:
        print(f"Error checking transaction status: {e}")
        return False

def wait_for_confirmation(tx_id, timeout=900, retry_interval=30):
    start_time = time.time()
    while time.time() - start_time < timeout:
        if check_tx_confirmed(tx_id):
            return True
        time.sleep(retry_interval)
    return False

def attempt_sell(tokens_received, fee, max_fee, fund_box, low_earnings):
    sell_tx_id = bank_sell_token(tokens_received, fee, max_fee, fund_box=fund_box, low_earnings=low_earnings)
    print(f"Attempting sell transaction {sell_tx_id}.")
    return sell_tx_id

def handle_sell_transaction(sell_tx_id, tokens_received, fee, max_fee, fund_box, low_earnings, buy_tx_id):
    # Attempt the sell transaction and ensure it confirms if buy is confirmed
    while True:
        if check_tx_confirmed(buy_tx_id):  # Check if the buy transaction is confirmed
            if not check_tx_confirmed(sell_tx_id):  # If sell is not confirmed, retry
                sell_tx_id = attempt_sell(tokens_received, fee, max_fee, fund_box, low_earnings)
            else:
                print(f"Sell transaction {sell_tx_id} confirmed.")
                pending_sells.get()  # Remove this transaction from the queue
                break
        else:
            print(f"Waiting for buy transaction {buy_tx_id} to confirm before ensuring sell.")
        time.sleep(30)


def execute_trade(susd_sell_price, amount, fee, max_fee=None, low_earnings=False, buy_timeout=900, max_buy_retries=5):
    buy_tx_id = None
    tokens_received = None
    retries = 0
    buy_success = False

    while retries < max_buy_retries and not buy_success:
        buy_tx_id, tokens_received = n2t_buy_token(susd_sell_price * amount, pools[1], fee, max_fee,
                                                   low_earnings=low_earnings)
        print(f"Attempting buy transaction {buy_tx_id}, attempt {retries + 1}.")

        # Retrieve the unconfirmed output box from the mempool
        buy_tx_data = get_tx_from_mempool(buy_tx_id)
        fund_box = None
        if buy_tx_data:
            fund_box = buy_tx_data["outputs"][1]  # Use the unconfirmed output box
        else:
            fund_box = None
            print(f"Could not retrieve the unconfirmed output box for buy transaction {buy_tx_id}.")
        sell_tx_id = attempt_sell(tokens_received, fee, max_fee, fund_box, low_earnings=low_earnings)  # Immediate sell attempt
        # Check if buy confirms within timeout
        if wait_for_confirmation(buy_tx_id, timeout=buy_timeout):
            buy_success = True
            print(f"Buy transaction {buy_tx_id} confirmed.")
        else:
            retries += 1
            print(f"Buy transaction {buy_tx_id} failed to confirm. Retrying ({retries}/{max_buy_retries})...")

        # Proceed with ensuring sell confirmation, whether buy is successful or not
        box = get_tx_from_mempool(buy_tx_id)["outputs"][1] if buy_success else None
        pending_sells.put(1)
        handle_sell_transaction(sell_tx_id, tokens_received, fee, max_fee, box, low_earnings, buy_tx_id)

    return buy_tx_id


def arb_flow():
    bank_stats = get_bank_stats()
    susd_sell_price = bank_stats["susd_sell_price"]

    receives, _ = check_n2t_buy_token(susd_sell_price * 40, pools[1])
    receives2, _ = check_n2t_buy_token(susd_sell_price * 200, pools[1])

    print(receives)
    print(receives2)
    if receives2 > int(205 * 100):
        print(execute_trade(susd_sell_price, 205, int(0.1 * 1e9)))
    elif receives > int(40.6 * 100):
        print(execute_trade(susd_sell_price, 80, int(0.025 * 1e9)))
    elif receives > int(40.3 * 100):
        print(execute_trade(susd_sell_price, 40, int(0.01 * 1e9), int(0.1 * 1e9), True))
    elif receives > int(40.05 * 100):
        print(execute_trade(susd_sell_price, 40, int(0.007 * 1e9), int(0.04 * 1e9), True))

    while not pending_sells.empty():
        time.sleep(1)
