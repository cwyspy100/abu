

import abupy
from abupy import AbuMetricsBase

from abupy import AbuFactorBuyBreak
from abupy import AbuFactorAtrNStop
from abupy import AbuFactorPreAtrNStop
from abupy import AbuFactorCloseAtrNStop

# run_loop_back等一些常用且最外层的方法定义在abu中
from abupy import abu

# 使用沙盒数据，目的是和书中一样的数据环境
abupy.env.enable_example_env_ipython()

# 设置选股因子，None为不使用选股因子
stock_pickers = None
# 买入因子依然延用向上突破因子
buy_factors = [{'xd': 60, 'class': AbuFactorBuyBreak},
               {'xd': 42, 'class': AbuFactorBuyBreak}]

# 卖出因子继续使用上一章使用的因子
sell_factors = [
    {'stop_loss_n': 1.0, 'stop_win_n': 3.0,
     'class': AbuFactorAtrNStop},
    {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.5},
    {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5}
]


def stock_american_execute(show=True):
    """
    9.1 度量的基本使用方法
    :return:
    """
    # 设置初始资金数
    read_cash = 1000000
    # 择时股票池
    choice_symbols = ['usNOAH', 'usSFUN', 'usBIDU', 'usAAPL', 'usGOOG',
                      'usTSLA', 'usWUBA', 'usVIPS']
    # 使用run_loop_back运行策略
    abu_result_tuple, kl_pd_manager = abu.run_loop_back(read_cash,
                                                        buy_factors,
                                                        sell_factors,
                                                        stock_pickers,
                                                        choice_symbols=choice_symbols, n_folds=2)
    metrics = AbuMetricsBase(*abu_result_tuple)
    metrics.show_general(*abu_result_tuple, only_show_returns=True)
    metrics.fit_metrics()
    if show:
        metrics.plot_returns_cmp()
    return metrics


if __name__ == '__main__':
    stock_american_execute(False)