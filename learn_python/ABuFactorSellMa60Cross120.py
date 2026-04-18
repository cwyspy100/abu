# -*- coding: utf-8 -*-
"""
60 日均线下穿 120 日均线（死叉）时卖出择时因子。

参考 ABuFactorSellMean：在死叉当日收盘后发出信号，次日卖出。
"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

import pandas as pd

from abupy import AbuFactorSellBase, ESupportDirection


class AbuFactorSellMa60Cross120(AbuFactorSellBase):
    """60 日均线下穿 120 日均线触发卖出（死叉）。"""

    def _init_self(self, **kwargs):
        """
        可选参数：
        - short: 短期均线周期，默认 60
        - long: 长期均线周期，默认 120
        """
        self.short = int(kwargs.get('short', 60))
        self.long = int(kwargs.get('long', 120))
        if self.short >= self.long:
            raise ValueError('short 必须小于 long')
        self.sell_type_extra = '{}:{}:{}'.format(
            self.__class__.__name__, self.short, self.long
        )

    def support_direction(self):
        return [ESupportDirection.DIRECTION_CAll.value]

    def fit_day(self, today, orders):
        """
        当日发生死叉则卖出：今日 ma_short < ma_long，且昨日 ma_short >= ma_long。
        """
        if self.today_ind < self.long - 1:
            return

        close = self.kl_pd['close']
        self.kl_pd['ma_short'] = close.rolling(
            window=self.short, min_periods=self.short
        ).mean()
        self.kl_pd['ma_long'] = close.rolling(
            window=self.long, min_periods=self.long
        ).mean()

        i = self.today_ind
        ma_s_t = self.kl_pd['ma_short'].iloc[i]
        ma_l_t = self.kl_pd['ma_long'].iloc[i]
        ma_s_y = self.kl_pd['ma_short'].iloc[i - 1]
        ma_l_y = self.kl_pd['ma_long'].iloc[i - 1]

        if self._nan_any(ma_s_t, ma_l_t, ma_s_y, ma_l_y):
            return

        # 死叉：今日在下方，昨日不在下方
        death = (ma_s_t < ma_l_t) and (ma_s_y >= ma_l_y)
        if not death:
            return

        for order in orders:
            self.sell_tomorrow(order)

    @staticmethod
    def _nan_any(*vals):
        for v in vals:
            try:
                if pd.isna(v):
                    return True
            except Exception:
                return True
        return False
