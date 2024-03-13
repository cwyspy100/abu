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

# 使用沙盒数据，目的是和书中一样的数据环境
abupy.env.enable_example_env_ipython()
from abupy import AbuFactorAtrNStop, AbuFactorPreAtrNStop, AbuFactorCloseAtrNStop, AbuFactorBuyBreak
from abupy import abu, EMarketTargetType, AbuMetricsBase, ABuMarketDrawing, ABuProgress, ABuSymbolPd

# abupy量化环境设置为A股
abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_CN
from abupy import slippage
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
    choice_symbols = ['002230', '300104', '300059', '601766', '600085', '600036', '600809', '000002', '002594', '002739']

    # choice_symbols = ['000001', '000002']

    # 设置初始资金数
    read_cash = 1000000

    # 买入因子依然延用向上突破因子
    buy_factors = [{'xd': 60, 'class': AbuFactorBuyBreak},
                   {'xd': 42, 'class': AbuFactorBuyBreak}]

    # 卖出因子继续使用上一节使用的因子
    sell_factors = [
        {'stop_loss_n': 1.0, 'stop_win_n': 3.0,
         'class': AbuFactorAtrNStop},
        {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.5},
        {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5}
    ]

    # 使用run_loop_back运行策略
    abu_result_tuple, kl_pd_manger = abu.run_loop_back(read_cash,
                                                       buy_factors,
                                                       sell_factors,

                                                       n_folds=6,
                                                       choice_symbols=choice_symbols)
    ABuProgress.clear_output()
    # metrics = AbuMetricsBase(*abu_result_tuple)
    # metrics.fit_metrics()
    AbuMetricsBase.show_general(*abu_result_tuple, only_show_returns=True)

    # orders_pd = abu_result_tuple.orders_pd
    # ABuMarketDrawing.plot_candle_from_order(orders_pd)




if __name__ == "__main__":
    execute_stock_a_back_test()
