# -*- encoding:utf-8-*-


from abupy import AbuFactorAtrNStop
from abupy import ABuPickTimeExecute, AbuBenchmark, AbuCapital
from abupy import AbuFactorBuyBreak, AbuFactorSellBreak, EMarketDataFetchMode, AbuFactorPreAtrNStop, \
    AbuFactorCloseAtrNStop
from abupy import AbuSlippageBuyBase, slippage
import abupy
import numpy as np

abupy.env.disable_example_env_ipython()
abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_NORMAL

# REVIEW: 2023/3/30 下午3:22
# REVIEW:
#  这里四个策略对美团基本上没有任何作用,自定义滑点类的实现

g_open_down_rate = 0.02


class AbuSlippageBuyMean2(AbuSlippageBuyBase):
    """示例日内滑点均价买入类"""

    @slippage.sbb.slippage_limit_up
    def fit_price(self):
        """
        取当天交易日的最高最低均价做为决策价格
        :return: 最终决策的当前交易买入价格
        """
        # TODO 基类提取作为装饰器函数，子类根据需要选择是否装饰，并且添加上根据order的call，put明确细节逻辑
        if self.kl_pd_buy.pre_close == 0 or (self.kl_pd_buy.open / self.kl_pd_buy.pre_close) < (1 - g_open_down_rate):
            # 开盘就下跌一定比例阀值，放弃单子
            return np.inf
        # 买入价格为当天均价，即最高，最低的平均，也可使用高开低收平均等方式计算
        self.buy_price = np.mean([self.kl_pd_buy['high'], self.kl_pd_buy['low']])
        # 返回最终的决策价格
        return self.buy_price


# 利润保护止盈策略和滑点策略配置
def buy_sell_close_atr_nstop_slippage(symbols):
    # buy_factors 60日向上突破，42日向上突破两个因子
    buy_factors = [{'slippage': AbuSlippageBuyMean2, 'xd': 60,
                    'class': AbuFactorBuyBreak},
                   {'xd': 42, 'class': AbuFactorBuyBreak}]

    # 使用120天向下突破为卖出信号
    sell_factor1 = {'xd': 120, 'class': AbuFactorSellBreak}
    # 趋势跟踪策略止盈要大于止损设置值，这里0.5，3.0

    sell_factor2 = {'stop_loss_n': 0.5, 'stop_win_n': 3.0,
                    'class': AbuFactorAtrNStop}

    # 暴跌止损卖出因子形成dict
    sell_factor3 = {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.0}

    # 保护止盈卖出因子组成dict
    sell_factor4 = {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5}

    # 两个卖出因子策略并行同时生效
    sell_factors = [sell_factor1, sell_factor2, sell_factor3, sell_factor4]
    benchmark = AbuBenchmark(n_folds=4)
    capital = AbuCapital(1000000, benchmark)
    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(symbols,
                                                                              benchmark,
                                                                              buy_factors,
                                                                              sell_factors,
                                                                              capital, show=False)
    if orders_pd is not None:
        print('orders_pd {}'.format(orders_pd.tail(10)))


# 利润保护止盈策略和滑点策略配置，手续费
def buy_sell_close_atr_nstop_slippage_commission(symbols):
    # buy_factors 60日向上突破，42日向上突破两个因子
    buy_factors = [{'slippage': AbuSlippageBuyMean2, 'xd': 60,
                    'class': AbuFactorBuyBreak},
                   {'xd': 42, 'class': AbuFactorBuyBreak}]

    # 使用120天向下突破为卖出信号
    sell_factor1 = {'xd': 120, 'class': AbuFactorSellBreak}
    # 趋势跟踪策略止盈要大于止损设置值，这里0.5，3.0

    sell_factor2 = {'stop_loss_n': 0.5, 'stop_win_n': 3.0,
                    'class': AbuFactorAtrNStop}

    # 暴跌止损卖出因子形成dict
    sell_factor3 = {'class': AbuFactorPreAtrNStop, 'pre_atr_n': 1.0}

    # 保护止盈卖出因子组成dict
    sell_factor4 = {'class': AbuFactorCloseAtrNStop, 'close_atr_n': 1.5}

    # 构造一个字典key='buy_commission_func', value=自定义的手续费方法函数
    commission_dict = {'buy_commission_func': calc_commission_us, 'sell_commission_func': calc_commission_us}

    # 两个卖出因子策略并行同时生效
    sell_factors = [sell_factor1, sell_factor2, sell_factor3, sell_factor4]
    benchmark = AbuBenchmark(n_folds=4)
    capital = AbuCapital(1000000, benchmark, user_commission_dict=commission_dict)
    orders_pd, action_pd, _ = ABuPickTimeExecute.do_symbols_with_same_factors(symbols,
                                                                              benchmark,
                                                                              buy_factors,
                                                                              sell_factors,
                                                                              capital, show=False)
    if orders_pd is not None:
        print('orders_pd {}'.format(orders_pd.tail(10)))
        print('commission_pd {}'.format(capital.commission.commission_df))


def calc_commission_us2(trade_cnt, price):
    """
        手续费统一7美元
    """
    return 7


# 定义手续费
def calc_commission_us(trade_cnt, price):
    """
    美股计算交易费用：每股0.01，最低消费2.99
    :param trade_cnt: 交易的股数（int）
    :param price: 每股的价格（美元）（暂不使用，只是保持接口统一）
    :return: 计算结果手续费
    """
    # 每股手续费0.01
    commission = trade_cnt * 0.01
    if commission < 2.99:
        # 最低消费2.99
        commission = 2.99
    return commission


if __name__ == '__main__':
    symbols = ['hk03690']
    # buy_sell_atr_nstop(symbols)
    # buy_sell_pre_atr_nstop(symbols)
    # buy_sell_close_atr_nstop_slippage(symbols)
    buy_sell_close_atr_nstop_slippage_commission(symbols)
