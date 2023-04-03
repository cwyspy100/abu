# -*- encoding:utf-8-*-


from abupy import AbuFactorAtrNStop
from abupy import ABuPickTimeExecute, AbuBenchmark, AbuCapital
from abupy import AbuFactorBuyBreak, AbuFactorSellBreak, EMarketDataFetchMode, AbuFactorPreAtrNStop, \
    AbuFactorCloseAtrNStop
from abupy import AbuSlippageBuyBase, slippage, AbuSlippageBuyMean, AbuMetricsBase
import abupy
import numpy as np

abupy.env.disable_example_env_ipython()
abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_NORMAL

# REVIEW: 2023/3/30 下午3:22
# REVIEW:
#  这里四个策略对美团基本上没有任何作用,自定义滑点类的实现



# REVIEW date:2023-04-3 周一 23:29
# REVIEW ：1、参考 sample_811，sample_812， sample_813

# 利润保护止盈策略和滑点策略配置，手续费
def buy_sell_close_atr_nstop_slippage_commission(symbols):
    # buy_factors 60日向上突破，42日向上突破两个因子
    buy_factors = [{'slippage': AbuSlippageBuyMean, 'xd': 60,
                    'class': AbuFactorBuyBreak},
                   {'xd': 42, 'class': AbuFactorBuyBreak}]

    # 使用120天向下突破为卖出信号
    sell_factor1 = {'xd': 42, 'class': AbuFactorSellBreak}
    # 趋势跟踪策略止盈要大于止损设置值，这里0.5，3.0

    sell_factor2 = {'stop_loss_n': 0.5, 'stop_win_n': 3.0,
                    'class': AbuFactorAtrNStop}

    # 暴跌止损卖出因子形成dict
    sell_factor3 = {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.0}

    # 保护止盈卖出因子组成dict
    sell_factor4 = {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5}

    # 构造一个字典key='buy_commission_func', value=自定义的手续费方法函数
    commission_dict = {'buy_commission_func': calc_commission_us, 'sell_commission_func': calc_commission_us}

    # 两个卖出因子策略并行同时生效
    sell_factors = [sell_factor1, sell_factor2, sell_factor3, sell_factor4]
    benchmark = AbuBenchmark(n_folds=3)
    capital = AbuCapital(1000000, benchmark, user_commission_dict=commission_dict)
    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(symbols,
                                                                              benchmark,
                                                                              buy_factors,
                                                                              sell_factors,
                                                                              capital, show=True)
    if orders_pd is not None:
        print('orders_pd {}'.format(orders_pd))
        print('commission_pd {}'.format(capital.commission.commission_df))




# REVIEW date:2023-04-3 周一 23:30
# REVIEW ：2、参考sample_814

# 利润保护止盈策略和滑点策略配置，手续费
def buy_sell_close_atr_nstop_slippage_commission_metric(symbols, show=True):
    # buy_factors 60日向上突破，42日向上突破两个因子
    buy_factors = [{'slippage': AbuSlippageBuyMean, 'xd': 60,
                    'class': AbuFactorBuyBreak},
                   {'xd': 42, 'class': AbuFactorBuyBreak}]

    # 使用120天向下突破为卖出信号
    sell_factor1 = {'xd': 60, 'class': AbuFactorSellBreak}
    # 趋势跟踪策略止盈要大于止损设置值，这里0.5，3.0

    sell_factor2 = {'stop_loss_n': 0.5, 'stop_win_n': 3.0,
                    'class': AbuFactorAtrNStop}

    # 暴跌止损卖出因子形成dict
    sell_factor3 = {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.0}

    # 保护止盈卖出因子组成dict
    sell_factor4 = {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5}

    # 构造一个字典key='buy_commission_func', value=自定义的手续费方法函数
    commission_dict = {'buy_commission_func': calc_commission_us, 'sell_commission_func': calc_commission_us}

    # 两个卖出因子策略并行同时生效
    sell_factors = [sell_factor1, sell_factor2, sell_factor3, sell_factor4]
    benchmark = AbuBenchmark(n_folds=3)
    capital = AbuCapital(1000000, benchmark, user_commission_dict=commission_dict)
    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(symbols,
                                                                              benchmark,
                                                                              buy_factors,
                                                                              sell_factors,
                                                                              capital, show=True)


    metrics = AbuMetricsBase(orders_pd, action_pd, capital, benchmark)
    metrics.fit_metrics()
    if show:
        print('orders_pd[:10]:\n', orders_pd[:10].filter(
            ['symbol', 'buy_price', 'buy_cnt', 'buy_factor', 'buy_pos', 'sell_date', 'sell_type_extra', 'sell_type',
             'profit']))
        print('action_pd[:10]:\n', action_pd[:10])
        metrics.plot_returns_cmp(only_show_returns=True)




def calc_commission_us2(trade_cnt, price):
    """
        手续费统一7美元
    """
    return 7


# 定义手续费
def calc_commission_us(trade_cnt, price):
    """
    美股计算交易费用：每股0.01，最低消费2.99
    :param trade_cnt: 交易的股数（int）
    :param price: 每股的价格（美元）（暂不使用，只是保持接口统一）
    :return: 计算结果手续费
    """
    # 每股手续费0.01
    commission = trade_cnt * 0.01
    if commission < 2.99:
        # 最低消费2.99
        commission = 2.99
    return commission


    # get_hk_data('hk00700')
    # # 获取美团的最近的数据
    # get_hk_data('hk03690')
    # get_hk_data('hk01024')
    # get_hk_data('hk02618')
    # get_hk_data('hk01810')
    # get_hk_data('hk06160')
    # get_hk_data('hk06618')

if __name__ == '__main__':
    # symbols = ['hk03690', 'hk01024', 'hk02618', 'hk01810', 'hk06160', 'hk06618', 'hk00700']
    symbols = ['hk01024']
    # buy_sell_atr_nstop(symbols)
    # buy_sell_pre_atr_nstop(symbols)
    # buy_sell_close_atr_nstop_slippage(symbols)
    # buy_sell_close_atr_nstop_slippage_commission(symbols)
    buy_sell_close_atr_nstop_slippage_commission_metric(symbols)
