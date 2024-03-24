# -*- encoding:utf-8 -*-
"""
    买入择时示例因子：动态自适应双均线策略
    这个使用慢均线的昨天，前天，打前天的数据对比进行选择买入。

"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from abupy.FactorBuyBu.ABuFactorBuyBase import AbuFactorBuyXD, BuyCallMixin
from abupy.TLineBu.ABuTL import AbuTLine
from abupy.UtilBu import ABuRegUtil

__author__ = '阿布'
__weixin__ = 'abu_quant'


# noinspection PyAttributeOutsideInit

# noinspection PyAttributeOutsideInit
class CyUpTrend(AbuFactorBuyXD, BuyCallMixin):
    """示例长线上涨中寻找短线下跌买入择时因子，混入BuyCallMixin"""

    def _init_self(self, **kwargs):
        """
            kwargs中可以包含xd: 比如20，30，40天...突破，默认20
            kwargs中可以包含past_factor: 代表长线的趋势判断长度，默认4，long = xd * past_factor->eg: long = 20 * 4
            kwargs中可以包含up_deg_threshold: 代表判断上涨趋势拟合角度阀值，即长线拟合角度值多少决策为上涨，默认3
        """
        if 'xd' not in kwargs:
            # 如果外部没有设置xd值，默认给一个30
            kwargs['xd'] = 10
        super(CyUpTrend, self)._init_self(**kwargs)
        # 代表长线的趋势判断长度，默认4，long = xd * past_factor->eg: long = 30 * 4
        self.past_factor = kwargs.pop('past_factor', 4)
        # 代表判断上涨趋势拟合角度阀值，即长线拟合角度值多少决策为上涨，默认4
        self.up_deg_threshold = kwargs.pop('up_deg_threshold', 3)

    def fit_day(self, today):
        """
        长线周期选择目标为上升趋势的目标，短线寻找近期走势为向下趋势的目标进行买入，期望是持续之前长相的趋势
            1. 通过past_today_kl获取长周期的金融时间序列，通过AbuTLine中的is_up_trend判断
            长周期是否属于上涨趋势，
            2. 今天收盘价为最近xd天内最低价格，且短线xd天的价格走势为下跌趋势
            3. 满足1，2发出买入信号
        :param today: 当前驱动的交易日金融时间序列数据
        """
        # long_kl = self.past_today_kl(today, self.past_factor * self.xd)
        # tl_long = AbuTLine(long_kl.close, 'long')
        # # 判断长周期是否属于上涨趋势
        # if tl_long.is_up_trend(up_deg_threshold=self.up_deg_threshold, show=False):
        #     if today.close == self.xd_kl.close.min() and AbuTLine(
        #             self.xd_kl.close, 'short').is_down_trend(down_deg_threshold=-self.up_deg_threshold, show=False):
        #         # 今天收盘价为最近xd天内最低价格，且短线xd天的价格走势为下跌趋势
        #         return self.buy_tomorrow()



        if today.close == self.xd_kl.close.max() and AbuTLine(
                self.xd_kl.close, 'short').is_up_trend(up_deg_threshold=self.up_deg_threshold, show=False):
            # 今天收盘价为最近xd天内最高价格，且短线xd天的价格走势为上升趋势
            return self.buy_tomorrow()


class CyMultiUpTrend(AbuFactorBuyXD, BuyCallMixin):
    """示例长线上涨中寻找短线下跌买入择时因子，混入BuyCallMixin"""

    def _init_self(self, **kwargs):
        """
            kwargs中可以包含xd: 比如20，30，40天...突破，默认20
            kwargs中可以包含past_factor: 代表长线的趋势判断长度，默认4，long = xd * past_factor->eg: long = 20 * 4
            kwargs中可以包含up_deg_threshold: 代表判断上涨趋势拟合角度阀值，即长线拟合角度值多少决策为上涨，默认3
        """
        if 'xd' not in kwargs:
            # 如果外部没有设置xd值，默认给一个30
            kwargs['xd'] = 20
        super(CyMultiUpTrend, self)._init_self(**kwargs)
        # 代表长线的趋势判断长度，默认4，long = xd * past_factor->eg: long = 30 * 4
        self.past_factor = kwargs.pop('past_factor', 4)
        # 代表判断上涨趋势拟合角度阀值，即长线拟合角度值多少决策为上涨，默认4
        self.up_deg_threshold = kwargs.pop('up_deg_threshold', 3)

    def fit_day(self, today):
        """
        长线周期选择目标为上升趋势的目标，短线寻找近期走势为向下趋势的目标进行买入，期望是持续之前长相的趋势
            1. 通过past_today_kl获取长周期的金融时间序列，通过AbuTLine中的is_up_trend判断
            长周期是否属于上涨趋势，
            2. 今天收盘价为最近xd天内最低价格，且短线xd天的价格走势为下跌趋势
            3. 满足1，2发出买入信号
        :param today: 当前驱动的交易日金融时间序列数据
        """
        # long_kl = self.past_today_kl(today, self.past_factor * self.xd)
        # tl_long = AbuTLine(long_kl.close, 'long')
        # # 判断长周期是否属于上涨趋势
        # if tl_long.is_up_trend(up_deg_threshold=self.up_deg_threshold, show=False):
        #     if today.close == self.xd_kl.close.min() and AbuTLine(
        #             self.xd_kl.close, 'short').is_down_trend(down_deg_threshold=-self.up_deg_threshold, show=False):
        #         # 今天收盘价为最近xd天内最低价格，且短线xd天的价格走势为下跌趋势
        #         return self.buy_tomorrow()

        xd_kl_5 = self.kl_pd[self.today_ind - 5 + 1:self.today_ind + 1]
        xd_kl_10 = self.kl_pd[self.today_ind - 10 + 1:self.today_ind + 1]
        xd_kl_20 = self.kl_pd[self.today_ind - 20 + 1:self.today_ind + 1]

        # deg_5 = ABuRegUtil.calc_regress_deg(self.xd_kl_5.close, show=False)
        # deg_10 = ABuRegUtil.calc_regress_deg(self.xd_kl_10.close, show=False)
        # deg_20 = ABuRegUtil.calc_regress_deg(self.xd_kl_20.close, show=False)

        up_5 = AbuTLine(xd_kl_5.close, 'short').is_up_trend(up_deg_threshold=self.up_deg_threshold, show=False)
        up_10 = AbuTLine(xd_kl_10.close, 'short').is_up_trend(up_deg_threshold=self.up_deg_threshold, show=False)
        up_20 = AbuTLine(xd_kl_20.close, 'short').is_up_trend(up_deg_threshold=self.up_deg_threshold, show=False)

        if today.close == self.xd_kl.close.max() and up_5 and up_10 and up_20:
            # return self.buy_tomorrow()
            return self.buy_today()

        # if today.close == self.xd_kl.close.max() and AbuTLine(
        #         self.xd_kl.close, 'short').is_up_trend(up_deg_threshold=self.up_deg_threshold, show=False):
        #     # 今天收盘价为最近xd天内最高价格，且短线xd天的价格走势为上升趋势
        #     return self.buy_tomorrow()