'''
通过网格交易策略实现指数的买卖：
1. 设定基准价格和网格间距(百分比)
2. 当价格下跌到网格买入点时买入
3. 根据价格偏离基准的程度动态调整买入金额
4. 每个网格使用相同的资金比例

总结：
网格交易策略，适合基金同时基金是上升，如何过是上升，那么直接最初购买就好，不是一个很好的策略
'''

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

from abupy import AbuFactorBuyBase, BuyCallMixin
import numpy as np

# noinspection PyAttributeOutsideInit
class AbuFactorBuyGrid(AbuFactorBuyBase, BuyCallMixin):
    """网格交易策略，根据价格相对基准位置动态调整投资金额"""

    def _init_self(self, **kwargs):
        """kwargs中必须包含: 
        1. grid_interval: 网格间距，百分比表示，默认5%
        2. invest_base_amount: 每格基准投资金额
        3. window_size: 计算基准价格的滑动窗口大小，默认20天
        """
        self.grid_interval = kwargs.get('grid_interval', 5)
        self.invest_base_amount = kwargs.get('invest_base_amount', 10000)
        self.window_size = kwargs.get('window_size', 20)
        
        # 记录网格状态，key为网格编号，value为买入状态
        # 使用类变量来共享网格状态
        if not hasattr(AbuFactorBuyGrid, '_grid_states'):
            AbuFactorBuyGrid._grid_states = {}
        self.grid_states = AbuFactorBuyGrid._grid_states
        # 动态基准价格
        self.grid_base_price = 0
        # 在输出生成的orders_pd中显示的名字
        self.factor_name = '{}:{}:{}:{}'.format(
            self.__class__.__name__, 
            self.grid_base_price,
            self.grid_interval,
            self.invest_base_amount
        )

    def fit_day(self, today):
        """针对每一天交易日进行网格交易判断"""
        # 忽略不符合买入的天（统计周期内前window_size天）
        if self.today_ind < self.window_size - 1:
            return None

        # 计算滑动窗口的均值作为基准价格
        window_prices = self.kl_pd.close[self.today_ind - self.window_size + 1:self.today_ind + 1]
        self.grid_base_price = window_prices.mean()

        # 计算当前价格相对基准价格的偏离度
        deviation = (today.close - self.grid_base_price) * 100 / self.grid_base_price
        
        # 计算当前价格所在的网格
        current_grid = int(deviation / self.grid_interval)
        
        # 只在下跌时买入
        if deviation >= 0:
            return None
            
        # 检查当前网格是否已买入
        if self.grid_states.get(current_grid, False):
            return None
            
        # 计算投资金额系数：偏离度越大，投资金额越大
        grid_count = abs(current_grid)  # 当前是第几个网格
        coefficient = 1.0 + (grid_count - 1) * 0.2  # 每下跌一个网格，增加20%投资
        
        # 设置本次交易的资金使用率
        self.buy_factor = self.invest_base_amount * coefficient
        
        # 更新网格状态为已买入
        self.grid_states[current_grid] = True
        
        print("当前价格: {:.2f}, 基准价格: {:.2f}, 偏离度: {:.2f}%, 网格: {}, 投资系数: {:.2f}, 网格状态: {}".format(
            today.close,
            self.grid_base_price,
            deviation,
            current_grid,
            coefficient,
            self.grid_states[current_grid]
        ))
        
        # 生成买入订单
        return self.buy_tomorrow()