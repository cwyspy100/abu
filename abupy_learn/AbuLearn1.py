# -*- encoding:utf8   -*-

from abupy import AbuBenchmark
from abupy import AbuCapital
from abupy import AbuFactorBuyBreak
from abupy import ABuPickTimeExecute
import abupy
abupy.env.enable_example_env_ipython()


if __name__ == '__main__':
    # buy_factors 60日向上突破，42日向上突破两个因子
    buy_factors = [{'xd': 60, 'class': AbuFactorBuyBreak},
                   {'xd': 42, 'class': AbuFactorBuyBreak}]
    buy_factors = [{'xd': 42, 'class': AbuFactorBuyBreak}]
    benchmark = AbuBenchmark()
    capital = AbuCapital(1000000, benchmark)

    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(['usTSLA'],
                                                                              benchmark,
                                                                              buy_factors,
                                                                              None,
                                                                              capital, show=True)
