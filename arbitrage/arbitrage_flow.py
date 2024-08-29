from arbitrage.arb_helpers import get_bank_stats, check_n2t_sell_token, check_n2t_buy_token, get_tx_from_mempool
from arbitrage.transaction_builders import n2t_buy_token, bank_sell_token
from consts import pools
from helpers.platform_functions import get_dex_box


def arb_flow():
    bank_stats = get_bank_stats()
    susd_sell_price = bank_stats["susd_sell_price"]
    receives, _ = (check_n2t_buy_token(susd_sell_price * 40, pools[1]))
    receives2, _ = (check_n2t_buy_token(susd_sell_price * 200, pools[1]))
    print(receives)
    print(receives2)
    if receives2 > int(205 * 100):
        tx_id, tokens_received = n2t_buy_token(susd_sell_price * 205, pools[1], int(0.1 * 1000000000))
        box = get_tx_from_mempool(tx_id)["outputs"][1]
        print(bank_sell_token(tokens_received, int(0.1 * 1000000000), fund_box=box))
    elif receives > int(40.6 * 100):
        tx_id, tokens_received = n2t_buy_token(susd_sell_price * 80, pools[1], int(0.025 * 1000000000))
        box = get_tx_from_mempool(tx_id)["outputs"][1]
        print(bank_sell_token(tokens_received, int(0.025 * 1000000000), fund_box=box))
    elif receives > int(40.3 * 100):
        start_fee = int(0.01 * 1000000000)
        max_fee = int(0.1 * 1000000000)
        tx_id, tokens_received = n2t_buy_token(susd_sell_price * 40, pools[1], start_fee, max_fee, low_earnings=True)
        box = get_tx_from_mempool(tx_id)["outputs"][1]
        print(bank_sell_token(tokens_received, start_fee, max_fee, fund_box=box, low_earnings=True))
    elif receives > int(40.12 * 100):
        start_fee = int(0.007 * 1000000000)
        max_fee = int(0.04 * 1000000000)
        tx_id, tokens_received = n2t_buy_token(susd_sell_price * 40, pools[1], start_fee, max_fee, low_earnings=True)
        box = get_tx_from_mempool(tx_id)["outputs"][1]
        print(bank_sell_token(tokens_received, start_fee, max_fee, fund_box=box, low_earnings=True))