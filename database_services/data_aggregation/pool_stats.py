import math
from math import floor

from consts import BORROW_TOKEN_DENOMINATION, INTEREST_DENOMINATION
from helpers.platform_functions import get_interest_box


def total_borrowed(pool, pool_box):
    circulatingBorrowTokens = pool["BorrowTokenSupply"] - pool_box["assets"][2]["amount"]
    if pool["version"] == 1:
        return circulatingBorrowTokens
    if pool["version"] == 2:
        interest_box = get_interest_box(pool["interest"], pool["INTEREST_NFT"])
        borrowTokenValue = int(interest_box["additionalRegisters"]["R5"]["renderedValue"])
        return floor(circulatingBorrowTokens * borrowTokenValue / BORROW_TOKEN_DENOMINATION)


def pool_utilization(pool, pool_box):
    borrowed = total_borrowed(pool, pool_box)
    if pool["is_Erg"]:
        freeValue = pool_box["value"]
    else:
        freeValue = pool_box["assets"][3]["amount"]
    return borrowed / (freeValue + borrowed)


def lend_apy(pool, pool_box):
    borrow_rate = borrow_apy(pool, pool_box)
    utilization = pool_utilization(pool, pool_box)
    return borrow_rate * utilization


def borrow_apy(pool, pool_box):
    coefficients = pool["interest_coefficients"]
    util = pool_utilization(pool, pool_box)
    coefficient_denom = 100000000
    a = coefficients[0]
    b = coefficients[1]
    c = coefficients[2]
    d = coefficients[3]
    e = coefficients[4]
    f = coefficients[5]
    M = INTEREST_DENOMINATION
    D = coefficient_denom
    x = util * M

    current_rate = math.floor(
        M +
        (a +
         math.floor(math.floor(b * x) / D) +
         math.floor(math.floor(math.floor(math.floor(c * x) / D) * x) / M) +
         math.floor(
             math.floor(
                 math.floor(math.floor(math.floor(math.floor(d * x) / D) * x) / M) *
                 x
             ) / M
         ) +
         math.floor(
             math.floor(
                 math.floor(
                     math.floor(
                         math.floor(
                             math.floor(math.floor(math.floor(e * x) / D) * x) / M
                         ) * x
                     ) / M
                 ) * x
             ) / M
         ) +
         math.floor(
             math.floor(
                 math.floor(
                     math.floor(
                         math.floor(
                             math.floor(
                                 math.floor(
                                     math.floor(math.floor(math.floor(f * x) / D) * x) / M
                                 ) * x
                             ) / M
                         ) * x
                     ) / M
                 ) * x
             ) / M
         ))
    )
    return 100 * (current_rate / M) ** 2190 - 100