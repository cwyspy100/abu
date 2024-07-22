'''
通过均值，比如120天的均线，今天的金额大于120均线数值就买入，对应有卖出

'''

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

from abupy import AbuFactorBuyBase, AbuFactorBuyXD, BuyCallMixin, BuyPutMixin
from abupy.UtilBu import ABuRegUtil


# noinspection PyAttributeOutsideInit
class AbuFactorBuyMeanAng(AbuFactorBuyBase, BuyCallMixin):
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
        self.kl_pd['ma_120_1'] = self.kl_pd['close'].rolling(window=int(self.xd / 2)).mean()
        self.kl_pd['ma_120_2'] = self.kl_pd['close'].rolling(window=int(self.xd / 3)).mean()
        self.kl_pd['ma_120_3'] = self.kl_pd['close'].rolling(window=int(self.xd / 4)).mean()
        self.kl_pd['ma_120_4'] = self.kl_pd['close'].rolling(window=int(self.xd / 5)).mean()

        tmp = self.kl_pd['ma_120'][self.today_ind - 30:self.today_ind]
        tmp1 = self.kl_pd['ma_120_1'][self.today_ind - 30:self.today_ind]
        tmp2 = self.kl_pd['ma_120_2'][self.today_ind - 30:self.today_ind]
        tmp3 = self.kl_pd['ma_120_3'][self.today_ind - 30:self.today_ind]
        tmp4 = self.kl_pd['ma_120_4'][self.today_ind - 30:self.today_ind]

        ang = ABuRegUtil.calc_regress_deg(tmp, show=False)
        ang1 = ABuRegUtil.calc_regress_deg(tmp1, show=False)
        ang2 = ABuRegUtil.calc_regress_deg(tmp2, show=False)
        ang3 = ABuRegUtil.calc_regress_deg(tmp3, show=False)
        ang4 = ABuRegUtil.calc_regress_deg(tmp4, show=False)

        if ang4 > ang3 > ang2 > ang1 > ang > 0:
            # 把突破新高参数赋值skip_days，这里也可以考虑make_buy_order确定是否买单成立，但是如果停盘太长时间等也不好
            self.skip_days = self.xd / 2
            # self.skip_days = 1
            # 生成买入订单, 由于使用了今天的收盘价格做为策略信号判断，所以信号发出后，只能明天买
            return self.buy_tomorrow()
            # return self.buy_today()
        return None
