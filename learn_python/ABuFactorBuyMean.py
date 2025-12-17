
'''
通过均值，比如120天的均线，今天的金额大于120均线数值就买入，对应有卖出

'''


from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

from abupy import AbuFactorBuyBase, AbuFactorBuyXD, BuyCallMixin, BuyPutMixin




# noinspection PyAttributeOutsideInit
class AbuFactorBuyMean(AbuFactorBuyBase, BuyCallMixin):
    """示例正向突破买入择时类，混入BuyCallMixin，即向上突破触发买入event"""

    def _init_self(self, **kwargs):
        """kwargs中必须包含: 突破参数xd 比如20，30，40天...突破"""
        # 突破参数 xd， 比如20，30，40天...突破, 不要使用kwargs.pop('xd', 20), 明确需要参数xq
        self.xd = kwargs['xd']
        # 在输出生成的orders_pd中显示的名字
        self.factor_name = '{}:{}'.format(self.__class__.__name__, self.xd)

    def fit_day(self, today):
        """
        针对每一个交易日拟合买入交易策略，寻找向上突破买入机会
        :param today: 当前驱动的交易日金融时间序列数据
        :return:
        """
        # 忽略不符合买入的天（统计周期内前xd天）
        if self.today_ind < self.xd - 1:
            return None

        # price = self.kl_pd.close[self.today_ind - self.xd + 1:self.today_ind + 1].mean()
        # self.kl_pd['EMA120'] = self.kl_pd['close'].ewm(span=self.xd, adjust=False).mean()
        self.kl_pd['ma_120'] = self.kl_pd['close'].rolling(window=self.xd).mean()

        # 今天的收盘价格达到xd天内最高价格则符合买入条件
        if today.close >= self.kl_pd['ma_120'].iloc[self.today_ind] and self.kl_pd.close[self.today_ind - 1] < self.kl_pd['ma_120'].iloc[self.today_ind - 1]:
        # if today.close >= self.kl_pd['EMA120'].iloc[self.today_ind] and self.kl_pd.close[self.today_ind - 1] < self.kl_pd['EMA120'].iloc[self.today_ind - 1]:
            # 把突破新高参数赋值skip_days，这里也可以考虑make_buy_order确定是否买单成立，但是如果停盘太长时间等也不好
            # self.skip_days = self.xd
            self.skip_days = 5
            # 生成买入订单, 由于使用了今天的收盘价格做为策略信号判断，所以信号发出后，只能明天买
            return self.buy_tomorrow()
            # return self.buy_today()
        return None