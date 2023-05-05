import abupy
from abupy import AbuPickStockWorker
from abupy import AbuBenchmark, AbuCapital, AbuKLManager, AbuPickRegressAngMinMax, ABuRegUtil, EMarketTargetType, \
    EMarketDataFetchMode

# abupy.env.enable_example_env_ipython()
abupy.env.disable_example_env_ipython()
abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_HK


def select_stocks(choice_symbols):
    # 选股条件threshold_ang_min=0.0, 即要求股票走势为向上上升趋势
    stock_pickers = [{'class': AbuPickRegressAngMinMax,
                      'threshold_ang_min': 0.0, 'threshold_ang_max': 50.0, 'reversed': False}]

    benchmark = AbuBenchmark()
    capital = AbuCapital(1000000, benchmark)
    kl_pd_manger = AbuKLManager(benchmark, capital)
    stock_pick = AbuPickStockWorker(capital, benchmark, kl_pd_manger,
                                    choice_symbols=choice_symbols,
                                    stock_pickers=stock_pickers)
    stock_pick.fit()
    # 打印最后的选股结果
    print("select stocks result {}".format(stock_pick.choice_symbols))


def select_hk_stocks_test(symbol):
    abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_HK
    # abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_FORCE_NET

    benchmark = AbuBenchmark()
    capital = AbuCapital(1000000, benchmark)
    kl_pd_manger = AbuKLManager(benchmark, capital)
    # 从kl_pd_manger缓存中获取选股走势数据，
    # 注意get_pick_stock_kl_pd()为选股数据，get_pick_time_kl_pd()为择时
    kl_pd_noah = kl_pd_manger.get_pick_stock_kl_pd(symbol)
    # 绘制并计算角度
    deg = ABuRegUtil.calc_regress_deg(kl_pd_noah.close)
    print('symbol 选股周期内角度={}'.format(round(deg, 3)))


if __name__ == '__main__':
    # 从这几个股票里进行选股，只是为了演示方便
    # 一般的选股都会是数量比较多的情况比如全市场股票
    # choice_symbols = ['usNOAH', 'usSFUN', 'usBIDU', 'usAAPL', 'usGOOG',
    #                   'usTSLA', 'usWUBA', 'usVIPS']

    # choice_symbols = ['hk03690', 'hk01024', 'hk02618', 'hk01810', 'hk06160', 'hk06618', 'hk00700']
    # select_stocks(choice_symbols)

    symbol = 'hk03690'
    select_hk_stocks_test(symbol)
