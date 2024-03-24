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
from abupy import AbuFactorSellBreak

from abupy import AbuDoubleMaBuy, AbuDoubleMaSell, ABuKLUtil, ABuSymbolPd, AbuUpDownTrend, AbuDownUpTrend, AbuUpDownGolden
from abupy import AbuFactorCloseAtrNStop, AbuFactorAtrNStop, AbuFactorPreAtrNStop, tl
from abupy import abu, ABuProgress, AbuMetricsBase, EMarketTargetType, ABuMarketDrawing

from learn_python.ABuFactorHaiGuiBuyBreak import ABuFactorHaiGuiBuyBreak
from learn_python.ABuFactorBuyMean import AbuFactorBuyMean
from learn_python.ABuFactorSellMean import AbuFactorSellMean
from learn_python.ABuUpTrend import CyUpTrend, CyMultiUpTrend

warnings.filterwarnings('ignore')
sns.set_context(rc={'figure.figsize': (14, 7)})
# 使用沙盒数据，目的是和书中一样的数据环境
abupy.env.enable_example_env_ipython()
abupy.env.disable_example_env_ipython()


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
    buy_factors = [{'xd': 42, 'class': AbuDoubleMaBuy}]
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


def execute_test_mean(show=True):
    """
    8.1.2 卖出因子的实现
    :return:
    """

    # 120天向下突破为卖出信号
    sell_factor1 = {'xd': 120, 'class': AbuFactorSellMean}
    # 趋势跟踪策略止盈要大于止损设置值，这里0.5，3.0
    sell_factor2 = {'stop_loss_n': 0.5, 'stop_win_n': 3.0, 'class': AbuFactorAtrNStop}
    # 暴跌止损卖出因子形成dict
    sell_factor3 = {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.0}
    # 保护止盈卖出因子组成dict
    sell_factor4 = {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5}
    # 四个卖出因子同时生效，组成sell_factors
    sell_factors = [sell_factor1, sell_factor2, sell_factor3, sell_factor4]

    # buy_factors 60日向上突破，42日向上突破两个因子
    buy_factors = [{'xd': 120, 'class': AbuFactorBuyMean}]
    benchmark = AbuBenchmark()

    capital = AbuCapital(1000000, benchmark)
    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(['usFUTU'], benchmark, buy_factors, sell_factors, capital, show=True)

    metrics = AbuMetricsBase(orders_pd, action_pd, capital, benchmark)
    metrics.fit_metrics()
    if show:
        print('orders_pd[:10]:\n', orders_pd[:10].filter(
            ['symbol', 'buy_price', 'buy_cnt', 'buy_factor', 'buy_pos', 'sell_date', 'sell_type_extra', 'sell_type',
             'profit']))
        print('action_pd[:10]:\n', action_pd[:10])
        metrics.plot_returns_cmp(only_show_returns=True)
    return metrics



def execute_test_down_up_strategy():
    cash = 3000000

    us_choice_symbols = ['usTSLA', 'usNOAH', 'usSFUN', 'usBIDU', 'usAAPL', 'usGOOG', 'usWUBA', 'usVIPS']
    # cn_choice_symbols = ['002230', '300104', '300059', '601766', '600085', '600036', '600809', '000002', '002594',
    #                      '002739']
    # hk_choice_symbols = ['hk03333', 'hk00700', 'hk02333', 'hk01359', 'hk00656', 'hk03888', 'hk02318']

    def run_loo_back(choice_symbols, ps=None, n_folds=3, start=None, end=None, only_info=False):
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

    # 买入策略使用AbuDownUpTrend
    buy_factors = [{'class': AbuDownUpTrend}]
    # 卖出策略：利润保护止盈策略+风险下跌止损+较大的止盈位
    sell_factors = [{'stop_loss_n': 1.0, 'stop_win_n': 3.0,
                     'class': AbuFactorAtrNStop},
                    {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.5},
                    {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5}]
    # 开始回测
    abu_result_tuple, metrics = run_loo_back(us_choice_symbols, only_info=True)


def execute_test_up_strategy():
    cash = 3000000

    us_choice_symbols = ['usTSLA', 'usNOAH', 'usSFUN', 'usBIDU', 'usAAPL', 'usGOOG', 'usWUBA', 'usVIPS']
    cn_choice_symbols = ['002230', '300104', '300059', '601766', '600085', '600036', '600809', '000002', '002594',
                         '002739']
    hk_choice_symbols = ['hk03333', 'hk00700', 'hk02333', 'hk01359', 'hk00656', 'hk03888', 'hk02318']

    def run_loo_back(choice_symbols, ps=None, n_folds=3, start=None, end=None, only_info=False):
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

    # 买入策略使用AbuDownUpTrend
    buy_factors = [{'class': CyUpTrend}]
    # 卖出策略：利润保护止盈策略+风险下跌止损+较大的止盈位
    sell_factors = [{'stop_loss_n': 1.0, 'stop_win_n': 3.0,
                     'class': AbuFactorAtrNStop},
                    {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.5},
                    {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5}]
    # 开始回测
    abu_result_tuple, metrics = run_loo_back(hk_choice_symbols, only_info=True)

def execute_test_multi_up_strategy():
    cash = 1000000

    us_choice_symbols = ['usTSLA', 'usNOAH', 'usSFUN', 'usBIDU', 'usAAPL', 'usGOOG', 'usWUBA', 'usVIPS']
    us_choice_symbols = ['usTSLA']
    cn_choice_symbols = ['002230', '300104', '300059', '601766', '600085', '600036', '600809', '000002', '002594',
                         '002739']
    hk_choice_symbols = ['hk03333', 'hk00700', 'hk02333', 'hk01359', 'hk00656', 'hk03888', 'hk02318']
    hk_choice_symbols = ['hk03333']

    def run_loo_back(choice_symbols, ps=None, n_folds=3, start=None, end=None, only_info=False):
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

    # 买入策略使用AbuDownUpTrend
    buy_factors = [{'class': CyUpTrend}]
    # 卖出策略：利润保护止盈策略+风险下跌止损+较大的止盈位
    sell_factors = [{'stop_loss_n': 1.0, 'stop_win_n': 3.0,
                     'class': AbuFactorAtrNStop},
                    {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.5},
                    {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5}]
    # 开始回测
    abu_result_tuple, metrics = run_loo_back(us_choice_symbols, only_info=True)

    tsla_orders = abu_result_tuple.orders_pd[abu_result_tuple.orders_pd.symbol == 'usTSLA']

    print(tsla_orders)



if __name__ == '__main__':
    # execute_test()
    # execute_test_mean()
    # execute_test_down_up_strategy()
    # execute_test_up_strategy()
    execute_test_multi_up_strategy()
