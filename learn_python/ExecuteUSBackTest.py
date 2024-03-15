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

from abupy import AbuDoubleMaBuy, AbuDoubleMaSell, ABuKLUtil, ABuSymbolPd
from abupy import AbuFactorCloseAtrNStop, AbuFactorAtrNStop, AbuFactorPreAtrNStop
from abupy import abu, ABuProgress, AbuMetricsBase, EMarketTargetType, nd

from learn_python.ABuFactorHaiGuiBuyBreak import ABuFactorHaiGuiBuyBreak
from learn_python.ABuFactorBuyDMNew import AbuDoubleMaBuyNew

warnings.filterwarnings('ignore')
sns.set_context(rc={'figure.figsize': (14, 7)})
# 使用沙盒数据，目的是和书中一样的数据环境
# abupy.env.enable_example_env_ipython()
abupy.env.disable_example_env_ipython()


def get_data():
    futu_data = ABuSymbolPd.make_kl_df('usFUTU')
    print(futu_data.tail())


def execute_test(show=True):
    # 初始资金量
    cash = 1000000

    # 使用沙盒内的美股做为回测目标
    us_choice_symbols = ['usTSLA']

    # us_choice_symbols = ['usFUTU', 'usTSLA', 'usNOAH', 'usSFUN', 'usBIDU', 'usAAPL',
    #                      'usGOOG', 'usWUBA', 'usVIPS']




    # 买入双均线策略AbuDoubleMaBuy寻找金叉买入信号：ma快线＝5，ma慢线＝60
    buy_factors = [{'fast': 5, 'slow': 30, 'class': AbuDoubleMaBuyNew}]
    # 卖出双均线策略AbuDoubleMaSell寻找死叉卖出信号：ma快线＝5，ma慢线＝60，并行继续使用止盈止损基础策略
    sell_factors = [
                    {'fast': 5, 'slow': 10, 'class': AbuDoubleMaSell},
                    {'stop_loss_n': 1.0, 'stop_win_n': 3.0,
                     'class': AbuFactorAtrNStop},
                    {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.5},
                    {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5}]

    def run_loo_back(choice_symbols, ps=None, n_folds=2, start=None, end=None, only_info=False):
        """封装一个回测函数，返回回测结果，以及回测度量对象"""
        if choice_symbols[0].startswith('us'):
            abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_US
        else:
            abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_CN
        abu_result_tuple, _ = abu.run_loop_back(cash,
                                                buy_factors,
                                                sell_factors,
                                                ps,
                                                start=start,
                                                end=end,
                                                n_folds=n_folds,
                                                choice_symbols=choice_symbols)
        ABuProgress.clear_output()
        metrics = AbuMetricsBase.show_general(*abu_result_tuple, returns_cmp=only_info,
                                              only_info=only_info,
                                              only_show_returns=True)
        return abu_result_tuple, metrics

    # 开始回测
    abu_result_tuple, metrics = run_loo_back(us_choice_symbols)

    metrics.plot_buy_factors()
    metrics.plot_sell_factors()
    metrics.plot_order_returns_cmp()
    metrics.plot_sharp_volatility_cmp()

    tsla_orders = abu_result_tuple.orders_pd[abu_result_tuple.orders_pd.symbol == 'usTSLA']

    print(tsla_orders)

    nd.ma.plot_ma_from_order(tsla_orders.iloc[0], time_period=(5, 60))
    nd.ma.plot_ma_from_order(tsla_orders.iloc[1], time_period=(5, 60))
    nd.ma.plot_ma_from_order(tsla_orders.iloc[2], time_period=(5, 60))
    nd.ma.plot_ma_from_order(tsla_orders.iloc[3], time_period=(5, 60))
    nd.ma.plot_ma_from_order(tsla_orders.iloc[4], time_period=(5, 60))


def execute_test_new(show=True):
    # 初始资金量
    cash = 1000000

    # 使用沙盒内的美股做为回测目标
    us_choice_symbols = ['usFUTU']

    # us_choice_symbols = ['usTSLA', 'usNOAH', 'usSFUN', 'usBIDU', 'usAAPL',
    #                      'usGOOG', 'usWUBA', 'usVIPS']

    # 只传递慢线60，不传递快线参数为动态自适应快线值
    buy_factors = [{'slow': 60, 'class': AbuDoubleMaBuy}]

    # 卖出双均线策略AbuDoubleMaSell寻找死叉卖出信号：ma快线＝5，ma慢线＝60，并行继续使用止盈止损基础策略
    sell_factors = [{'fast': 5, 'slow': 60, 'class': AbuDoubleMaSell},
                    {'stop_loss_n': 1.0, 'stop_win_n': 3.0,
                     'class': AbuFactorAtrNStop},
                    {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.5},
                    {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5}]

    def run_loo_back(choice_symbols, ps=None, n_folds=2, start=None, end=None, only_info=False):
        """封装一个回测函数，返回回测结果，以及回测度量对象"""
        if choice_symbols[0].startswith('us'):
            abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_US
        else:
            abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_CN
        abu_result_tuple, _ = abu.run_loop_back(cash,
                                                buy_factors,
                                                sell_factors,
                                                ps,
                                                start=start,
                                                end=end,
                                                n_folds=n_folds,
                                                choice_symbols=choice_symbols)
        ABuProgress.clear_output()
        metrics = AbuMetricsBase.show_general(*abu_result_tuple, returns_cmp=only_info,
                                              only_info=only_info,
                                              only_show_returns=True)
        return abu_result_tuple, metrics

    # 开始回测
    abu_result_tuple, metrics = run_loo_back(us_choice_symbols)

    metrics.plot_buy_factors()
    metrics.plot_sell_factors()

    tsla_orders = abu_result_tuple.orders_pd[abu_result_tuple.orders_pd.symbol == 'usFUTU']

    print(tsla_orders)

    nd.ma.plot_ma_from_order(tsla_orders.iloc[0], time_period=(5, 60))
    nd.ma.plot_ma_from_order(tsla_orders.iloc[1], time_period=(5, 60))


def execute_test_new_1(show=True):
    # 初始资金量
    cash = 1000000

    # 使用沙盒内的美股做为回测目标
    us_choice_symbols = ['usTSLA']

    # us_choice_symbols = ['usFUTU', 'usTSLA', 'usNOAH', 'usSFUN', 'usBIDU', 'usAAPL',
    #                      'usGOOG', 'usWUBA', 'usVIPS']

    kl_dict = {us_symbol[2:]:
                   ABuSymbolPd.make_kl_df(us_symbol, start='2014-07-26', end='2015-07-26')
               for us_symbol in us_choice_symbols}

    # 不传递任何参数，快线， 慢线都动态自适应
    buy_factors = [{'class': AbuDoubleMaBuy}]

    # 卖出双均线策略AbuDoubleMaSell寻找死叉卖出信号：ma快线＝5，ma慢线＝60，并行继续使用止盈止损基础策略
    sell_factors = [{'fast': 5, 'slow': 60, 'class': AbuDoubleMaSell},
                    {'stop_loss_n': 1.0, 'stop_win_n': 3.0,
                     'class': AbuFactorAtrNStop},
                    {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.5},
                    {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5}]

    def run_loo_back(choice_symbols, ps=None, n_folds=2, start=None, end=None, only_info=False):
        """封装一个回测函数，返回回测结果，以及回测度量对象"""
        if choice_symbols[0].startswith('us'):
            abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_US
        else:
            abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_CN
        abu_result_tuple, _ = abu.run_loop_back(cash,
                                                buy_factors,
                                                sell_factors,
                                                ps,
                                                start=start,
                                                end=end,
                                                n_folds=n_folds,
                                                choice_symbols=choice_symbols)
        ABuProgress.clear_output()
        metrics = AbuMetricsBase.show_general(*abu_result_tuple, returns_cmp=only_info,
                                              only_info=only_info,
                                              only_show_returns=True)
        return abu_result_tuple, metrics

    # 开始回测
    abu_result_tuple, metrics = run_loo_back(us_choice_symbols)

    metrics.plot_buy_factors()
    metrics.plot_sell_factors()
    metrics.plot_order_returns_cmp()
    metrics.plot_sharp_volatility_cmp()

    tsla_orders = abu_result_tuple.orders_pd[abu_result_tuple.orders_pd.symbol == 'usTSLA']

    print(tsla_orders)

    nd.ma.plot_ma_from_order(tsla_orders.iloc[0], time_period=(5, 60))
    nd.ma.plot_ma_from_order(tsla_orders.iloc[1], time_period=(5, 60))
    nd.ma.plot_ma_from_order(tsla_orders.iloc[2], time_period=(5, 60))
    nd.ma.plot_ma_from_order(tsla_orders.iloc[3], time_period=(5, 60))
    ABuKLUtil.resample_close_mean(kl_dict)


if __name__ == '__main__':
    # get_data()
    # execute_test()
    # execute_test_new()
    execute_test_new_1()
