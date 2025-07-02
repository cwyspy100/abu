'''
通过网格交易策略实现指数的卖出：
1. 设定基准价格(120日均线)和网格间距(百分比)
2. 当价格上涨到对应买入网格的卖出点时卖出
3. 根据价格偏离基准的程度动态调整卖出金额
4. 每个网格使用相同的资金比例
'''

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

from abupy import AbuFactorSellBase, ESupportDirection
from learn_python.ABuFactorBuyGrid import AbuFactorBuyGrid
import numpy as np
import datetime

class AbuFactorSellGrid(AbuFactorSellBase):
    """网格交易策略，根据价格相对120日均线位置动态调整卖出金额"""

    def _init_self(self, **kwargs):
        """kwargs中必须包含: 
        1. grid_interval: 网格间距，百分比表示，默认5%
        2. ma_period: 均线周期，默认120天
        3. grid_count: 网格数量，默认5格
        """
        self.grid_interval = kwargs.get('grid_interval', 5)
        self.ma_period = kwargs.get('ma_period', 120)
        self.grid_count = kwargs.get('grid_count', 5)
        
        # 记录网格状态，与买入策略共享
        self.grid_states = AbuFactorBuyGrid._grid_states
        # 动态基准价格（120日均线）
        self.ma_price = 0
        
        self.factor_name = '{}:{}:{}:{}'.format(
            self.__class__.__name__, 
            self.ma_period,
            self.grid_count,
            self.grid_interval
        )

    def fit_day(self, today, orders):
        """针对每一天交易日进行网格交易判断"""
        # 忽略不符合卖出的天（统计周期内前ma_period天）
        if self.today_ind < self.ma_period - 1:
            return None

        # 计算120日均线
        window_prices = self.kl_pd.close[self.today_ind - self.ma_period + 1:self.today_ind + 1]
        self.ma_price = window_prices.mean()

        # 计算当前价格相对均线的偏离度（百分比）
        deviation = (today.close - self.ma_price) * 100 / self.ma_price
        
        # 计算当前价格所在的网格
        # 正数表示价格高于均线
        current_grid = int(deviation / self.grid_interval)
        
        # 只在上涨时卖出，且网格编号必须在设定范围内
        if current_grid <= 0 or current_grid > self.grid_count:
            return None
            
        # 遍历订单，检查是否有对应网格的买入订单需要卖出
        for order in orders:
            # 获取买入时的网格编号
            buy_grid_key = None
            for key in self.grid_states:
                if key.startswith(self.kl_pd.name) and self.grid_states[key]:
                    buy_grid_key = key
                    break
                    
            if not buy_grid_key:
                continue

            if order.sell_type != 'keep':
                continue
                
            # 提取买入网格编号
            buy_grid = int(buy_grid_key.split('_')[1])
            
            # 只有当前卖出网格等于买入网格时才卖出
            if current_grid == buy_grid:
                # 计算卖出系数：与买入策略保持一致
                coefficient = 1.0 + (current_grid - 1) * 0.2
                
                log = ("股票: {},  当前日期：{},当前价格: {:.2f}, 120日均线: {:.2f}, 偏离度: {:.2f}%, 卖出网格: {}, 卖出系数: {:.2f}".format(
                    self.kl_pd.name,
                    today.date,
                    today.close,
                    self.ma_price,
                    deviation,
                    current_grid,
                    coefficient
                ))
                print(log)
                # self.save_grid_log()
                
                # 重置该网格状态
                self.grid_states[buy_grid_key] = False
                
                # 生成卖出订单
                self.sell_tomorrow(order)

    def support_direction(self):
        """支持的交易方向，只支持正向"""
        return [ESupportDirection.DIRECTION_CAll.value]

    def save_grid_log(resultlog):
        result = []
        today = datetime.date.today()
        result.append("------------" + str(today) + "-------------42非动态均线----------------")
        result.append(resultlog)
        string = "\n"
        with open('../todolist/stock_us_pool_grid.txt', 'a', encoding='utf-8') as f:
            f.write(string.join(result))