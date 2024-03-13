from __future__ import print_function
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import pandas as pd
import warnings

import abupy
from abupy import AbuFactorBuyBase, BuyCallMixin

warnings.filterwarnings('ignore')
sns.set_context(rc={'figure.figsize': (14, 7)})
# 使用沙盒数据，目的是和书中一样的数据环境
abupy.env.enable_example_env_ipython()


class ABuFactorBuyThreeVolume(AbuFactorBuyBase, BuyCallMixin):
    """
        拟合三倍成交量买入示例类
    """

    def _init_self(self, **kwargs):
        """通过kwargs设置拟合角度边际条件，配置因子参数"""

        """kwargs中必须包含: 突破参数xd 比如20，30，40天...突破"""
        self.xd = kwargs.pop('xd', 20)
        self.factor_name = '{}:{}'.format(self.__class__.__name__, self.xd)

    def fit_day(self, today):
        """开始根据自定义成交量参数进行选股"""

        """
           针对每一个交易日拟合买入交易策略，寻找向上突破买入机会
           :param today: 当前驱动的交易日金融时间序列数据
           :return:
           """
        # 忽略不符合买入的天（统计周期内前xd天）
        if self.today_ind < self.xd - 1:
            return None

        # 今天的收盘价格达到xd天内最高价格则符合买入条件
        if today.volume >= self.kl_pd.volume[self.today_ind - self.xd + 1:self.today_ind + 1].mean() * 3:
            # 把突破新高参数赋值skip_days，这里也可以考虑make_buy_order确定是否买单成立，但是如果停盘太长时间等也不好
            self.skip_days = self.xd
            # 生成买入订单, 由于使用了今天的收盘价格做为策略信号判断，所以信号发出后，只能明天买
            return self.buy_tomorrow()
        return None
