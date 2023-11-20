import abupy
from abupy import ABuSymbolPd

if __name__ == '__main__':

    from abupy import AbuFactorBuyBreak, AbuFactorSellBreak
    from abupy import AbuFactorAtrNStop, AbuFactorPreAtrNStop, AbuFactorCloseAtrNStop
    from abupy import ABuPickTimeExecute, AbuBenchmark, AbuCapital
    from abupy_learn.AbuSlippageBuyMean2 import AbuSlippageBuyMean2
    from abupy import AbuMetricsBase, EMarketTargetType
    from abupy import AbuSlippageBuyMean
    abupy.env.disable_example_env_ipython()
    abupy.env.g_market_target =  EMarketTargetType.E_MARKET_TARGET_CN

    kl_pd = ABuSymbolPd.make_kl_df('002584', n_folds=2)
    print(kl_pd.tail())



    # buy_factors 60日向上突破，42日向上突破两个因子
    # buy_factors = [{'xd': 60, 'class': AbuFactorBuyBreak},
    #                {'xd': 42, 'class': AbuFactorBuyBreak}]
    # # 四个卖出因子同时并行生效
    # sell_factors = [
    #     {
    #         'xd': 120,
    #         'class': AbuFactorSellBreak
    #     },
    #     {
    #         'stop_loss_n': 0.5,
    #         'stop_win_n': 3.0,
    #         'class': AbuFactorAtrNStop
    #     },
    #     {
    #         'class': AbuFactorPreAtrNStop,
    #         'pre_atr_n': 1.0
    #     },
    #     {
    #         'class': AbuFactorCloseAtrNStop,
    #         'close_atr_n': 1.5
    #     }]
    # benchmark = AbuBenchmark()
    # capital = AbuCapital(1000000, benchmark)
    #
    #
    #
    #
    # # 针对60使用AbuSlippageBuyMean2
    # buy_factors2 = [{'slippage': AbuSlippageBuyMean, 'xd': 60,
    #                  'class': AbuFactorBuyBreak},
    #                 {'xd': 42, 'class': AbuFactorBuyBreak}]
    # orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(['002584'],
    #                                                                           benchmark,
    #                                                                           buy_factors2,
    #                                                                           sell_factors,
    #                                                                           capital,
    #                                                                           show=True)
    #
    #
    #
    # metrics = AbuMetricsBase(orders_pd, action_pd, capital, benchmark)
    # metrics.fit_metrics()
    # metrics.plot_returns_cmp(only_show_returns=True)

    # from abupy import AbuFactorBuyBreak
    # from abupy import AbuBenchmark
    #
    # # buy_factors 60日向上突破，42日向上突破两个因子
    # buy_factors = [{'xd': 60, 'class': AbuFactorBuyBreak},
    #                {'xd': 42, 'class': AbuFactorBuyBreak}]
    # benchmark = AbuBenchmark()
    #
    # from abupy import ABuPickTimeExecute
    #
    # sell_factor1 = {'xd': 120, 'class': AbuFactorSellBreak}
    #
    # # 只使用120天向下突破为卖出因子
    # sell_factors = [sell_factor1]
    # capital = AbuCapital(1000000, benchmark)
    # orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(
    #     ['002786'], benchmark, buy_factors, sell_factors, capital, show=True)
    #
    # from abupy import AbuMetricsBase
    #
    # metrics = AbuMetricsBase(orders_pd, action_pd, capital, benchmark)
    # metrics.fit_metrics()
    # metrics.plot_returns_cmp(only_show_returns=True)