# -*- coding: utf-8 -*-
"""
60 日均线上穿 120 日均线（金叉）时买入择时因子。

参考 ABuFactorBuyMean：使用短期/长期均线，在金叉当日收盘后发出信号，次日买入。
"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

import pandas as pd

from abupy import AbuFactorBuyBase, BuyCallMixin


class AbuFactorBuyMa60Cross120(AbuFactorBuyBase, BuyCallMixin):
    """正向：60 日均线上穿 120 日均线触发买入（金叉）。"""

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
        self.factor_name = '{}:{}:{}'.format(
            self.__class__.__name__, self.short, self.long
        )

    def fit_day(self, today):
        """
        当日发生金叉则发出买入：今日 ma_short > ma_long，且昨日 ma_short <= ma_long。
        需足够历史 K 线以计算长期均线。
        """
        if self.today_ind < self.long - 1:
            return None

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
            return None

        # 金叉：今日在上方，昨日不在上方（含相等视为未上穿）
        golden = (ma_s_t > ma_l_t) and (ma_s_y <= ma_l_y)
        if not golden:
            return None

        self.skip_days = 5
        return self.buy_tomorrow()

    @staticmethod
    def _nan_any(*vals):
        for v in vals:
            try:
                if pd.isna(v):
                    return True
            except Exception:
                return True
        return False
