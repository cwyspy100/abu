# -*- encoding:utf-8 -*-
"""
    选股示例因子：涨幅选股因子
"""
from __future__ import print_function
from __future__ import absolute_import
from __future__ import division

from .ABuPickStockBase import AbuPickStockBase, reversed_result
from ..UtilBu import ABuRegUtil
import numpy as np

__author__ = '阿布'
__weixin__ = 'abu_quant'


class AbuPickStockByGrow(AbuPickStockBase):
    """涨幅选股因子示例类，通过涨幅大于20"""

    def _init_self(self, **kwargs):
        """通过kwargs设置选股价格边际条件，配置因子参数"""

        # 暂时与base保持一致不使用kwargs.pop('a', default)方式
        # fit_pick中选择 > 最小(threshold_price_min), 默认负无穷，即默认所有都符合
        self.mean_xd = 120
        if 'mean_xd' in kwargs:
            # 最小价格阀值
            self.mean_xd = kwargs['mean_xd']

        self.grow_num = 20
        if 'grow_num' in kwargs:
            # 最小涨幅
            self.mean_xd = kwargs['grow_num']

    @reversed_result
    def fit_pick(self, kl_pd, target_symbol):
        """开始根据自定义价格边际参数进行选股"""
        # kl_pd['MA_xd'] = kl_pd['close'].rolling(window=self.mean_xd).mean()
        start_price = kl_pd['close'].iloc[-20]
        end_price = kl_pd['close'].iloc[0]
        increase = ((end_price - start_price) / start_price) * 100

        if increase > self.grow_num:
            print(
                "target_symobol {} start_price {} end_price {} grow :{}".format(target_symbol, start_price, end_price, increase))
            return True
        return False

    def fit_first_choice(self, pick_worker, choice_symbols, *args, **kwargs):
        raise NotImplementedError('AbuPickStockPriceMinMax fit_first_choice unsupported now!')
