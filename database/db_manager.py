from .core import CoreDB
from .currency_mixin import CurrencyMixin
from .transaction_mixin import TransactionMixin
from .pool_mixin import PoolMixin
from .history_mixin import HistoryMixin


class DatabaseManager(CoreDB,
                      TransactionMixin,
                      PoolMixin,
                      HistoryMixin,
                      CurrencyMixin):
    pass
