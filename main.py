from time import sleep

from helpers.custom_routines import custom_routine
from token_pools.t_borrow_proxy_susd import t_borrow_proxy_job
from consts import pools
from client_consts import node_address
from erg_pool.e_borrow_proxy import e_borrow_proxy_job
from erg_pool.e_interest_rate import e_update_interest_rate
from erg_pool.e_lend_proxy import e_lend_proxy_job
from erg_pool.e_liquidation import e_liquidation_job
from erg_pool.e_partial_repay_proxy import e_partial_repay_proxy_job
from helpers.node_calls import unlock_wallet, current_height, generate_dummy_script
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

logger = set_logger(__name__)
if __name__ == "__main__":
    logger.info("Beginning Off-Chain Bot")

    SLEEP_TIME = 5
    curr_height = -1
    unlock_wallet()
    dummy_script = generate_dummy_script(node_address)

    while not sleep(SLEEP_TIME):
        try:
            custom_routine()
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