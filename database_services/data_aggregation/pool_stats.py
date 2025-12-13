import math
from math import floor

from consts import BORROW_TOKEN_DENOMINATION, INTEREST_DENOMINATION
from helpers.platform_functions import get_interest_box
from helpers.serializer import extract_number


# ========== total_borrowed - Already has V1/V2 logic ==========
def total_borrowed_v1(pool, pool_box):
    """V1 implementation of total_borrowed - original logic."""
    circulatingBorrowTokens = pool["BorrowTokenSupply"] - pool_box["assets"][2]["amount"]
    return circulatingBorrowTokens


def total_borrowed_v2(pool, pool_box):
    """V2 implementation of total_borrowed - uses interest box."""
    circulatingBorrowTokens = pool["BorrowTokenSupply"] - pool_box["assets"][2]["amount"]
    interest_box = get_interest_box(pool["interest"], pool["INTEREST_NFT"])
    borrowTokenValue = extract_number(interest_box["additionalRegisters"]["R5"]["renderedValue"])
    return floor(circulatingBorrowTokens * borrowTokenValue / BORROW_TOKEN_DENOMINATION)


def total_borrowed(pool, pool_box):
    """Dispatcher for total_borrowed based on pool version."""
    if pool["version"] == 1:
        return total_borrowed_v1(pool, pool_box)
    elif pool["version"] == 2:
        return total_borrowed_v2(pool, pool_box)
    else:
        raise ValueError(f"Unknown pool version: {pool['version']}")


# ========== pool_utilization ==========
def pool_utilization_v1(pool, pool_box):
    """V1 implementation of pool_utilization - original logic."""
    borrowed = total_borrowed(pool, pool_box)
    if pool["is_Erg"]:
        freeValue = pool_box["value"]
    else:
        freeValue = pool_box["assets"][3]["amount"]
    return borrowed / (freeValue + borrowed)


def pool_utilization_v2(pool, pool_box):
    """V2 implementation of pool_utilization - token-only pools."""
    borrowed = total_borrowed(pool, pool_box)
    # V2 pools are token-only, always use assets[3] for pool assets
    freeValue = pool_box["assets"][3]["amount"]
    return borrowed / (freeValue + borrowed)


def pool_utilization(pool, pool_box):
    """Dispatcher for pool_utilization based on pool version."""
    if pool["version"] == 1:
        return pool_utilization_v1(pool, pool_box)
    elif pool["version"] == 2:
        return pool_utilization_v2(pool, pool_box)
    else:
        raise ValueError(f"Unknown pool version: {pool['version']}")


# ========== lend_apy ==========
def lend_apy_v1(pool, pool_box):
    """V1 implementation of lend_apy - original logic."""
    borrow_rate = borrow_apy(pool, pool_box)
    utilization = pool_utilization(pool, pool_box)
    return borrow_rate * utilization


def lend_apy_v2(pool, pool_box):
    """V2 implementation of lend_apy - same formula as V1."""
    borrow_rate = borrow_apy(pool, pool_box)  # Dispatcher will call v2
    utilization = pool_utilization(pool, pool_box)  # Dispatcher will call v2
    return borrow_rate * utilization


def lend_apy(pool, pool_box):
    """Dispatcher for lend_apy based on pool version."""
    if pool["version"] == 1:
        return lend_apy_v1(pool, pool_box)
    elif pool["version"] == 2:
        return lend_apy_v2(pool, pool_box)
    else:
        raise ValueError(f"Unknown pool version: {pool['version']}")


# ========== borrow_apy ==========
def borrow_apy_v1(pool, pool_box):
    """V1 implementation of borrow_apy - original logic."""
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


def borrow_apy_v2(pool, pool_box):
    """V2 implementation of borrow_apy - same polynomial formula as V1."""
    coefficients = pool["interest_coefficients"]
    util = pool_utilization(pool, pool_box)  # Dispatcher will call v2
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


def borrow_apy(pool, pool_box):
    """Dispatcher for borrow_apy based on pool version."""
    if pool["version"] == 1:
        return borrow_apy_v1(pool, pool_box)
    elif pool["version"] == 2:
        return borrow_apy_v2(pool, pool_box)
    else:
        raise ValueError(f"Unknown pool version: {pool['version']}")