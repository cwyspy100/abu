# -*- encoding:utf-8 -*-
"""
    买入择时示例因子：动态自适应双均线策略
"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

import seaborn as sns
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')
sns.set_context(rc={'figure.figsize': (14, 7)})

import abupy

import numpy as np

from abupy.FactorBuyBu.ABuFactorBuyBase import AbuFactorBuyXD, BuyCallMixin
from abupy.IndicatorBu.ABuNDMa import calc_ma_from_prices
from abupy.CoreBu.ABuPdHelper import pd_resample
from abupy.TLineBu.ABuTL import AbuTLine
from abupy import AbuPickRegressAngMinMax
from abupy import  AbuBenchmark, AbuCapital, AbuKLManager, ABuPickStockExecute, ABuRegUtil
from learn_python.ABuPickRegressAng import AbuPickRegressAng

# 使用沙盒数据，目的是和书中一样的数据环境
abupy.env.enable_example_env_ipython()

__author__ = '阿布'
__weixin__ = 'abu_quant'




stock_pickers = [{'class': AbuPickRegressAng,
                      'threshold_ang_min': 0.0, 'threshold_ang_max': 100.0,
                      'reversed': False}]

choice_symbols = ['usNOAH', 'usSFUN', 'usBIDU', 'usAAPL', 'usGOOG',
                  'usTSLA', 'usWUBA', 'usVIPS']
benchmark = AbuBenchmark()
capital = AbuCapital(1000000, benchmark)
kl_pd_manager = AbuKLManager(benchmark, capital)

print('ABuPickStockExecute.do_pick_stock_work:\n', ABuPickStockExecute.do_pick_stock_work(choice_symbols, benchmark,
                                                                                          capital, stock_pickers))

# kl_pd_sfun = kl_pd_manager.get_pick_stock_kl_pd('usSFUN')
# print('sfun 选股周期内角度={}'.format(round(ABuRegUtil.calc_regress_deg(kl_pd_sfun.close), 3)))
#
# kl_pd_stsla = kl_pd_manager.get_pick_stock_kl_pd('usTSLA')
# print('usTSLA 选股周期内角度={}'.format(round(ABuRegUtil.calc_regress_deg(kl_pd_stsla.close), 3)))



