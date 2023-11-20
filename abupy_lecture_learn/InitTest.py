#  -*- encoding:utf-8 -*-


import abupy
from abupy import ABuSymbolPd
abupy.env.enable_example_env_ipython()

if __name__ == '__main__':
    # print(ABuSymbolPd.make_kl_df('usJD') is None)
    # # abupy.env.disable_example_env_ipython()
    # # abupy.env.g_market_source = abupy.env.EMarketSourceType.E_MARKET_SOURCE_tx
    # # abupy.env.g_data_cache_type = abupy.env.EDataCacheType.E_DATA_CACHE_CSV
    # us_jd = ABuSymbolPd.make_kl_df('usJD')
    #
    #
    #
    # abupy.env.enable_example_env_ipython()
    # tail = None
    # if us_jd is not None:
    #     tail = us_jd.tail()
    # tail
    # print(us_jd)

    # print(ABuSymbolPd.make_kl_df('jd0').tail())



    import pandas as pd
    import numpy as np
    # import matplotlib.pyplot as plt
    #
    # abupy.env.disable_example_env_ipython()
    # abupy.env.g_market_source = abupy.env.EMarketSourceType.E_MARKET_SOURCE_tx
    # abupy.env.g_market_target = abupy.env.EMarketTargetType.E_MARKET_TARGET_CN
    #
    # kl_pd = ABuSymbolPd.make_kl_df('002786', n_folds=2)
    # train_kl = kl_pd[:243]
    # test_kl = kl_pd[243:]
    # # 数据展示在下面
    # tmp_df = pd.DataFrame(
    #     np.array([train_kl.close.values, test_kl.close.values]).T,
    #     columns=['train', 'test']
    # )
    # tmp_df[['train', 'test']].plot(subplots=True, grid=True, figsize=(14, 7))
    # plt.show()

    N1 = 42
    N2 = 21
    demo_list = np.array([1, 2, 1, 1, 100, 1000])
    # s = pd.Series(demo_list)
    # l = s.rolling(window=3, min_periods=5).max()
    # print(l)

    print(pd.Series(demo_list).rolling(window=3).max())
