#  -*- enconding: utf9 -*-
import os

os.system('cls')

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
# import os
# import sys
# # 使用insert 0即只使用github，避免交叉使用了pip安装的abupy，导致的版本不一致问题
# sys.path.insert(0, os.path.abspath('../'))
import abupy
import datetime

# 使用沙盒数据，目的是和书中一样的数据环境
# abupy.env.enable_example_env_ipython()
abupy.env.disable_example_env_ipython()
from abupy import AbuFactorAtrNStop, AbuFactorPreAtrNStop, AbuFactorCloseAtrNStop, AbuFactorBuyBreak, AbuDoubleMaBuy
from abupy import abu, EMarketTargetType, AbuMetricsBase, ABuMarketDrawing, ABuProgress, ABuSymbolPd, EMarketSourceType

# abupy量化环境设置为A股
abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_CN
abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_tx
from abupy import slippage

from learn_python.ABuFactorBuyMean import AbuFactorBuyMean
from learn_python.ABuFactorSellMean import AbuFactorSellMean
from learn_python.ABuFactorBuyEMA import AbuFactorBuyEMA

# 开启针对非集合竞价阶段的涨停，滑点买入价格以高概率在接近涨停的价格买入
slippage.sbb.g_enable_limit_up = True
# 将集合竞价阶段的涨停买入成功概率设置为0，如果设置为0.2即20%概率成功买入
slippage.sbb.g_pre_limit_up_rate = 0
# 开启针对非集合竞价阶段的跌停，滑点卖出价格以高概率在接近跌停的价格卖出
slippage.ssb.g_enable_limit_down = True
# 将集合竞价阶段的跌停卖出成功概率设置为0, 如果设置为0.2即20%概率成功卖出
slippage.ssb.g_pre_limit_down_rate = 0


def execute_stock_a_back_test():
    # 择时股票池
    # choice_symbols = ['002230', '300104', '300059', '601766', '600085', '600036', '600809', '000002', '002594',
    #                   '002739']

    # choice_symbols = ['300104']
    choice_symbols_pd = pd.read_csv('../todolist/stock_a_pool.csv')
    choice_symbols = choice_symbols_pd['symbol']

    # 设置初始资金数
    read_cash = 1000000

    # 买入因子依然延用向上突破因子
    buy_factors = [
        # {'xd': 60, 'class': AbuFactorBuyBreak},
        # {'xd': 42, 'class': AbuFactorBuyBreak},
        # {'fast': 5, 'slow': 60, 'class': AbuDoubleMaBuy},
        # {'xd': 120, 'class': AbuFactorBuyMean},
        {'xd': 120, 'class': AbuFactorBuyEMA}
    ]

    # 卖出因子继续使用上一节使用的因子
    sell_factors = [
        {'stop_loss_n': 1.0, 'stop_win_n': 3.0, 'class': AbuFactorAtrNStop},
        {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.5},
        {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5},
        # {'xd': 120, 'class': AbuFactorSellMean}
    ]

    # 使用run_loop_back运行策略
    abu_result_tuple, kl_pd_manger = abu.run_loop_back(read_cash,
                                                       buy_factors,
                                                       sell_factors,
                                                       n_folds=1,
                                                       choice_symbols=choice_symbols)
    ABuProgress.clear_output()
    metrics = AbuMetricsBase(*abu_result_tuple)
    metrics.fit_metrics()
    AbuMetricsBase.show_general(*abu_result_tuple, only_show_returns=True)

    orders_pd = abu_result_tuple.orders_pd
    orders_pd.to_csv('../todolist/stock_a_orders.csv')
    actions_pd = abu_result_tuple.action_pd
    actions_pd.to_csv('../todolist/stock_a_actions.csv')

    save_backtest_result(metrics)

    # ABuMarketDrawing.plot_candle_from_order(orders_pd)


def save_backtest_result(metrics):
    result = []
    result1 = '买入后卖出的交易数量:{}'.format(metrics.order_has_ret.shape[0])
    result2 = '买入后尚未卖出的交易数量:{}'.format(metrics.order_keep.shape[0])
    result3 = '胜率:{:.4f}%'.format(metrics.win_rate * 100)
    result4 = '平均获利期望:{:.4f}%'.format(metrics.gains_mean * 100)
    result5 = '平均亏损期望:{:.4f}%'.format(metrics.losses_mean * 100)
    result6 = '盈亏比:{:.4f}'.format(metrics.win_loss_profit_rate)
    result7 = '策略收益: {:.4f}%'.format(metrics.algorithm_period_returns * 100)
    result8 = '基准收益: {:.4f}%'.format(metrics.benchmark_period_returns * 100)
    result9 = '策略年化收益: {:.4f}%'.format(metrics.algorithm_annualized_returns * 100)
    result10 = '基准年化收益: {:.4f}%'.format(metrics.benchmark_annualized_returns * 100)
    result11 = '策略买入成交比例:{:.4f}%'.format(metrics.buy_deal_rate * 100)
    result12 = '策略资金利用率比例:{:.4f}%'.format(metrics.cash_utilization * 100)
    result13 = '策略共执行{}个交易日'.format(metrics.num_trading_days)
    today = datetime.date.today()
    result.append("------------" + str(today) + "-------------非动态均线----------------")
    result.append(result1)
    result.append(result2)
    result.append(result3)
    result.append(result4)
    result.append(result5)
    result.append(result6)
    result.append(result7)
    result.append(result8)
    result.append(result9)
    result.append(result10)
    result.append(result11)
    result.append(result12)
    result.append(result13)
    string = "\n"
    with open('../todolist/stock_a_pool_backtest.txt', 'a', encoding='utf-8') as f:
        f.write(string.join(result))


if __name__ == "__main__":
    execute_stock_a_back_test()
    # stock_a_pd = pd.read_csv('stock_a_pool.csv')
    # print(stock_a_pd['symbol'])
