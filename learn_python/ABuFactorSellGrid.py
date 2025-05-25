'''
通过网格交易策略实现指数的卖出：
1. 设定基准价格和网格间距(百分比)
2. 当价格上涨到网格卖出点时卖出
3. 根据价格偏离基准的程度动态调整卖出金额
4. 每个网格使用相同的资金比例
'''

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

from abupy import AbuFactorSellBase, ESupportDirection
from learn_python.ABuFactorBuyGrid import AbuFactorBuyGrid
import numpy as np

# noinspection PyAttributeOutsideInit
class AbuFactorSellGrid(AbuFactorSellBase):
    """网格交易策略，根据价格相对基准位置动态调整卖出金额"""

    def _init_self(self, **kwargs):
        """kwargs中必须包含: 
        1. grid_interval: 网格间距，百分比表示，默认5%
        2. window_size: 计算基准价格的滑动窗口大小，默认20天
        """
        self.grid_interval = kwargs.get('grid_interval', 5)
        self.window_size = kwargs.get('window_size', 20)
        
        # 记录网格状态，与买入策略共享
        self.grid_states = AbuFactorBuyGrid._grid_states
        # 动态基准价格
        self.grid_base_price = 0
        # 在输出生成的orders_pd中显示的名字
        self.factor_name = '{}:{}:{}'.format(
            self.__class__.__name__, 
            self.grid_base_price,
            self.grid_interval
        )

    def fit_day(self, today, orders):
        """针对每一天交易日进行网格交易判断"""
        # 忽略不符合卖出的天（统计周期内前window_size天）
        if self.today_ind < self.window_size - 1:
            return None

        # 计算滑动窗口的均值作为基准价格
        window_prices = self.kl_pd.close[self.today_ind - self.window_size + 1:self.today_ind + 1]
        self.grid_base_price = window_prices.mean()

        # 计算当前价格相对基准价格的偏离度
        deviation = (today.close - self.grid_base_price) * 100 / self.grid_base_price
        
        # 计算当前价格所在的网格
        current_grid = int(deviation / self.grid_interval)
        
        # 只在上涨时卖出
        if deviation <= 0:
            return None
            
        # 检查当前网格是否已买入
        if not self.grid_states.get(current_grid, False):
            return None
            
        # 计算卖出金额系数：偏离度越大，卖出金额越大
        grid_count = abs(current_grid)  # 当前是第几个网格
        coefficient = 1.0 + (grid_count - 1) * 0.2  # 每上涨一个网格，增加20%卖出
        
        # 更新网格状态为未买入，允许重新买入
        self.grid_states[current_grid] = False
        
        print("当前价格: {:.2f}, 基准价格: {:.2f}, 偏离度: {:.2f}%, 网格: {}, 卖出系数: {:.2f}, 网格状态: {}".format(
            today.close,
            self.grid_base_price,
            deviation,
            current_grid,
            coefficient,
            self.grid_states[current_grid]
        ))
        
        # 遍历订单，对每个订单执行卖出操作
        for order in orders:
            # 设置卖出数量比例
            # order.sell_cnt = int(order.buy_cnt * coefficient)
            # 生成卖出订单
            self.sell_tomorrow(order)

    def support_direction(self):
        """支持的交易方向，只支持正向"""
        return [ESupportDirection.DIRECTION_CAll.value]