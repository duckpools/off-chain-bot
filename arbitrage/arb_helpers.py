import json
from math import floor

from client_consts import arbitrage_address, node_url
from consts import oracle_nft, bank_addr, MAX_BORROW_TOKENS
from helpers.explorer_calls import get_unspent_boxes_by_address, get_unspent_by_tokenId
from helpers.generic_calls import get_request
from helpers.platform_functions import get_dex_box


def get_tx_from_mempool(tx_id):
    response = json.loads(get_request(f"{node_url}/transactions/unconfirmed").text)
    for item in response:
        if item["id"] == tx_id:
            return item

def check_n2t_sell_token(amount, pool):
    dex_box = get_dex_box(pool["collateral_supported"]["erg"]["dex_nft"])
    dex_initial_val = int(dex_box["value"])
    dex_tokens = int(dex_box["assets"][2]["amount"])
    dex_fee = pool["collateral_supported"]["erg"]["dex_fee"]
    liquidation_value = ((dex_initial_val * amount * dex_fee) //
                         (dex_tokens * 1000 + amount * dex_fee))
    return liquidation_value, dex_box


def check_n2t_buy_token(amount, pool):
    dex_box = get_dex_box(pool["collateral_supported"]["erg"]["dex_nft"])
    dex_initial_val = dex_box["value"]
    dex_tokens = dex_box["assets"][2]["amount"]
    tokens_to_liquidate = amount
    dex_fee = pool["collateral_supported"]["erg"]["dex_fee"]
    liquidation_value = ((dex_tokens * tokens_to_liquidate * dex_fee) //
                              (dex_initial_val * 1000 +
                               (tokens_to_liquidate * dex_fee)))
    return liquidation_value, dex_box


def get_bank_stats():
    bank_box = get_bank_box()
    oracle_box = get_oracle_box()
    current_rate = int(int(oracle_box["additionalRegisters"]["R4"]["renderedValue"]) / 100)
    circ_x = int(bank_box["additionalRegisters"]["R4"]["renderedValue"])
    current_erg_val = int(bank_box["value"]) / current_rate
    final_x = current_erg_val / 4
    buyable = int(final_x - circ_x)
    return {
        "susd_buyable": buyable,
        "susd_buy_cost": (100 * current_rate) + floor((100 * current_rate) * 0.02),
        "susd_sellable": MAX_BORROW_TOKENS,
        "susd_sell_price": (100 * current_rate) - floor((100 * current_rate) * 0.02)
    }


def get_fund_box():
    return get_unspent_boxes_by_address(arbitrage_address)[0]


def get_oracle_box():
    return get_unspent_by_tokenId(oracle_nft)[0]


def get_bank_box():
    ps = get_unspent_boxes_by_address(bank_addr)
    for box in ps:
        try:
            if box["assets"][2]["tokenId"] == "7d672d1def471720ca5782fd6473e47e796d9ac0c138d9911346f118b2f6d9d9":
                return box
        except Exception:
            continue