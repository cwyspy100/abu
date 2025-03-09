import time

# noinspection PyUnresolvedReferences
import abu_local_env

import abupy
from abupy import ABuMarket
from abupy import AbuBenchmark
from abupy import AbuCapital
from abupy import AbuKLManager
from abupy import AbuPickRegressAngMinMax, AbuPickStockPriceMinMax, AbuPickStockByMean
from abupy import AbuPickStockWorker
from abupy import EMarketSourceType, EDataCacheType, EMarketTargetType, EMarketDataFetchMode
from abupy import abu
from abupy import ABuRegUtil
import datetime


def update_all_us_data():
    abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_sn_us
    abupy.env.g_data_cache_type = EDataCacheType.E_DATA_CACHE_CSV
    abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_US
    abu.run_kl_update(n_folds=1, market=EMarketTargetType.E_MARKET_TARGET_US, n_jobs=4)


def pick_stock_in_us_stock():
    # 要关闭沙盒数据环境，因为沙盒里就那几个股票的历史数据, 下面要随机做50个股票
    abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_tx
    abupy.env.disable_example_env_ipython()
    abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_FORCE_LOCAL
    abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_US

    # 关闭沙盒后，首先基准要从非沙盒环境换取，否则数据对不齐，无法正常运行
    choice_symbols = ABuMarket.all_symbol()

    # choice_symbols = {"sh600119"}

    # 选股条件threshold_ang_min=0.0, 即要求股票走势为向上上升趋势
    # stock_pickers = [{'class': AbuPickRegressAngMinMax,
    #                   'threshold_ang_min': 5.0, 'xd': 10, 'reversed': False}]
    stock_pickers = [
        {'class': AbuPickRegressAngMinMax, 'threshold_ang_min': 5.0, 'xd': 120, 'reversed': False},
        {'class': AbuPickStockPriceMinMax, 'threshold_price_min': 5, 'threshold_price_max': 500, 'reversed': False},
        {'class': AbuPickStockByMean, 'mean_xd': 120},
    ]

    benchmark = AbuBenchmark()
    capital = AbuCapital(1000000, benchmark)
    kl_pd_manager = AbuKLManager(benchmark, capital)
    stock_pick = AbuPickStockWorker(capital, benchmark, kl_pd_manager,
                                    choice_symbols=choice_symbols,
                                    stock_pickers=stock_pickers)
    stock_pick.fit()
    # 打印最后的选股结果
    print('stock_pick.choice_symbols:', stock_pick.choice_symbols)
    save_stock_info(stock_pick.choice_symbols, "mean")

def save_stock_info(choice_symbols, flag="all"):
    today = datetime.date.today().strftime("%Y%m%d")
    file_name = flag + "_us_out_put_"+today
    with open(file_name, "w") as file:
        for item in choice_symbols:
            file.write(str(item)+"\n")


def check_stock_in_us_stock(symbol):
    """
    验证一个股票的角度
    """
    benchmark = AbuBenchmark()
    capital = AbuCapital(1000000, benchmark)
    kl_pd_manager = AbuKLManager(benchmark, capital)
    kl_pd_noah = kl_pd_manager.get_pick_stock_kl_pd(symbol)
    if kl_pd_noah is None:
        return
    # 绘制并计算角度
    deg = ABuRegUtil.calc_regress_deg(kl_pd_noah.close)
    print('noah 选股周期内角度={}'.format(round(deg, 3)))


if __name__ == '__main__':
    start_time = time.time()
    # 1、更新所有数据
    # update_all_us_data()
    # 2、使用本地数据进行选股
    pick_stock_in_us_stock()
    # 3、验证结果
    # check_stock_in_us_stock("usFUTU")
    print("cost time {}".format(time.time() - start_time))
