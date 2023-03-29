# -*- encoding:utf-8 -*-


from abupy import AbuFactorBuyXD, BuyCallMixin

class AbuFactorBuyBreak1(AbuFactorBuyXD, BuyCallMixin):

    def fit_day(self, today):
        if today.close == self.xd_kl.close.max():
            return self.buy_tomorrow()
        return None


if __name__ == '__main__':
    from abupy import AbuBenchmark
    from abupy import AbuCapital
    from abupy import ABuPickTimeExecute
    from abupy import ABuSymbolPd
    from abupy import EMarketSourceType
    import abupy
    # 本地有usTSLA数据直接使用沙箱环境
    abupy.env.enable_example_env_ipython()
    us_tsla = ABuSymbolPd.make_kl_df('usTSLA')
    tail = None
    if us_tsla is not None:
        tail = us_tsla.tail()
    tail
    print(tail)

    # 使用外部数据,百度数据源无法使用,切换为腾讯
    print(abupy.env.g_market_source)
    abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_sn_us
    print(abupy.env.g_market_source)
    us_jd = ABuSymbolPd.make_kl_df('usTSLA')
    abupy.env.disable_example_env_ipython()
    tail = None
    if us_jd is not None:
        tail = us_jd.tail()
    tail
    print(tail)




    buy_factors = [{'xd':60, 'class':AbuFactorBuyBreak1},{'xd':60, 'class':AbuFactorBuyBreak1}]
    benmark = AbuBenchmark()
    captial = AbuCapital(1000000, benmark)
    orders_pd, action_pd, _= ABuPickTimeExecute.do_symbols_with_same_factors(['usTSLA'], benmark, captial, buy_factors, None, captial, show=True)
