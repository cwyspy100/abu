# -*- encoding:utf-8 -*-

import abupy

abupy.env.disable_example_env_ipython()
from abupy import AbuBenchmark, AbuCapital, AbuFactorBuyBreak, AbuFactorSellBreak, ABuPickTimeExecute, ABuSymbolPd, \
    EMarketDataSplitMode, EMarketTargetType
abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_HK

from abupy import AbuFactorAtrNStop
from abupy import AbuFactorPreAtrNStop
from abupy import AbuFactorCloseAtrNStop


def buy_sell_factors_test(symbols):
    buy_factors = [{'xd': 60, 'class': AbuFactorBuyBreak}, {'xd': 42, 'class': AbuFactorBuyBreak}]
    sell_factors = [{'xd': 120, 'class': AbuFactorSellBreak}]

    benchmark = AbuBenchmark(n_folds=5)
    capital = AbuCapital(1000000, benchmark)

    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(symbols, benchmark, buy_factors,
                                                                              sell_factors, capital, show=True)
    if orders_pd is not None:
        print("orders_pd {}".format(orders_pd.tail()))


# review date:2023-03-29 周三 22:45
# review ： 1、基本止盈止损策略
def buy_sell_factors_atr_nstop(symbols):
    buy_factors = [{'xd': 60, 'class': AbuFactorBuyBreak}, {'xd': 42, 'class': AbuFactorBuyBreak}]
    sell_factor1 = {'xd': 120, 'class': AbuFactorSellBreak}
    # 趋势跟踪策略止盈要大于止损设置值，这里0.5，3.0
    sell_factor2 = {'stop_loss_n': 0.5, 'stop_win_n': 3.0,
                    'class': AbuFactorAtrNStop}

    sell_factors = [sell_factor1, sell_factor2]
    benchmark = AbuBenchmark()
    capital = AbuCapital(1000000, benchmark)

    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(symbols, benchmark, buy_factors,
                                                                              sell_factors, capital, show=True)
    if orders_pd is not None:
        print("orders_pd {}".format(orders_pd.tail(10)))


# review date:2023-03-29 周三 22:47
# review ：2、风险控制止损策略
def buy_sell_factors_pre_atr_nstop(symbols):
    buy_factors = [{'xd': 60, 'class': AbuFactorBuyBreak}, {'xd': 42, 'class': AbuFactorBuyBreak}]
    sell_factor1 = {'xd': 120, 'class': AbuFactorSellBreak}
    # 趋势跟踪策略止盈要大于止损设置值，这里0.5，3.0
    sell_factor2 = {'stop_loss_n': 0.5, 'stop_win_n': 3.0,
                    'class': AbuFactorAtrNStop}
    # 暴跌止损卖出因子形成dict
    sell_factor3 = {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.0}

    sell_factors = [sell_factor1, sell_factor2, sell_factor3]
    benchmark = AbuBenchmark()
    capital = AbuCapital(1000000, benchmark)

    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(symbols, benchmark, buy_factors,
                                                                              sell_factors, capital, show=True)
    if orders_pd is not None:
        print("orders_pd {}".format(orders_pd.tail(10)))


# review date:2023-03-29 周三 22:50
# review ：3、利润保护止盈策略
def buy_sell_factors_close_atr_nstop(symbols):
    buy_factors = [{'xd': 60, 'class': AbuFactorBuyBreak}, {'xd': 42, 'class': AbuFactorBuyBreak}]
    sell_factor1 = {'xd': 120, 'class': AbuFactorSellBreak}
    # 趋势跟踪策略止盈要大于止损设置值，这里0.5，3.0
    sell_factor2 = {'stop_loss_n': 0.5, 'stop_win_n': 3.0,
                    'class': AbuFactorAtrNStop}
    # 暴跌止损卖出因子形成dict
    sell_factor3 = {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.0}

    # 保护止盈卖出因子组成dict
    sell_factor4 = {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5}

    sell_factors = [sell_factor1, sell_factor2, sell_factor3, sell_factor4]
    benchmark = AbuBenchmark()
    capital = AbuCapital(1000000, benchmark)

    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(symbols, benchmark, buy_factors,
                                                                              sell_factors, capital, show=True)
    if orders_pd is not None:
        print("orders_pd {}".format(orders_pd.tail(10)))


def get_data_by_symbols(symbol, n_folds=2):
    data = ABuSymbolPd.make_kl_df(symbol, EMarketDataSplitMode.E_DATA_SPLIT_SE, n_folds)
    if data is not None:
        print("data is {}".format(data.tail()))


if __name__ == '__main__':
    # symbol = "hk09988"
    # get_data_by_symbols(symbol, 5)
    symbols = ['hk00700', 'hk03690']
    symbols = ['hk09988']
    symbols = ['hk03690']
    buy_sell_factors_test(symbols)
    # # buy_sell_factors_atr_nstop(symbols)
    # # buy_sell_factors_pre_atr_nstop(symbols)
    # buy_sell_factors_close_atr_nstop(symbols)
