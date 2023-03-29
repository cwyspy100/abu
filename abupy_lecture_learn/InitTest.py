#  -*- encoding:utf-8 -*-


import abupy
from abupy import ABuSymbolPd
abupy.env.enable_example_env_ipython()

if __name__ == '__main__':
    print(ABuSymbolPd.make_kl_df('usJD') is None)
    # abupy.env.disable_example_env_ipython()
    # abupy.env.g_market_source = abupy.env.EMarketSourceType.E_MARKET_SOURCE_tx
    # abupy.env.g_data_cache_type = abupy.env.EDataCacheType.E_DATA_CACHE_CSV
    us_jd = ABuSymbolPd.make_kl_df('usJD')



    abupy.env.enable_example_env_ipython()
    tail = None
    if us_jd is not None:
        tail = us_jd.tail()
    tail
    print(us_jd)

    # print(ABuSymbolPd.make_kl_df('jd0').tail())