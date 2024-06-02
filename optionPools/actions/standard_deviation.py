import json

from consts import TX_FEE
from helpers.node_calls import box_id_to_binary, sign_tx, current_height
from helpers.platform_functions import get_std_box, get_dex_box
from helpers.serializer import encode_long_tuple, encode_int, encode_long
from math import floor, sqrt, ceil

def update_std():
    box = get_std_box()
    box_curr_height = int(box["additionalRegisters"]["R7"]["renderedValue"])
    curr_height = current_height()
    if box_curr_height < curr_height:
        dex_box = get_dex_box("9916d75132593c8b07fe18bd8d583bda1652eed7565cf41a4738ddd90fc992ec")
        current_index = int(box["additionalRegisters"]["R5"]["renderedValue"])
        new_entry = int(100000000000000 * int(dex_box["assets"][2]["amount"])/ int(dex_box["value"]))

        entries = json.loads(box["additionalRegisters"]["R4"]["renderedValue"])
        previous_entry = int(box["additionalRegisters"]["R8"]["renderedValue"])
        P = 1000000
        x = floor(new_entry * P / previous_entry) - P
        lnX= (
                x -
                int((x * x) / (2 * P)) +
                int((x * x * x) / (3 * P * P)) -
                int((x * x * x * x) / (4 * P * P * P)) +
                int((x * x * x * x * x) / (5 * P * P * P * P)) -
                int((x * x * x * x * x * x) / (6 * P * P * P * P * P))
        )
        entries[current_index] = lnX
        print(lnX)
        sum_of_entries = 0
        for entry in entries:
            sum_of_entries += int(entry)
        mean = floor(sum_of_entries / 100)
        squared_diff_sum = sum((price - mean) ** 2 for price in entries)
        new_volatilty = int(sqrt(floor(squared_diff_sum / 99)))
        print(new_volatilty)

        transaction_to_sign = \
            {
                "requests": [
                    {
                        "address": box["address"],
                        "value": box["value"] - TX_FEE,
                        "assets": [
                            {
                            "tokenId": box["assets"][0]["tokenId"],
                            "amount": box["assets"][0]["amount"]
                            }
                        ],
                        "registers": {
                            "R4": encode_long_tuple(entries),
                            "R5": encode_int((current_index + 1) % 100),
                            "R6": encode_long(new_volatilty),
                            "R7": encode_long(box_curr_height + 292),
                            "R8": encode_long(new_entry),
                            "R9": encode_long(new_volatilty * 30)
                        }
                    }
                ],
                "fee": TX_FEE,
                "inputsRaw":
                    [box_id_to_binary(box["boxId"])],
                "dataInputsRaw":
                    [box_id_to_binary(dex_box["boxId"])]
            }
        tx_id = sign_tx(transaction_to_sign)
        print(tx_id)

