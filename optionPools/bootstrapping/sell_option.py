import json

from consts import MIN_BOX_VALUE, TX_FEE, minutes_in_a_year
from helpers.job_helpers import op_latest_pool_info
from helpers.node_calls import tree_to_address, box_id_to_binary, current_height
from helpers.platform_functions import get_CDF_box
from helpers.node_calls import sign_tx
from helpers.serializer import encode_long, encode_long_tuple, encode_int
import requests
from math import floor
from math import sqrt



import numpy as np
import scipy.stats as stats
def get_spot_price():
    return 10

def get_volatility():
    return 680000



def sell_option_test(pool, boxId):
    optionBox = json.loads(requests.get(f"https://api.ergoplatform.com/api/v1/boxes/{boxId}").text)
    print(optionBox)

    pool_box = op_latest_pool_info(pool, None)
    S = get_spot_price()
    P = 1000000
    σ = get_volatility()
    cdf_box = get_CDF_box()
    optionSize = int(optionBox["value"]) - 1000000
    print(cdf_box)
    r = int(pool_box["additionalRegisters"]["R4"]["renderedValue"])

    K = int(optionBox["additionalRegisters"]["R4"]["renderedValue"])
    t_block = int(optionBox["additionalRegisters"]["R5"]["renderedValue"])
    t_hint = current_height()
    t = floor((t_block - t_hint) * P / minutes_in_a_year)

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
    optionPremium = call_price * optionSize

    print(call_price)
    print(pool_box)
    transaction_to_sign = \
            {
                "requests": [
                    {
                        "address": pool["pool"],
                        "value": pool_box["value"] + optionSize,
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
                                "amount": pool_box["assets"][2]["amount"] - optionPremium
                            },
                            {
                                "tokenId": pool_box["assets"][3]["tokenId"],
                                "amount": pool_box["assets"][3]["amount"] + 1
                            },
                        ],
                        "registers": {
                            "R4": pool_box["additionalRegisters"]["R4"]["serializedValue"],
                            "R5": encode_long(y),
                            "R6": encode_long(sqrtT),
                            "R7": encode_int(nd1i),
                            "R8": encode_int(nd2i),
                            "R9": encode_long(t_hint)
                        }
                    }
                ],
                "fee": TX_FEE,
                "inputsRaw":
                    [box_id_to_binary(pool_box["boxId"]),box_id_to_binary(optionBox["boxId"]), "93cdbef71f0008cd03dda8fe44b65ff96eb9dd442e6f10aca93f7351e96f2cbb1862c21a9055bc8b96a0dc4d175297efeab26c230b81f22fcd99836550d5bbbc740453cde190a0b0ba9467b1a2051368440201d3a950c9900bb9f4138223e5ee77f598f36a425ca665a886bb2c4885f9cae4c8283a9a734d0c5a0695bb79c6cde77bc1f6b8c9166b27f3a5a399e8f99d4cae15e005923e74c6272260623d64da6a227ed5016f4b1beded2a155775de47dd39ab6511d2919b87fef40103faf2cb329f2e90d6d23b58d91bbb6c046aa143261cc21f52fbe2824bfcbf04e201d5ab247e7871ad6f6377663243bb404bcadfb99134510b5653d3004de693c60dea96fd9da902df87864037f7a21a035c855ed1ef53929e65a0826853145f105f24b0598816598094ebdc034a6b0475bc6244ce18c5e1c99134252490e9d644a6b2034223ac3445aa85795b05d7603ac4abbf8b2ad09cb2c30dd04237d3df4589368b4056299515bb1613a8188094ebdc0317ddb7ac382546298a4b075d0df4b0e4f5965b1cf89d9d8f64ba33e9a86c7559f2aaaea580f50116546f8ceb99673ee351bda86563ca4d20afee46d52f1fd761c7c630a8b3192d053c37831f0c56c6974b458a33ede6051a2ed9cdbf83687bd2f6fed21004bd6eeebf8db701aac4169b183c91b291234aace912d976f9d1ec6718ae9f182e1cb193c1b19484fdff9d8395e98a9118d42471052082974680472b4cb054833e12d400dbfe847eb2941e54ceaa2c34d7c6c3e8f3dbc104a2a2f91405b6c46a2b159f26133930ccb7ac29abd0f7589419fa5c1dc4376a4580a6a0a580f501d34691ed46424f9b2f6911da7467ba9c0b14e2fafea161b6df30eb9ea12d5096feace2044d4bc42f51f0adfa263806608cc27913ca7621762d05723cc96b5c39281bb333e0bbe888b2010bd05d8f87dfd1e834f01e11ef2c632a62dc525ac5c9d6edce988e0f4709bde70587c4c600d731a002f98e07da6a2a78239179d3f3cec685493e6f7951fed8cdbeba9980f9b0019d08f3c34b871636cc5f1670131e56ff403dcc043465ef7c5ca0d9d865d455dfe095f3bef40282d818c4d35a4bfca7bc925ba5fa49bbdb859da4225f0f675e5c3fa40ea36ed280ade204fb4bc066802562b66b170ecf9332e5b258897b49114b5436ee58f188bbdc1af080ade2049a06d9e545a41fd51eeffc5e20d818073bf820c635e2a9d922269913e0de369db6843d001f8a582053ff414582800779a36c315a7774568254bcdfaa7723317f2def8f1803"],
                "dataInputsRaw":
                    [box_id_to_binary(cdf_box["boxId"])]
            }
    print(transaction_to_sign)
    tx_id = sign_tx(transaction_to_sign)
    print(tx_id)