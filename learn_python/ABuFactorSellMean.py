
from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

from abupy import AbuFactorSellBase, AbuFactorBuyXD, BuyCallMixin, BuyPutMixin,ESupportDirection

'''
通过均值，比如120天的均线，今天的金额小于120均线数值就卖出，对应有卖出

'''
class AbuFactorSellMean(AbuFactorSellBase):
    """示例向下突破卖出择时因子"""

    def _init_self(self, **kwargs):
        """kwargs中必须包含: 突破参数xd 比如20，30，40天...突破"""

        # 向下突破参数 xd， 比如20，30，40天...突破
        self.xd = kwargs['xd']
        # 在输出生成的orders_pd中显示的名字
        self.sell_type_extra = '{}:{}'.format(self.__class__.__name__, self.xd)

    def support_direction(self):
        """支持的方向，只支持正向"""
        return [ESupportDirection.DIRECTION_CAll.value]

    def fit_day(self, today, orders):
        """
        寻找向下突破作为策略卖出驱动event
        :param today: 当前驱动的交易日金融时间序列数据
        :param orders: 买入择时策略中生成的订单序列
        """

        self.kl_pd['EMA120'] = self.kl_pd['close'].ewm(span=self.xd, adjust=False).mean()
        self.kl_pd['ma_120'] = self.kl_pd['close'].rolling(window=self.xd).mean()

        # 今天的收盘价格达到xd天内最高价格则符合买入条件
        # if today.close <= self.kl_pd['EMA120'].iloc[self.today_ind]:
        if today.close <= self.kl_pd['ma_120'].iloc[self.today_ind]:
        # 今天的收盘价格达到xd天内最低价格则符合条件
        # if today.close <= self.kl_pd.close[self.today_ind - self.xd + 1:self.today_ind + 1].mean():
            for order in orders:
                self.sell_tomorrow(order)
