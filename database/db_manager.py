from .analytics_mixin import AnalyticsMixin
from .core import CoreDB
from .currency_mixin import CurrencyMixin
from .sync_mixin import SyncMixin
from .transaction_mixin import TransactionMixin
from .pool_mixin import PoolMixin
from .history_mixin import HistoryMixin
from .debt_mixin import DebtMixin
from .position_mixin import PositionMixin
from .headlinestats_mixin import HeadlinestatsMixin


class DatabaseManager(CoreDB,
                      TransactionMixin,
                      PoolMixin,
                      HistoryMixin,
                      CurrencyMixin,
                      AnalyticsMixin,
                      SyncMixin,
                      DebtMixin,
                      PositionMixin,
                      HeadlinestatsMixin):
    pass
