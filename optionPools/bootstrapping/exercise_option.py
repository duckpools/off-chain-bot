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



def exercise_option_test(pool, boxId):
    optionBox = json.loads(requests.get(f"https://api.ergoplatform.com/api/v1/boxes/{boxId}").text)
    print(optionBox)
    optionSize = int(optionBox["value"]) - 1000000
    K = int(optionBox["additionalRegisters"]["R4"]["renderedValue"])
    payment = K * optionSize
    pool_box = op_latest_pool_info(pool, None)

    transaction_to_sign = \
            {
                "requests": [
                    {
                        "address": pool["repayment"],
                        "value": 2000000,
                        "assets": [
                            {
                                "tokenId": optionBox["assets"][0]["tokenId"],
                                "amount": optionBox["assets"][0]["amount"]
                            },
                            {
                                "tokenId": pool["asset_y"],
                                "amount": payment
                            }
                        ],
                        "registers": {
                            "R4": "0e20" + optionBox["boxId"]
                        }
                    }
                ],
                "fee": TX_FEE,
                "inputsRaw":
                    [box_id_to_binary(optionBox["boxId"]), "d3ad93f41f0008cd03dda8fe44b65ff96eb9dd442e6f10aca93f7351e96f2cbb1862c21a9055bc8b96aadc4d179a06d9e545a41fd51eeffc5e20d818073bf820c635e2a9d922269913e0de369db6843d3a9a734d0c5a0695bb79c6cde77bc1f6b8c9166b27f3a5a399e8f99d4cae15e0053c37831f0c56c6974b458a33ede6051a2ed9cdbf83687bd2f6fed21004bd6eeebf8db701d5ab247e7871ad6f6377663243bb404bcadfb99134510b5653d3004de693c60de996fd9da9029d08f3c34b871636cc5f1670131e56ff403dcc043465ef7c5ca0d9d865d455dfe095f3bef402aac4169b183c91b291234aace912d976f9d1ec6718ae9f182e1cb193c1b19484fdffb3abd8ba8c8118d34691ed46424f9b2f6911da7467ba9c0b14e2fafea161b6df30eb9ea12d5096feace204d42471052082974680472b4cb054833e12d400dbfe847eb2941e54ceaa2c34d7c6c3e8f3dbc1044d4bc42f51f0adfa263806608cc27913ca7621762d05723cc96b5c39281bb333e0bbe888b201a2a2f91405b6c46a2b159f26133930ccb7ac29abd0f7589419fa5c1dc4376a45f0d79fa580f5011368440201d3a950c9900bb9f4138223e5ee77f598f36a425ca665a886bb2c48bfcaebe4c828d7603ac4abbf8b2ad09cb2c30dd04237d3df4589368b4056299515bb1613a8188094ebdc0317ddb7ac382546298a4b075d0df4b0e4f5965b1cf89d9d8f64ba33e9a86c7559f2aaaea580f50103faf2cb329f2e90d6d23b58d91bbb6c046aa143261cc21f52fbe2824bfcbf04e201923e74c6272260623d64da6a227ed5016f4b1beded2a155775de47dd39ab6511d2919b87fef40187c4c600d731a002f98e07da6a2a78239179d3f3cec685493e6f7951fed8cdbeba9980f9b001df87864037f7a21a035c855ed1ef53929e65a0826853145f105f24b0598816598094ebdc0316546f8ceb99673ee351bda86563ca4d20afee46d52f1fd761c7c630a8b3192d055297efeab26c230b81f22fcd99836550d5bbbc740453cde190a0b0ba9467b1a20582d818c4d35a4bfca7bc925ba5fa49bbdb859da4225f0f675e5c3fa40ea36ed280ade204fb4bc066802562b66b170ecf9332e5b258897b49114b5436ee58f188bbdc1af080ade2044a6b0475bc6244ce18c5e1c99134252490e9d644a6b2034223ac3445aa85795b050bd05d8f87dfd1e834f01e11ef2c632a62dc525ac5c9d6edce988e0f4709bde70500b6f6b2c986dfdfdf5020d07a310ea8dd510ed467505d6587b1efd392311068ab03"],
                "dataInputsRaw":
                    []
            }
    print(transaction_to_sign)
    tx_id = sign_tx(transaction_to_sign)
    print(tx_id)