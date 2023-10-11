# -*- encoding:utf8 -*-

import abupy
from abupy import EMarketSourceType, EDataCacheType, EMarketTargetType, EMarketDataFetchMode
from abupy import abu, ABuSymbolPd

if __name__ == '__main__':
    abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_tx
    abupy.env.g_data_cache_type = EDataCacheType.E_DATA_CACHE_CSV
    abu.run_kl_update(start='2020-07-01', end='2021-07-01', market=EMarketTargetType.E_MARKET_TARGET_CN, n_jobs=10)
    # abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_FORCE_LOCAL
    print(ABuSymbolPd.make_kl_df('sh000003').tail())
    print(abupy.env.g_project_data_dir)