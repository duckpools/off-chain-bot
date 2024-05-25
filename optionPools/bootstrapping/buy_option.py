from consts import MIN_BOX_VALUE, TX_FEE
from helpers.job_helpers import op_latest_pool_info
from helpers.node_calls import tree_to_address, box_id_to_binary
from helpers.platform_functions import get_CDF_box
from helpers.node_calls import sign_tx
from helpers.serializer import encode_long, encode_long_tuple, encode_int

from math import floor
from math import sqrt



import numpy as np
import scipy.stats as stats
def get_spot_price():
    return 10

def get_volatility():
    return 10


def buy_option_test(pool, optionSize):
    pool_box = op_latest_pool_info(pool, None)
    S = get_spot_price()
    P = 1000000
    σ = get_volatility()
    cdf_box = get_CDF_box()
    print(cdf_box)
    r = 5

    K = 10
    t = int(15 * P)

    i = S / K
    y = floor(sqrt(sqrt(sqrt(i))) * P)
    x = y - P


    lnSK = (
                   x -
                   floor((x * x) / (2 * P)) +
                   floor((x * x * x) / (3 * P * P)) -
                   floor((x * x * x * x) / (4 * P * P * P)) +
                   floor((x * x * x * x * x) / (5 * P * P * P * P)) -
                   floor((x * x * x * x * x * x) / (6 * P * P * P * P * P))
           ) * 8

    sqrtT = floor(sqrt(t / P) * P)
    d11 = floor((P * P * lnSK) / (σ * sqrtT))
    d12 = floor((t * P * r) / (σ * sqrtT))
    d13 = floor((σ * t) / (2 * sqrtT))
    d1 = d11 + d12 + d13
    d2 = d1 - floor((σ * sqrtT) / P)
    print(d1)
    print(d2)

    j = floor(r * t / P)
    ans = (
            P -
            j +
            floor((j * j) / (2 * P)) -
            floor((j * j * j) / (6 * P * P)) +
            floor((j * j * j * j) / (24 * P * P * P))
    )

    def calculate_cdf(d_in, x_values, cdf_values):
        i = 0
        d = max(d_in, -d_in)
        while i < len(x_values):
            if x_values[i] > d:
                if d_in < 0:
                    return (P - cdf_values[i - 1], i - 1)
                return (cdf_values[i - 1], i - 1)
            i += 1
        if d_in < 0:
            (P - cdf_values[i - 1], i - 1)
        return (cdf_values[i - 1], i - 1)

    # Generate the values from 0 to 3.1 with increments of 0.005
    x_values = np.arange(0, 3.105, 0.02)
    cdf_values = stats.norm.cdf(x_values).tolist()
    cdf_values = [floor(val * P) for val in cdf_values]
    x_vals = x_values.tolist()
    x_vals = [floor(val * P) for val in x_vals]

    nd1, nd1i = calculate_cdf(d1, x_vals, cdf_values)
    nd2, nd2i = calculate_cdf(d2, x_vals, cdf_values)
    call_price = floor((nd1 * S)) - floor((nd2 * K * ans) / (P))
    optionPremium = call_price * 2

    print(call_price)
    print(pool_box)
    transaction_to_sign = \
            {
                "requests": [
                    {
                        "address": pool["pool"],
                        "value": pool_box["value"] - optionSize,
                        "assets": [
                            {
                                "tokenId": pool_box["assets"][0]["tokenId"],
                                "amount": pool_box["assets"][0]["amount"]
                            },
                            {
                                "tokenId": pool_box["assets"][1]["tokenId"],
                                "amount": pool_box["assets"][1]["amount"]
                            },
                            {
                                "tokenId": pool_box["assets"][2]["tokenId"],
                                "amount": pool_box["assets"][2]["amount"] + optionPremium + 100
                            }
                        ],
                        "registers": {
                            "R4": pool_box["additionalRegisters"]["R4"]["serializedValue"],
                            "R5": encode_long(y),
                            "R6": encode_long(sqrtT),
                            "R7": encode_int(nd1i),
                            "R8": encode_int(nd2i)
                        }
                    },
                    {
                        "address": pool["option_address"],
                        "value": MIN_BOX_VALUE + optionSize,
                        "assets": [
                        ],
                        "registers": {
                            "R4": encode_long(K),
                            "R5": encode_long(t),
                        }
                    }
                ],
                "fee": TX_FEE,
                "inputsRaw":
                    [box_id_to_binary(pool_box["boxId"]), ""],
                "dataInputsRaw":
                    [box_id_to_binary(cdf_box["boxId"])]
            }
    print(transaction_to_sign)
    tx_id = sign_tx(transaction_to_sign)
    print(tx_id)