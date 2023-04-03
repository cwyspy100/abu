# -*- encoding:utf-8 -*-

import abupy
from abupy import ABuSymbolPd, EMarketDataFetchMode
from abupy import AbuBenchmark, AbuCapital, AbuFactorBuyBreak, ABuPickTimeExecute, AbuFactorSellBreak, EMarketTargetType

abupy.env.disable_example_env_ipython()
abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_NORMAL


# REVIEW: 2023/3/29 上午10:03
# REVIEW:
#  今天目标：
#  1、获取美团的近两年数据：
#  1.1、先从usJD来获取数据做测试，获取jd数据失败
#  1.2、获取腾讯和美团，最近两年的数据，成功，将获取数据改为本地获取，可以直接做本地测试。
#  2、对美团的数据执行择时策略


# print(abupy.env.enable_example_env_ipython())
# print(ABuSymbolPd.make_kl_df('usJD') is None)
# abupy.env.disable_example_env_ipython()
# us_JD = ABuSymbolPd.make_kl_df('usJD')
# # abupy.env.enable_example_env_ipython()
# tail = None
# if us_JD is not None:
#     tail = us_JD.tail()
# print(tail)

# 获取tsla最近两年数据
def get_tsla_data():
    abupy.env.disable_example_env_ipython()
    abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_FORCE_NET
    # us_Tsla = ABuSymbolPd.make_kl_df('usTsla', start='2023-01-01', end='2023-03-29')
    # us_Tsla = ABuSymbolPd.make_kl_df('usTsla', n_folds=1)
    us_Tsla = ABuSymbolPd.make_kl_df('usTSLA')
    tsla_tail = None
    if us_Tsla is not None:
        tsla_tail = us_Tsla.tail()
        print(tsla_tail)


# 获取香港股票数据，只需要使用相应的股票代码
def get_hk_data(symbol):
    abupy.env.disable_example_env_ipython()
    abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_FORCE_NET
    # abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_FORCE_LOCAL
    # us_Tsla = ABuSymbolPd.make_kl_df('usTsla', start='2023-01-01', end='2023-03-29')
    data = ABuSymbolPd.make_kl_df(symbol, n_folds=5)
    # data = ABuSymbolPd.make_kl_df(symbol)
    data_tail = None
    if data is not None:
        data_tail = data.tail()
        print('symbol  {}'.format(data_tail))


def buy_break(symbols):
    buy_factors = [{'xd': 60, 'class': AbuFactorBuyBreak}, {'xd': 40, 'class': AbuFactorBuyBreak}]
    benchmark = AbuBenchmark(n_folds=4)
    capital = AbuCapital(1000000, benchmark)
    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(symbols, benchmark, buy_factors, None,
                                                                              capital, show=True)
    print('orders_pd {}'.format(orders_pd.tail()))


def buy_sell_break(symbols):
    buy_factors = [{'xd': 60, 'class': AbuFactorBuyBreak}, {'xd': 40, 'class': AbuFactorBuyBreak}]
    sell_factors = [{'xd': 120, 'class': AbuFactorSellBreak}]
    benchmark = AbuBenchmark(n_folds=4)
    capital = AbuCapital(1000000, benchmark)
    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(symbols, benchmark, buy_factors,
                                                                              sell_factors,
                                                                      capital, show=True)
    if orders_pd is not None:
        print('orders_pd {}'.format(orders_pd.tail()))


if __name__ == '__main__':
    # get_tsla_data()
    abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_FORCE_NET
    abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_HK


    # # 获取腾讯的最近的数据
    # get_hk_data('hk00700')
    # # 获取美团的最近的数据
    get_hk_data('hk03690')
    # get_hk_data('hk01024')
    # get_hk_data('hk02618')
    # get_hk_data('hk01810')
    # get_hk_data('hk06160')
    # get_hk_data('hk06618')
    symbols = ['hk06618']
    # symbols = ['usTSLA']
    # abupy.env.enable_example_env_ipython()
    # test_buy_break(symbols)
    # buy_sell_break(symbols)
