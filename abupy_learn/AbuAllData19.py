# -*- encoding:utf8 -*-

import abupy
from abupy import EMarketSourceType, EDataCacheType, EMarketTargetType, EMarketDataFetchMode
from abupy import abu, ABuSymbolPd

if __name__ == '__main__':
    # abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_sn_us
    # abupy.env.g_data_cache_type = EDataCacheType.E_DATA_CACHE_CSV
    # # abu.run_kl_update(start='2020-07-01', end='2021-07-01', market=EMarketTargetType.E_MARKET_TARGET_CN, n_jobs=10)
    # abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_FORCE_LOCAL
    # print(ABuSymbolPd.make_kl_df('usTSLA').tail())
    # print(abupy.env.g_project_data_dir)

    # abupy.env.disable_example_env_ipython(
    # print(ABuSymbolPd.make_kl_df('hk00213').tail())

    from abupy import EMarketSourceType, EMarketSourceType, AbuBenchmark
    from abupy import AbuPickTimeWorker, AbuCapital, AbuKLManager
    benchmark = AbuBenchmark()
    # abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_sn_us
    abupy.env.disable_example_env_ipython()
    captial = AbuCapital(1000000, benchmark)
    kl_pd_manager = AbuKLManager(benchmark, captial)
    kl_pd = kl_pd_manager.get_pick_time_kl_pd('usFUTU')
    print(kl_pd.tail())