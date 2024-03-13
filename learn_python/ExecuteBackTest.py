# -*- encoding:utf-8 -*-
from __future__ import print_function

import warnings

# noinspection PyUnresolvedReferences
import abu_local_env
import seaborn as sns

import abupy
from abupy import ABuPickTimeExecute
from abupy import AbuBenchmark
from abupy import AbuCapital
from abupy import AbuFactorAtrNStop
from abupy import AbuFactorCloseAtrNStop
from abupy import AbuFactorPreAtrNStop
from abupy import AbuFactorSellBreak
from abupy import AbuMetricsBase
from abupy import AbuFactorBuyXD, AbuFactorBuyXDBK

from learn_python.ABuFactorHaiGuiBuyBreak import ABuFactorHaiGuiBuyBreak

warnings.filterwarnings('ignore')
sns.set_context(rc={'figure.figsize': (14, 7)})
# 使用沙盒数据，目的是和书中一样的数据环境
abupy.env.enable_example_env_ipython()


def execute_test(show=True):
    """
    8.1.2 卖出因子的实现
    :return:
    """

    # 120天向下突破为卖出信号
    sell_factor1 = {'xd': 120, 'class': AbuFactorSellBreak}
    # 趋势跟踪策略止盈要大于止损设置值，这里0.5，3.0
    sell_factor2 = {'stop_loss_n': 0.5, 'stop_win_n': 3.0, 'class': AbuFactorAtrNStop}
    # 暴跌止损卖出因子形成dict
    sell_factor3 = {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.0}
    # 保护止盈卖出因子组成dict
    sell_factor4 = {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5}
    # 四个卖出因子同时生效，组成sell_factors
    sell_factors = [sell_factor1, sell_factor2, sell_factor3, sell_factor4]

    # buy_factors 60日向上突破，42日向上突破两个因子
    buy_factors = [{'xd': 42, 'class': ABuFactorHaiGuiBuyBreak},{'xd': 60, 'class': ABuFactorHaiGuiBuyBreak}]
    benchmark = AbuBenchmark()

    capital = AbuCapital(1000000, benchmark)
    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(['usTSLA'], benchmark, buy_factors, sell_factors, capital, show=True)

    metrics = AbuMetricsBase(orders_pd, action_pd, capital, benchmark)
    metrics.fit_metrics()
    if show:
        print('orders_pd[:10]:\n', orders_pd[:10].filter(
            ['symbol', 'buy_price', 'buy_cnt', 'buy_factor', 'buy_pos', 'sell_date', 'sell_type_extra', 'sell_type',
             'profit']))
        print('action_pd[:10]:\n', action_pd[:10])
        metrics.plot_returns_cmp(only_show_returns=True)
    return metrics


if __name__ == '__main__':
    execute_test()
