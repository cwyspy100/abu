from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from abupy.FactorSellBu.ABuFactorSellBase import AbuFactorSellBase, ESupportDirection
from abupy.IndicatorBu.ABuNDMa import calc_ma_from_prices

class AbuFactorSellMacd(AbuFactorSellBase):
    """MACD均线交叉卖出策略"""

    def _init_self(self, **kwargs):
        """
        kwargs中可选参数：
        fast: 快线周期，默认30日
        slow: 慢线周期，默认60日
        """
        self.fast_period = kwargs.pop('fast', 30)
        self.slow_period = kwargs.pop('slow', 60)
        self.skip_days = kwargs.pop('skip_days', self.slow_period + 1)

    def support_direction(self):
        """支持的方向，只支持正向"""
        return [ESupportDirection.DIRECTION_CAll.value]

    def fit_day(self, today, orders):
        """
        针对每一个交易日完成卖出交易策略
        :param today: 当前驱动的交易日金融时间序列数据
        :param orders: 买入的订单，今天可能有多个订单
        """
        # 今天的收盘价格
        today_close = today.close
        # 获取快线和慢线的均线值
        fast_line = calc_ma_from_prices(self.kl_pd.close, self.fast_period, min_periods=1)
        slow_line = calc_ma_from_prices(self.kl_pd.close, self.slow_period, min_periods=1)

        # 卖出条件：
        # 1. 快线在今天下穿慢线
        # 2. 今天的价格要低于快线
        if len(fast_line) >= 2 and len(slow_line) >= 2:
            # 今天和昨天的快慢线差值
            today_diff = fast_line[-1] - slow_line[-1]
            yesterday_diff = fast_line[-2] - slow_line[-2]

            # 判断是否发生下穿
            if yesterday_diff > 0 and today_diff < 0 and today_close < fast_line[-1]:
                # 卖出所有持仓
                for order in orders:
                    self.sell_tomorrow(order)

    def __str__(self):
        """打印对象显示：class name, fast_period, slow_period"""
        return '{}: fast_period={}, slow_period={}'.format(self.__class__.__name__, 
                                                         self.fast_period, 
                                                         self.slow_period)