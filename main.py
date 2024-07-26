from time import sleep

from bootstrapping.pool_creation import create_pool, allAddressesWithBoxes, bootstrap_logic_box
from consts import BorrowTokenDenomination
from contracts.quacks import generate_repayment_script, generate_collateral_script, generate_pool_script, \
    generate_interest_script, generate_logic_script
from helpers.platform_functions import update_pools_in_file
from helpers.serializer import bytesLike, blake2b256, encode_bigint, encode_long, hex_to_base58
from token_pools.t_borrow_proxy_susd import t_borrow_proxy_job
from current_pools import current_pools
from client_consts import node_address
from erg_pool.e_borrow_proxy import e_borrow_proxy_job
from erg_pool.e_interest_rate import e_update_interest_rate
from erg_pool.e_lend_proxy import e_lend_proxy_job
from erg_pool.e_liquidation import e_liquidation_job
from erg_pool.e_partial_repay_proxy import e_partial_repay_proxy_job
from helpers.node_calls import unlock_wallet, current_height, generate_dummy_script, address_to_tree, mint_token, \
    compile_script
from token_pools.t_interest_rate_susd import t_update_interest_rate
from token_pools.t_lend_proxy_sUsd import t_lend_proxy_job
from token_pools.t_liquidation_susd import t_liquidation_job
from logger import set_logger
from token_pools.t_partial_repay_proxy_susd import t_partial_repay_proxy_job
from erg_pool.e_repay_proxy import e_repay_proxy_job
from token_pools.t_repay_proxy_susd import t_repay_proxy_job
from erg_pool.e_repay_to_pool import e_repay_to_pool_job
from token_pools.t_repay_to_pool_susd import t_repay_to_pool_job
from erg_pool.e_withdraw_proxy import e_withdraw_proxy_job
from token_pools.t_withdraw_proxy_sigusd import t_withdraw_proxy_job


try:
    from proposed_pools import pools
except ImportError:
    pass
"""childBoxNft = hex_to_base58(('920096d252fd80df91c65c7d62db9b876265469c29b7cc778157099776f81b13'))
parameterBoxNft = hex_to_base58(('2a26e43b9bfb0045fdc83ed4a835f7dd37e32df3a73316369163fc47da1ed2d3'))
col = hex_to_base58(blake2b256(bytesLike(address_to_tree('HuMJCQzmJNTcbratSHhJa8L67xXPNJUkm4yhHwqqgSeV747n3UBic42pYjLs6Uhwqq4E67CM5EjA8tASobNNt53FdLkGqAg5wJi9PipbtcLMxhq8zxa2etpyJfWeMKfY5GsA48EvsVMhDFH34nzekZngmPsNdDUCZK6qtvcL6fAhbtTAMxSp1kxcEnSv4PnKFGT9dCjApLhW9nQk6x8jFTJzgGCnWE7V7db9UA1iqasgTukNv5FExmyvULHQqFcFsHEi5GGkuAduh7vrsgn68vnhqSe4u8EVC7R2fvRBKmrKq4LBLkvJvasYYhaEmMupP2U3M1jJoEVEPk1Nhh5bKuXa6hNqAhGPMhfCdLTwy8WUMugVmLVCc2wum658itYxmcTQ3P54P4yLf2sSKQcAGKcVKJFh1GmpvTUWhifJUc3TQL3yizEZ61ezcyj7r3y2JEhYBRLjerrC1nhuCnHevEdFRDjuHQULimWGWSfsWnA5x2bVJBLNMiokYN8aDYzWRZMiyyb1f4nYiw5aFmLLRtJtncqDbCofY32ZGH1nytd3xpzSKgJNYBXJnSmccGZzaRLh6nAS6WBpDFsiemSpLfqnQL4Yp3BnUaANybXnq9ZWvNaGhashn6e7pUy6BfEpQmrRejb7ncXNxNuLpX1X4XE74D6XMsfHjh8YQ12fADa77SQnABZWSoQzqXRy3dUswhXXZUCC6p3qvBpg7mpyYNtjyaCZD7LW2SoVsxkmcfrVdMnVGD9VkC2DjD796m9RzQnHzHMi2jK3A7rpmSPy1jGkL6EG6ADHJ8itsUwrkmfcV8tW3aHEiZQrzCprv98GkSHkQfHMNs5mZKR8dAEPwbuKPr8iqMC4jCPqq2pZomMLhrVkxsDFU96xnkF189QcwiJehnJmY1hFoQ1hM7CvaefeRhfbcHrgJmAk2CLwKX4L8ddP1k7N4yqr6ajnGz6A4acb6SupUVHwXDfzHB5DNT1L4e6gVtJgdNZ6xkhApeVXAucrvuQAvBMiAyyJKiCkf9x7witH2osDtpLmysyDitaYT1duYocZDKqkZfkVxxYWFXEPKaaq4mByiUfJnc5CAHeWZmconDZ2zonnHrr5fefq2879QZibb4sFiQjinxNyUBBoQ1ATj2nSWSABqGUq9qHmBrfhT7tdMg769PoWKNgpjcMkEju1hKYeLDBZJnSoquusw66ShpfEiQAMtYZrtJJQCe3AMTzhxK1g34jNYQk2gTgVy6ENL6jWRjuJPkfQo6gwUnS5aYQjNdidXPVueDJfi9TgvtdXMJuEZ1rh6Cha9pgQDfDqAmfsrSiFpBwq5KtiSsDoMsvEYr4XsfE1Ar7vt27dgsjUkzEX9mJYw99V6dr5gD93Hvi1dKsMKUVPJFFy3X6ak9xA61vuz7przVZSTdJxzA9vRApCU1xyjkFSBSte6DMtXoUC7j7Zp7mEJvf2dXYkAvWfavMB8LMECLViuZkw3A9XpXNuqky4bxWD9tvq6tJBQcKh3USkAc96TQvBCa35eHbia2eh2DfC67qUDmQMc3Q3NA5hHu4umgr872UF9v6BEFN5SueSVmL9eFRRiFFaHHz7aKpP3XaQYnRxjECgAqBdVKNqRzQA5cFoZ8GpN45ydRsuTcJJnMj8rRib42q9nMmJHakZis2NxP4fBShoCR4jZzD8q5tpweiWEUnUgceFuguhTXNyNVk1rTSS8aWCr3oK6TnbvcE2EMRjUHVWecCBehtMGwFXxBCS2TKFwjqEjA6xZUHXTEb6XCbs3JhirksEH1YpZo96Rvqa5qfS1sfc73DF9d2wBSx2sQjxXu2k9pFzeSrbJgTmEpCDT7KPFJPThqJCbVGieYDJ7YDs2j97ACoYJ3URmKvYBw3e3gwYBr5h5Lh8Rf4YF4Q2mLvo2sfTsoRL6o35FjMFjr9JErr8ufZsKV1pSPxgTBUVhz8twMtVQgHiUnQ5ojHYakpBEYSxqT3KeSyRDC8zWh2iKFMCHiS1iaNZ'))))
print(generate_pool_script(col, childBoxNft, parameterBoxNft, [2000, 200000]))
dsd"""


logger = set_logger(__name__)
if __name__ == "__main__":
    logger.info("Beginning Off-Chain Bot")

    SLEEP_TIME = 5
    curr_height = -1
    unlock_wallet()
    dummy_script = generate_dummy_script(node_address)

    while not sleep(SLEEP_TIME):
        try:
            new_height = current_height()
            if new_height > curr_height:
                unlock_wallet()
                logger.debug("Block %d found", new_height)
                curr_height = new_height
                for pool in (pools + current_pools[0:]):
                    try:
                        if pool["is_Erg"]:
                            curr_tx_obj = e_lend_proxy_job(pool)
                            curr_tx_obj = e_withdraw_proxy_job(pool, curr_tx_obj)
                            curr_tx_obj = e_borrow_proxy_job(pool, curr_tx_obj)
                            curr_tx_obj = e_repay_to_pool_job(pool, curr_tx_obj)
                            e_repay_proxy_job(pool)
                            e_partial_repay_proxy_job(pool)
                            e_liquidation_job(pool, dummy_script, curr_height)
                            e_update_interest_rate(pool, curr_height, curr_tx_obj, dummy_script)
                        else:
                            curr_tx_obj = t_lend_proxy_job(pool)
                            curr_tx_obj = t_withdraw_proxy_job(pool, curr_tx_obj)
                            curr_tx_obj = t_borrow_proxy_job(pool, curr_tx_obj)
                            t_repay_proxy_job(pool)
                            t_update_interest_rate(pool, curr_height, curr_tx_obj, dummy_script)
                    except Exception:
                        logger.exception("Exception")
        except KeyboardInterrupt:
            raise
        except Exception:
            logger.exception("Exception")
            curr_height -= 1