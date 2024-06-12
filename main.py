from time import sleep

from bootstrapping.pool_creation import create_pool, allAddressesWithBoxes
from contracts.quacks import generate_repayment_script, generate_collateral_script, generate_pool_script
from helpers.platform_functions import update_pools_in_file
from helpers.serializer import bytesLike, blake2b256
from token_pools.t_borrow_proxy_susd import t_borrow_proxy_job
from current_pools import pools
from client_consts import node_address
from erg_pool.e_borrow_proxy import e_borrow_proxy_job
from erg_pool.e_interest_rate import e_update_interest_rate
from erg_pool.e_lend_proxy import e_lend_proxy_job
from erg_pool.e_liquidation import e_liquidation_job
from erg_pool.e_partial_repay_proxy import e_partial_repay_proxy_job
from helpers.node_calls import unlock_wallet, current_height, generate_dummy_script, address_to_tree
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
addy = ["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"]
print(allAddressesWithBoxes(addy))
create_pool()
dd
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
                for pool in pools[0:]:
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
                            curr_tx_obj = t_repay_to_pool_job(pool, curr_tx_obj)
                            t_repay_proxy_job(pool)
                            t_partial_repay_proxy_job(pool)
                            t_liquidation_job(pool, dummy_script, curr_height)
                            t_update_interest_rate(pool, curr_height, curr_tx_obj, dummy_script)
                    except Exception:
                        logger.exception("Exception")
        except KeyboardInterrupt:
            raise
        except Exception:
            logger.exception("Exception")
            curr_height -= 1