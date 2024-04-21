# noinspection PyUnresolvedReferences
import abu_local_env

import abupy
from abupy import ABuMarket
from abupy import AbuBenchmark
from abupy import AbuCapital
from abupy import AbuKLManager
from abupy import AbuPickRegressAngMinMax
from abupy import AbuPickStockWorker
from abupy import EMarketSourceType, EDataCacheType, EMarketTargetType,EMarketDataFetchMode
from abupy import abu
from abupy import ABuRegUtil


def update_all_a_data():
    abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_tx
    abupy.env.g_data_cache_type = EDataCacheType.E_DATA_CACHE_CSV
    abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_CN
    abu.run_kl_update(market=EMarketTargetType.E_MARKET_TARGET_CN, n_jobs=4)



def pick_stock_in_A_stock():
    # 要关闭沙盒数据环境，因为沙盒里就那几个股票的历史数据, 下面要随机做50个股票
    abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_tx
    abupy.env.disable_example_env_ipython()
    abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_FORCE_LOCAL
    abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_CN

    # 关闭沙盒后，首先基准要从非沙盒环境换取，否则数据对不齐，无法正常运行
    choice_symbols = ABuMarket.all_symbol()

    # choice_symbols = {"sh600119"}

    # 选股条件threshold_ang_min=0.0, 即要求股票走势为向上上升趋势
    stock_pickers = [{'class': AbuPickRegressAngMinMax,
                      'threshold_ang_min': 0.0, 'reversed': False}]

    benchmark = AbuBenchmark()
    capital = AbuCapital(1000000, benchmark)
    kl_pd_manager = AbuKLManager(benchmark, capital)
    stock_pick = AbuPickStockWorker(capital, benchmark, kl_pd_manager,
                                    choice_symbols=choice_symbols,
                                    stock_pickers=stock_pickers)
    stock_pick.fit()
    # 打印最后的选股结果
    print('stock_pick.choice_symbols:', stock_pick.choice_symbols)

def check_stock_in_A_stock(symbol):
    """
    验证一个股票的角度
    """
    benchmark = AbuBenchmark()
    capital = AbuCapital(1000000, benchmark)
    kl_pd_manager = AbuKLManager(benchmark, capital)
    kl_pd_noah = kl_pd_manager.get_pick_stock_kl_pd(symbol)
    # 绘制并计算角度
    deg = ABuRegUtil.calc_regress_deg(kl_pd_noah.close)
    print('noah 选股周期内角度={}'.format(round(deg, 3)))


if __name__ == '__main__':
    # 1、更新所有数据
    # update_all_a_data()
    # 2、使用本地数据进行选股
    # pick_stock_in_A_stock()
    # 3、验证结果
    check_stock_in_A_stock("sh600449")