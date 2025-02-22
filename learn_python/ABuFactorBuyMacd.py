from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from abupy.FactorBuyBu.ABuFactorBuyBase import AbuFactorBuyBase, BuyCallMixin
from abupy.IndicatorBu.ABuNDMa import calc_ma_from_prices
from abupy.CoreBu.ABuPdHelper import pd_resample
import numpy as np


class AbuFactorBuyMacd(AbuFactorBuyBase, BuyCallMixin):
    """MACD均线交叉买入策略"""

    def _init_self(self, **kwargs):
        """
            kwargs中可选参数：
            fast: 快线周期，默认30日
            slow: 慢线周期，默认60日
            """
        self.fast_period = kwargs.pop('fast', 30)
        self.slow_period = kwargs.pop('slow', 60)
        self.skip_days = kwargs.pop('skip_days', self.slow_period + 1)

    def fit_day(self, today):
        """
        针对每一个交易日拟合买入交易策略
        :param today: 当前驱动的交易日金融时间序列数据
        :return:
        """
        # 今天的收盘价格
        today_close = today.close
        # 获取快线和慢线的均线值
        fast_line = calc_ma_from_prices(self.kl_pd.close, self.fast_period, min_periods=1)
        slow_line = calc_ma_from_prices(self.kl_pd.close, self.slow_period, min_periods=1)

        # 买入条件：
        # 1. 快线在今天上穿慢线
        # 2. 今天的价格要高于快线
        if len(fast_line) >= 2 and len(slow_line) >= 2:
            # 今天和昨天的快慢线差值
            today_diff = fast_line[-1] - slow_line[-1]
            yesterday_diff = fast_line[-2] - slow_line[-2]

            # 判断是否发生上穿
            if yesterday_diff < 0 and today_diff > 0 and today_close > fast_line[-1]:
                return self.buy_tomorrow()
        return None

    def fit_month(self, *args, **kwargs):
        pass

    def fit_week(self, *args, **kwargs):
        pass

    def __str__(self):
        """打印对象显示：class name, fast_period, slow_period"""
        return '{}: fast_period={}, slow_period={}'.format(self.__class__.__name__, 
                                                         self.fast_period, 
                                                         self.slow_period)