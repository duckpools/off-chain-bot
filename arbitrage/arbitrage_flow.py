from arbitrage.arb_helpers import get_bank_stats, check_n2t_sell_token, check_n2t_buy_token, get_tx_from_mempool
from arbitrage.transaction_builders import n2t_buy_token, bank_sell_token
from consts import pools
from helpers.platform_functions import get_dex_box
import time
import concurrent.futures
from queue import Queue
import requests

# Maximum number of concurrent threads
MAX_WORKERS = 3

# Thread pool executor
executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)

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

def handle_sell_transaction(tokens_received, fee, max_fee, fund_box, low_earnings):
    sell_tx_id = bank_sell_token(tokens_received, fee, max_fee, fund_box=fund_box, low_earnings=low_earnings)
    if not wait_for_confirmation(sell_tx_id):
        print(f"Transaction {sell_tx_id} not confirmed after 15 minutes. Resubmitting...")
        sell_tx_id = bank_sell_token(tokens_received, fee, max_fee, fund_box=fund_box, low_earnings=low_earnings)
    print(f"Sell transaction {sell_tx_id} confirmed or resubmitted.")
    pending_sells.get()  # Remove this transaction from the queue

def execute_trade(susd_sell_price, amount, fee, max_fee=None, low_earnings=False):
    tx_id, tokens_received = n2t_buy_token(susd_sell_price * amount, pools[1], fee, max_fee, low_earnings=low_earnings)
    box = get_tx_from_mempool(tx_id)["outputs"][1]
    pending_sells.put(1)
    executor.submit(handle_sell_transaction, tokens_received, fee, max_fee, box, low_earnings)
    return tx_id

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

def cleanup():
    executor.shutdown(wait=True)