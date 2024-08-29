from math import ceil, floor

from arbitrage.arb_helpers import check_n2t_buy_token, get_fund_box, check_n2t_sell_token, get_bank_box, get_oracle_box
from client_consts import arbitrage_address
from consts import MIN_BOX_VALUE, fee_address, DOUBLE_SPENDING_ATTEMPT
from helpers.node_calls import box_id_to_binary, sign_tx
from helpers.serializer import encode_long


def n2t_buy_token(amountPaid, pool, fee, max_fee, fund_box=None, low_earnings=False):
    pure_receipt, dex_box = check_n2t_buy_token(amountPaid, pool)
    rs_ada_received = ceil(pure_receipt * 0.9986)
    if low_earnings:
        rs_ada_received = pure_receipt
    rs_ada_received_fee = pure_receipt - rs_ada_received
    dex_tokens = int(dex_box["assets"][2]["amount"])
    if not fund_box:
        fund_box = get_fund_box()
    transaction_to_sign = {
        "requests": [
            {
                "address": dex_box["address"],
                "value": int(dex_box["value"]) + amountPaid,
                "assets": [
                    {
                        "tokenId": dex_box["assets"][0]["tokenId"],
                        "amount": str(dex_box["assets"][0]["amount"])
                    },
                    {
                        "tokenId": dex_box["assets"][1]["tokenId"],
                        "amount": str(dex_box["assets"][1]["amount"])
                    },
                    {
                        "tokenId": dex_box["assets"][2]["tokenId"],
                        "amount": str(dex_tokens - pure_receipt)
                    }
                ],
                "registers": {
                    "R4": dex_box["additionalRegisters"]["R4"]["serializedValue"]
                }
            },
            {
                "address": arbitrage_address,
                "value": int(fund_box["value"]) - amountPaid - fee - MIN_BOX_VALUE,
                "assets": [
                    {
                        "tokenId": fund_box["assets"][0]["tokenId"],
                        "amount": int(fund_box["assets"][0]["amount"]) + rs_ada_received
                    }
                ],
                "registers": {
                }
            }
        ],
        "fee": fee,
        "inputsRaw": [box_id_to_binary(dex_box["boxId"]), box_id_to_binary(fund_box["boxId"])],
        "dataInputsRaw": []
    }
    if rs_ada_received_fee > 0:
        transaction_to_sign["requests"].append(
        {
            "address": fee_address,
            "value": MIN_BOX_VALUE,
            "assets": [
                {
                    "tokenId": fund_box["assets"][0]["tokenId"],
                    "amount": rs_ada_received_fee
                }
            ],
            "registers": {
            }
        })
    else:
        transaction_to_sign["fee"] += MIN_BOX_VALUE
    print('tx')
    print(transaction_to_sign)
    tx_id = sign_tx(transaction_to_sign)
    print(tx_id)
    if tx_id == DOUBLE_SPENDING_ATTEMPT:
        n2t_buy_token(amountPaid, pool, fee + 1000000, max_fee, fund_box)
    return tx_id, rs_ada_received


def n2t_sell_token(amountSelling, pool, fee, fund_box=None):
    pure_erg_received, dex_box = check_n2t_sell_token(amountSelling, pool)
    erg_received = ceil(pure_erg_received * 0.9986)
    erg_received_fee = pure_erg_received - erg_received
    dex_tokens = int(dex_box["assets"][2]["amount"])
    if not fund_box:
        fund_box = get_fund_box()
    transaction_to_sign = {
        "requests": [
            {
                "address": dex_box["address"],
                "value": int(dex_box["value"]) - pure_erg_received,
                "assets": [
                    {
                        "tokenId": dex_box["assets"][0]["tokenId"],
                        "amount": str(dex_box["assets"][0]["amount"])
                    },
                    {
                        "tokenId": dex_box["assets"][1]["tokenId"],
                        "amount": str(dex_box["assets"][1]["amount"])
                    },
                    {
                        "tokenId": dex_box["assets"][2]["tokenId"],
                        "amount": str(dex_tokens + amountSelling)
                    }
                ],
                "registers": {
                    "R4": dex_box["additionalRegisters"]["R4"]["serializedValue"]
                }
            },
            {
                "address": arbitrage_address,
                "value": int(fund_box["value"]) + erg_received - fee,
                "assets": [
                    {
                        "tokenId": fund_box["assets"][0]["tokenId"],
                        "amount": int(fund_box["assets"][0]["amount"]) - amountSelling
                    }
                ],
                "registers": {
                }
            }
        ],
        "fee": fee,
        "inputsRaw": [box_id_to_binary(dex_box["boxId"]), box_id_to_binary(fund_box["boxId"])],
        "dataInputsRaw": []
    }
    if erg_received_fee > MIN_BOX_VALUE:
        transaction_to_sign["requests"].append(
        {
            "address": fee_address,
            "value": erg_received_fee,
            "assets": [
            ],
            "registers": {
            }
        })
    else:
        transaction_to_sign["fee"] += erg_received_fee
    print('tx')
    print(transaction_to_sign)
    tx_id = sign_tx(transaction_to_sign)
    print(tx_id)
    return tx_id, erg_received - fee


def bank_buy_token(amount_to_buy, fee):
    bank_box = get_bank_box()
    oracle_box = get_oracle_box()
    current_rate = int(int(oracle_box["additionalRegisters"]["R4"]["renderedValue"]) / 100)
    circ_x = int(bank_box["additionalRegisters"]["R4"]["renderedValue"])
    current_erg_val = int(bank_box["value"]) / current_rate
    final_x = current_erg_val / 4
    buyable = int(final_x - circ_x)
    amount_to_buy = min(buyable, amount_to_buy)
    erg_requried = (amount_to_buy * current_rate) + floor((amount_to_buy * current_rate) * 0.02)

    fund_box = get_fund_box()
    transaction_to_sign = {
        "requests": [
            {
                "address": bank_box["address"],
                "value": str(int(bank_box["value"]) + erg_requried),
                "assets": [
                    {
                        "tokenId": bank_box["assets"][0]["tokenId"],
                        "amount": str(bank_box["assets"][0]["amount"] - amount_to_buy)
                    },
                    {
                        "tokenId": bank_box["assets"][1]["tokenId"],
                        "amount": str(bank_box["assets"][1]["amount"])
                    },
                    {
                        "tokenId": bank_box["assets"][2]["tokenId"],
                        "amount": 1
                    }
                ],
                "registers": {
                    "R4": encode_long(circ_x + amount_to_buy),
                    "R5": bank_box["additionalRegisters"]["R5"]["serializedValue"]
                }
            },
            {
                "address": fund_box["address"],
                "value": int(fund_box["value"]) - erg_requried - fee,
                "assets": [
                    {
                        "tokenId": fund_box["assets"][0]["tokenId"],
                        "amount": int(fund_box["assets"][0]["tokenId"]) + amount_to_buy
                    }
                ],
                "registers": {
                    "R4": encode_long(amount_to_buy),
                    "R5": encode_long(erg_requried)
                }
            }
        ],
        "fee": fee,
        "inputsRaw": [box_id_to_binary(bank_box["boxId"]), box_id_to_binary(fund_box["boxId"])],
        "dataInputsRaw": [box_id_to_binary(oracle_box["boxId"])]
    }
    if floor(erg_requried * 0.0018) > MIN_BOX_VALUE:
        transaction_to_sign["requests"].append(
        {
            "address": fee_address,
            "value": floor(erg_requried * 0.0018),
            "assets": [
            ],
            "registers": {
            }
        })
    print('tx')
    print(transaction_to_sign)
    tx_id = sign_tx(transaction_to_sign)
    return tx_id

def bank_sell_token(amount_to_buy, fee, max_fee, fund_box=None, low_earnings=False):
    bank_box = get_bank_box()
    oracle_box = get_oracle_box()
    current_rate = int(int(oracle_box["additionalRegisters"]["R4"]["renderedValue"]) / 100)
    circ_x = int(bank_box["additionalRegisters"]["R4"]["renderedValue"])
    #TODO: Add Capped Sell Logic
    pure_erg_received = (amount_to_buy * current_rate) - floor((amount_to_buy * current_rate) * 0.02)
    erg_received = ceil(pure_erg_received * 0.9986)
    if low_earnings:
        erg_received = pure_erg_received
    erg_received_fee = pure_erg_received - erg_received
    if not fund_box:
        fund_box = get_fund_box()
    transaction_to_sign = {
        "requests": [
            {
                "address": bank_box["address"],
                "value": str(int(bank_box["value"]) - pure_erg_received),
                "assets": [
                    {
                        "tokenId": bank_box["assets"][0]["tokenId"],
                        "amount": str(bank_box["assets"][0]["amount"] + amount_to_buy)
                    },
                    {
                        "tokenId": bank_box["assets"][1]["tokenId"],
                        "amount": str(bank_box["assets"][1]["amount"])
                    },
                    {
                        "tokenId": bank_box["assets"][2]["tokenId"],
                        "amount": 1
                    }
                ],
                "registers": {
                    "R4": encode_long(circ_x - amount_to_buy),
                    "R5": bank_box["additionalRegisters"]["R5"]["serializedValue"]
                }
            },
            {
                "address": arbitrage_address,
                "value": int(fund_box["value"]) + erg_received - fee,
                "assets": [
                    {
                        "tokenId": fund_box["assets"][0]["tokenId"],
                        "amount": int(fund_box["assets"][0]["amount"]) - amount_to_buy
                    }
                ],
                "registers": {
                    "R4": encode_long(-amount_to_buy),
                    "R5": encode_long(-pure_erg_received)
                }
            }
        ],
        "fee": fee,
        "inputsRaw": [box_id_to_binary(bank_box["boxId"]), box_id_to_binary(fund_box["boxId"])],
        "dataInputsRaw": [box_id_to_binary(oracle_box["boxId"])]
    }
    if erg_received_fee > MIN_BOX_VALUE:
        transaction_to_sign["requests"].append(
        {
            "address": fee_address,
            "value": erg_received_fee,
            "assets": [
            ],
            "registers": {
            }
        })
    else:
        transaction_to_sign["fee"] += erg_received_fee
    print('tx')
    print(transaction_to_sign)
    tx_id = sign_tx(transaction_to_sign)
    if tx_id == DOUBLE_SPENDING_ATTEMPT:
        bank_sell_token(amount_to_buy, fee + 1000000, max_fee, fund_box)
    print(tx_id)
    return tx_id