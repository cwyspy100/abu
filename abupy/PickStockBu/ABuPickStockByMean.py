# -*- encoding:utf-8 -*-
"""
    选股示例因子：均值选股因子
"""
from __future__ import print_function
from __future__ import absolute_import
from __future__ import division

from .ABuPickStockBase import AbuPickStockBase, reversed_result
from ..UtilBu import ABuRegUtil
import numpy as np

__author__ = '阿布'
__weixin__ = 'abu_quant'


class AbuPickStockByMean(AbuPickStockBase):
    """价格选股因子示例类，通过价格刚大于120日均线值"""

    def _init_self(self, **kwargs):
        """通过kwargs设置选股价格边际条件，配置因子参数"""

        # 暂时与base保持一致不使用kwargs.pop('a', default)方式
        # fit_pick中选择 > 最小(threshold_price_min), 默认负无穷，即默认所有都符合
        self.mean_xd = 120
        if 'mean_xd' in kwargs:
            # 最小价格阀值
            self.mean_xd = kwargs['mean_xd']

        # # fit_pick中选择 < 最大(threshold_price_max), 默认正无穷，即默认所有都符合
        # self.threshold_price_max = np.inf
        # if 'threshold_price_max' in kwargs:
        #     # 最大价格阀值
        #     self.threshold_price_max = kwargs['threshold_price_max']

    @reversed_result
    def fit_pick(self, kl_pd, target_symbol):
        """开始根据自定义价格边际参数进行选股"""
        kl_pd['MA_xd'] = kl_pd['close'].rolling(window=self.mean_xd).mean()
        last_ma = kl_pd['MA_xd'].iloc[-1]
        last_price = kl_pd['close'].iloc[-1]
        before_last_ma = kl_pd['MA_xd'].iloc[-2]
        before_last_price = kl_pd['close'].iloc[-2]
        # before_last_ma_1 = kl_pd['MA_xd'].iloc[-3]
        # before_last_price_1 = kl_pd['close'].iloc[-3]
        # before_change = before_last_price / before_last_price_1 - 1
        # last_change = last_price / before_last_price - 1

        # deg = ABuRegUtil.calc_regress_deg(kl_pd[-10:].close, show=False)

        radio = last_price - last_ma > 0

        if (radio):
            print(
                "target_symobol {} last_price {} minus last_ma {} value :{}".format(target_symbol, last_price, last_ma,
                                                                                    last_price - last_ma))
            return True

        # if kl_pd.close.max() < self.threshold_price_max and kl_pd.close.min() > self.threshold_price_min:
        #     # kl_pd.close的最大价格 < 最大价格阀值 且 kl_pd.close的最小价格 > 最小价格阀值
        #     return True
        return False

    def fit_first_choice(self, pick_worker, choice_symbols, *args, **kwargs):
        raise NotImplementedError('AbuPickStockPriceMinMax fit_first_choice unsupported now!')
