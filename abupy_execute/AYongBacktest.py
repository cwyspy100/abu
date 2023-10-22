# -*- encoding:utf-8 -*-

from abupy import AbuFactorAtrNStop, AbuFactorPreAtrNStop, AbuFactorCloseAtrNStop, AbuFactorBuyBreak
from abupy import abu, ABuFileUtil, ABuGridHelper, GridSearch, AbuBlockProgress, ABuProgress
import numpy as np
from abupy import AbuMetricsBase


def get_sell_factors():
    sell_atr_nstop_factor_grid = get_sell_atr_nstop_factors()
    sell_atr_pre_factor_grid, sell_atr_close_factor_grid = get_sell_atr_close_factor()
    sell_factors_product = ABuGridHelper.gen_factor_grid(
        ABuGridHelper.K_GEN_FACTOR_PARAMS_SELL,
        [sell_atr_nstop_factor_grid, sell_atr_pre_factor_grid, sell_atr_close_factor_grid], need_empty_sell=True)
    print('卖出因子参数共有{}种组合方式'.format(len(sell_factors_product)))
    print('卖出因子组合0: 形式为{}'.format(sell_factors_product[0]))
    return sell_factors_product


def get_sell_atr_nstop_factors():
    stop_win_range = np.arange(2.0, 4.5, 0.5)
    stop_loss_range = np.arange(0.5, 2, 0.5)

    sell_atr_nstop_factor_grid = {
        'class': [AbuFactorAtrNStop],
        'stop_loss_n': stop_loss_range,
        'stop_win_n': stop_win_range
    }

    print('AbuFactorAtrNStop止盈参数stop_win_n设置范围:{}'.format(stop_win_range))
    print('AbuFactorAtrNStop止损参数stop_loss_n设置范围:{}'.format(stop_loss_range))
    return sell_atr_nstop_factor_grid


def get_sell_atr_close_factor():
    close_atr_range = np.arange(1.0, 4.0, 0.5)
    pre_atr_range = np.arange(1.0, 3.5, 0.5)
    close_atr_range = np.arange(1.0, 2.0, 1.0)
    pre_atr_range = np.arange(1.0, 2, 1.0)

    sell_atr_pre_factor_grid = {
        'class': [AbuFactorPreAtrNStop],
        'pre_atr_n': pre_atr_range
    }

    sell_atr_close_factor_grid = {
        'class': [AbuFactorCloseAtrNStop],
        'close_atr_n': close_atr_range
    }

    print('暴跌保护止损参数pre_atr_n设置范围:{}'.format(pre_atr_range))
    print('盈利保护止盈参数close_atr_n设置范围:{}'.format(close_atr_range))

    return sell_atr_pre_factor_grid, sell_atr_close_factor_grid


def get_buy_factors():
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

    print('买入因子参数共有{}种组合方式'.format(len(buy_factors_product)))
    print('买入因子组合形式为{}'.format(buy_factors_product))
    return buy_factors_product



def execute_grid_search(choice_symbols, flag=2):
    read_cash = 1000000

    sell_factors_product = get_sell_factors()
    buy_factors_product = get_buy_factors()

    grid_search = GridSearch(read_cash, choice_symbols, buy_factors_product = buy_factors_product
                             , sell_factors_product= sell_factors_product)

    scores = None
    score_tuple_array = None

    def run_grid_search():
        global scores, score_tuple_array
        # 运行GridSearch n_jobs=-1启动cpu个数的进程数
        scores, score_tuple_array = grid_search.fit(n_jobs=-1)
        # 运行完成输出的score_tuple_array可以使用dump_pickle保存在本地，以方便之后使用
        ABuFileUtil.dump_pickle(score_tuple_array, '../gen/score_tuple_array')

    def load_score_cache():
        """有本地数据score_tuple_array后，即可以从本地缓存读取score_tuple_array"""
        global scores, score_tuple_array

        with AbuBlockProgress('load score cache'):
            score_tuple_array = ABuFileUtil.load_pickle('../gen/score_tuple_array')
            if not hasattr(grid_search, 'best_score_tuple_grid'):
                # load_pickle的grid_search没有赋予best_score_tuple_grid，这里补上
                from abupy import make_scorer, WrsmScorer
                scores = make_scorer(score_tuple_array, WrsmScorer)
                grid_search.best_score_tuple_grid = score_tuple_array[scores.index[-1]]
            print('load complete!')

    if flag == 1:
        run_grid_search()
    else:
        load_score_cache()

    best_score_tuple_grid = grid_search.best_score_tuple_grid
    AbuMetricsBase.show_general(best_score_tuple_grid.orders_pd, best_score_tuple_grid.action_pd,
                                best_score_tuple_grid.capital, best_score_tuple_grid.benchmark)





if __name__ == '__main__':
    # get_sell_atr_nstop_factors()
    # get_sell_atr_close_factor()
    # sell_factors_product = get_sell_factors()
    # buy_factors_product = get_buy_factors()
    # cn_choice_stock = ['002230', '300059', '600085', '600036', '600809', '000002', '002594', 'sh000001']
    cn_choice_stock = ['002230', '300059']
    # execute_grid_search(cn_choice_stock, flag=1)
    execute_grid_search(cn_choice_stock)
