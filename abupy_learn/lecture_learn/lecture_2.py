# -*- encoding:utf-8-*-


from abupy import AbuFactorAtrNStop
from abupy import ABuPickTimeExecute, AbuBenchmark, AbuCapital
from abupy import AbuFactorBuyBreak, AbuFactorSellBreak, EMarketDataFetchMode, AbuFactorPreAtrNStop, AbuFactorCloseAtrNStop
import abupy

abupy.env.disable_example_env_ipython()
abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_NORMAL

# REVIEW: 2023/3/30 下午3:22
# REVIEW:
#  这里四个策略对美团基本上没有任何作用


# 基本止盈止损策略
def buy_sell_atr_nstop(symbols):
    # buy_factors 60日向上突破，42日向上突破两个因子
    buy_factors = [{'xd': 60, 'class': AbuFactorBuyBreak},
                   {'xd': 42, 'class': AbuFactorBuyBreak}]
    # 使用120天向下突破为卖出信号
    sell_factor1 = {'xd': 120, 'class': AbuFactorSellBreak}
    # 趋势跟踪策略止盈要大于止损设置值，这里0.5，3.0

    sell_factor2 = {'stop_loss_n': 0.5, 'stop_win_n': 3.0,
                    'class': AbuFactorAtrNStop}

    # 两个卖出因子策略并行同时生效
    sell_factors = [sell_factor1, sell_factor2]
    benchmark = AbuBenchmark(n_folds=4)
    capital = AbuCapital(1000000, benchmark)
    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(symbols,
                                                                              benchmark,
                                                                              buy_factors,
                                                                              sell_factors,
                                                                              capital, show=False)
    if orders_pd is not None:
        print('orders_pd {}'.format(orders_pd.tail(10)))


# 风险控制止损策略
def buy_sell_pre_atr_nstop(symbols):
    # buy_factors 60日向上突破，42日向上突破两个因子
    buy_factors = [{'xd': 60, 'class': AbuFactorBuyBreak},
                   {'xd': 42, 'class': AbuFactorBuyBreak}]
    # 使用120天向下突破为卖出信号
    sell_factor1 = {'xd': 120, 'class': AbuFactorSellBreak}
    # 趋势跟踪策略止盈要大于止损设置值，这里0.5，3.0

    sell_factor2 = {'stop_loss_n': 0.5, 'stop_win_n': 3.0,
                    'class': AbuFactorAtrNStop}

    # 暴跌止损卖出因子形成dict
    sell_factor3 = {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.0}

    # 两个卖出因子策略并行同时生效
    sell_factors = [sell_factor1, sell_factor2, sell_factor3]
    benchmark = AbuBenchmark(n_folds=4)
    capital = AbuCapital(1000000, benchmark)
    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(symbols,
                                                                              benchmark,
                                                                              buy_factors,
                                                                              sell_factors,
                                                                              capital, show=False)
    if orders_pd is not None:
        print('orders_pd {}'.format(orders_pd.tail(10)))



# 利润保护止盈策略
def buy_sell_close_atr_nstop(symbols):
    # buy_factors 60日向上突破，42日向上突破两个因子
    buy_factors = [{'xd': 60, 'class': AbuFactorBuyBreak},
                   {'xd': 42, 'class': AbuFactorBuyBreak}]
    # 使用120天向下突破为卖出信号
    sell_factor1 = {'xd': 120, 'class': AbuFactorSellBreak}
    # 趋势跟踪策略止盈要大于止损设置值，这里0.5，3.0

    sell_factor2 = {'stop_loss_n': 0.5, 'stop_win_n': 3.0,
                    'class': AbuFactorAtrNStop}

    # 暴跌止损卖出因子形成dict
    sell_factor3 = {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.0}

    # 保护止盈卖出因子组成dict
    sell_factor4 = {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5}

    # 两个卖出因子策略并行同时生效
    sell_factors = [sell_factor1, sell_factor2, sell_factor3, sell_factor4]
    benchmark = AbuBenchmark(n_folds=4)
    capital = AbuCapital(1000000, benchmark)
    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(symbols,
                                                                              benchmark,
                                                                              buy_factors,
                                                                              sell_factors,
                                                                              capital, show=False)
    if orders_pd is not None:
        print('orders_pd {}'.format(orders_pd.tail(10)))


if __name__ == '__main__':
    symbols = ['hk03690']
    # buy_sell_atr_nstop(symbols)
    # buy_sell_pre_atr_nstop(symbols)
    buy_sell_close_atr_nstop(symbols)
