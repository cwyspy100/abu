# -*- encoding:utf-8 -*-

import abupy
from abupy import EMarketDataFetchMode, EMarketTargetType, ABuSymbolPd


def get_us_stock_pool_data(us_choice_stock):
    abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_FORCE_NET
    abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_US

    get_stock_data(us_choice_stock)


def get_hk_stock_pool_data(hk_choice_sotck):
    abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_NORMAL
    abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_HK
    get_stock_data(hk_choice_sotck)


def get_cn_stock_pool_data(cn_choice_sotck):
    abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_NORMAL
    abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_CN
    get_stock_data(cn_choice_sotck)



def get_stock_data(stock_pool):
    for stock in stock_pool:
        data = ABuSymbolPd.make_kl_df(stock, n_folds=2)
        if data is not None:
            # data_tail = data.tail()
            print('symbol {} data is ready'.format(stock))
        else:
            print('symbol {} data is none'.format(stock))


if __name__ == '__main__':
    # 获取美股股票池市场数据
    # us_choice_stock = ["usTSLA"]
    # get_us_stock_pool_data(us_choice_stock)

    # 获取港股股票池市场数据
    print("======================开始获取港股票数据=============================")
    hk_choice_stock = ['hk03690', 'hk01024', 'hk02618', 'hk01810', 'hk06160', 'hk06618', 'hk00700']
    get_hk_stock_pool_data(hk_choice_stock)

    # 获取A股股票池市场数据
    print("======================开始获取A股票数据=============================")
    # 科大讯飞(002230)
    # 东方财富(300059)
    # 同仁堂(600085),
    # 招商银行(600036)
    # 山西汾酒(600809)
    # 万科A(000002)
    # 比亚迪(002594)
    # 上证指数(sh000001)
    cn_choice_stock = ['002230', '300059', '600085', '600036', '600809', '000002', '002594', 'sh000001']
    get_cn_stock_pool_data(cn_choice_stock)

