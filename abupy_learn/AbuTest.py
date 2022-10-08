import abupy
from abupy import ABuSymbolPd

if __name__ == '__main__':
    # abupy.env.enable_example_env_ipython()
    # print(ABuSymbolPd.make_kl_df('usJD') is None)
    #
    # # todo 关闭本地环境，目前不能请求外部数据
    # abupy.env.disable_example_env_ipython()
    # us_jd = ABuSymbolPd.make_kl_df('usJD')
    #
    # tail = None
    # if us_jd is not None:
    #     tail = us_jd.tail()
    # tail
    #
    # print(tail)



    from abupy import AbuFactorBuyBreak, AbuFactorSellBreak
    from abupy import AbuFactorAtrNStop, AbuFactorPreAtrNStop, AbuFactorCloseAtrNStop
    from abupy import ABuPickTimeExecute, AbuBenchmark, AbuCapital
    from abupy_learn.AbuSlippageBuyMean2 import AbuSlippageBuyMean2
    abupy.env.enable_example_env_ipython()

    # buy_factors 60日向上突破，42日向上突破两个因子
    buy_factors = [{'xd': 60, 'class': AbuFactorBuyBreak},
                   {'xd': 42, 'class': AbuFactorBuyBreak}]
    # 四个卖出因子同时并行生效
    sell_factors = [
        {
            'xd': 120,
            'class': AbuFactorSellBreak
        },
        {
            'stop_loss_n': 0.5,
            'stop_win_n': 3.0,
            'class': AbuFactorAtrNStop
        },
        {
            'class': AbuFactorPreAtrNStop,
            'pre_atr_n': 1.0
        },
        {
            'class': AbuFactorCloseAtrNStop,
            'close_atr_n': 1.5
        }]
    benchmark = AbuBenchmark()
    capital = AbuCapital(1000000, benchmark)

    # 针对60使用AbuSlippageBuyMean2
    buy_factors2 = [{'slippage': AbuSlippageBuyMean2, 'xd': 60,
                     'class': AbuFactorBuyBreak},
                    {'xd': 42, 'class': AbuFactorBuyBreak}]
    capital = AbuCapital(1000000, benchmark)
    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(['usTSLA'],
                                                                              benchmark,
                                                                              buy_factors2,
                                                                              sell_factors,
                                                                              capital,
                                                                              show=True)