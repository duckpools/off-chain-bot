from client_consts import report_wallet_balance, node_address
from helpers.explorer_calls import log_node_balance, log_node_transaction_count


def custom_routine():
    if report_wallet_balance:
        log_node_balance(node_address)
        log_node_transaction_count(node_address)
