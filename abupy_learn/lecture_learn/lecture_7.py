import abupy
from abupy import AbuPickStockWorker
from abupy import AbuBenchmark, AbuCapital, AbuKLManager, AbuPickRegressAngMinMax, ABuRegUtil, EMarketTargetType, \
    EMarketDataFetchMode
from abupy import AbuFactorAtrNStop, AbuFactorPreAtrNStop, AbuFactorCloseAtrNStop, AbuFactorBuyBreak, AbuMetricsBase
import numpy as np

# abupy.env.enable_example_env_ipython()
abupy.env.disable_example_env_ipython()
abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_HK

# REVIEW date:2023-04-10 周一 21:55
# REVIEW ：Grid Search寻找最优参数 、
#  1、组合出更多参数
#  2、找出最优解释


stop_win_range = np.arange(2.0, 4.5, 0.5)
stop_loss_range = np.arange(0.5, 2, 0.5)

sell_atr_nstop_factor_grid = {
    'class': [AbuFactorAtrNStop],
    'stop_loss_n': stop_loss_range,
    'stop_win_n': stop_win_range
}

close_atr_range = np.arange(1.0, 4.0, 0.5)
pre_atr_range = np.arange(1.0, 3.5, 0.5)

sell_atr_pre_factor_grid = {
    'class': [AbuFactorPreAtrNStop],
    'pre_atr_n': pre_atr_range
}

sell_atr_close_factor_grid = {
    'class': [AbuFactorCloseAtrNStop],
    'close_atr_n': close_atr_range
}


def grid_list():
    """
       9.3.1 参数取值范围
       :return:
       """
    print('止盈参数stop_win_n设置范围:{}'.format(stop_win_range))
    print('止损参数stop_loss_n设置范围:{}'.format(stop_loss_range))

    print('暴跌保护止损参数pre_atr_n设置范围:{}'.format(pre_atr_range))
    print('盈利保护止盈参数close_atr_n设置范围:{}'.format(close_atr_range))


def grid_select_list(show=True):
    """
  9.3.2 参数进行排列组合
  :return:
  """

    from abupy import ABuGridHelper

    sell_factors_product = ABuGridHelper.gen_factor_grid(
        ABuGridHelper.K_GEN_FACTOR_PARAMS_SELL,
        [sell_atr_nstop_factor_grid, sell_atr_pre_factor_grid, sell_atr_close_factor_grid])

    if show:
        print('卖出因子参数共有{}种组合方式'.format(len(sell_factors_product)))
        print('卖出因子组合0形式为{}'.format(sell_factors_product[0]))

    buy_bk_factor_grid1 = {
        'class': [AbuFactorBuyBreak],
        'xd': [42]
    }

    buy_bk_factor_grid2 = {
        'class': [AbuFactorBuyBreak],
        'xd': [60]
    }

    buy_factors_product = ABuGridHelper.gen_factor_grid(
        ABuGridHelper.K_GEN_FACTOR_PARAMS_BUY, [buy_bk_factor_grid1, buy_bk_factor_grid2])

    if show:
        print('买入因子参数共有{}种组合方式'.format(len(buy_factors_product)))
        print('买入因子组合形式为{}'.format(buy_factors_product))

    return sell_factors_product, buy_factors_product


def select_stocks(choice_symbols):
    """
        9.3.3 GridSearch寻找最优参数
        :return:
        """
    from abupy import GridSearch

    read_cash = 1000000

    sell_factors_product, buy_factors_product = grid_select_list(show=False)

    grid_search = GridSearch(read_cash, choice_symbols,
                             buy_factors_product=buy_factors_product,
                             sell_factors_product=sell_factors_product)

    from abupy import ABuFileUtil
    """
        注意下面的运行耗时大约1小时多，如果所有cpu都用上的话，也可以设置n_jobs为 < cpu进程数，一边做其它的一边跑
    """
    # 运行GridSearch n_jobs=-1启动cpu个数的进程数
    scores, score_tuple_array = grid_search.fit(n_jobs=-1)

    """
        针对运行完成输出的score_tuple_array可以使用dump_pickle保存在本地，以方便修改其它验证效果。
    """
    ABuFileUtil.dump_pickle(score_tuple_array, '../gen/score_tuple_array')

    print('组合因子参数数量{}'.format(len(buy_factors_product) * len(sell_factors_product)))
    print('最终评分结果数量{}'.format(len(scores)))

    best_score_tuple_grid = grid_search.best_score_tuple_grid
    AbuMetricsBase.show_general(best_score_tuple_grid.orders_pd, best_score_tuple_grid.action_pd,
                                best_score_tuple_grid.capital, best_score_tuple_grid.benchmark)


if __name__ == '__main__':
    # 从这几个股票里进行选股，只是为了演示方便
    # 一般的选股都会是数量比较多的情况比如全市场股票
    # choice_symbols = ['usNOAH', 'usSFUN', 'usBIDU', 'usAAPL', 'usGOOG',
    #                   'usTSLA', 'usWUBA', 'usVIPS']

    # choice_symbols = ['hk03690', 'hk01024', 'hk02618', 'hk01810', 'hk06160', 'hk06618', 'hk00700']
    # select_stocks(choice_symbols)

    choice_symbols = ['hk02618']
    # grid_list()
    # grid_select_list()
    select_stocks(choice_symbols)
