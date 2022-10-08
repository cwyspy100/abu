# -*- encoding:utf-8 -*-


from abupy import AbuSlippageBuyBase, slippage
import numpy as np

from abupy.SlippageBu.ABuSlippageBuyMean import g_open_down_rate


class AbuSlippageBuyMean2(AbuSlippageBuyBase):
    """示例日内滑点均价买入类"""

    @slippage.sbb.slippage_limit_up
    def fit_price(self):
        """
        取当天交易日的最高最低均价做为决策价格
        :return: 最终决策的当前交易买入价格
        """
        if self.kl_pd_buy.price_close == 0  or (self.kl_pd_buy.open / self.kl_pd_buy.price_close) < (1- g_open_down_rate):
            return np.inf

        # 买入价格为当天均价，即最高，最低的平均，也可使用高开低收平均等方式计算
        self.buy_price = np.mean([self.kl_pd_buy['high'], self.kl_pd_buy['low']])

        return self.buy_price
