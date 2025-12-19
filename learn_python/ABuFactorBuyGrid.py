from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

from abupy import AbuFactorBuyBase, BuyCallMixin
import numpy as np
import datetime

class AbuFactorBuyGrid(AbuFactorBuyBase, BuyCallMixin):
    """基于120日均线的网格交易策略"""

    def _init_self(self, **kwargs):
        """初始化参数
        Args:
            grid_count: 网格数量，默认5格
            grid_interval: 网格间距，默认5%
            invest_base_amount: 每格基准投资金额
            ma_period: 均线周期，默认120天
        """
        self.grid_count = kwargs.get('grid_count', 5)
        self.grid_interval = kwargs.get('grid_interval', 5)
        self.invest_base_amount = kwargs.get('invest_base_amount', 200000)
        self.ma_period = kwargs.get('ma_period', 120)
        
        # 初始化网格状态字典
        if not hasattr(AbuFactorBuyGrid, '_grid_states'):
            AbuFactorBuyGrid._grid_states = {}
        self.grid_states = AbuFactorBuyGrid._grid_states
        
        # 动态基准价格（120日均线）
        self.ma_price = 0
        
        self.factor_name = '{}:{}:{}:{}:{}'.format(
            self.__class__.__name__, 
            self.ma_period,
            self.grid_count,
            self.grid_interval,
            self.invest_base_amount
        )

    def fit_day(self, today):
        """每日交易策略"""
        # 忽略不符合买入的天（统计周期内前ma_period天）
        if self.today_ind < self.ma_period - 1:
            return None

        # 计算120日均线
        window_prices = self.kl_pd.close[self.today_ind - self.ma_period + 1:self.today_ind + 1]
        self.ma_price = window_prices.mean()

        # 计算当前价格相对均线的偏离度（百分比）
        deviation = (today.close - self.ma_price) * 100 / self.ma_price
        
        # 计算当前价格所在的网格
        # 负数表示价格低于均线，正数表示高于均线
        current_grid = int(deviation / self.grid_interval)
        
        # 只在下跌时买入，且网格编号必须在设定范围内
        if current_grid >= 0 or abs(current_grid) > self.grid_count:
            return None
            
        # 获取实际的网格编号（1-5）
        actual_grid = abs(current_grid)
            
        # 检查当前网格是否已买入
        grid_key = f"{self.kl_pd.name}_{actual_grid}"
        if self.grid_states.get(grid_key, False):
            return None
            
        # 计算投资金额：越靠下的网格投资金额越大
        coefficient = 1.0 + (actual_grid - 1) * 0.2  # 每低一个网格，增加20%投资
        # self.buy_factor = self.invest_base_amount * coefficient
        # self.capital.read_cash = self.invest_base_amount * coefficient
        
        # 标记该网格已买入
        self.grid_states[grid_key] = True
        
        log = "股票: {}, 当前日期：{}, 当前价格: {:.2f}, 120日均线: {:.2f}, 偏离度: {:.2f}%, 网格: {}, 投资系数: {:.2f}".format(
            self.kl_pd.name,
            today.date,
            today.close,
            self.ma_price,
            deviation,
            actual_grid,
            coefficient
        )
        print(log)

        # self.save_grid_log()
        
        return self.buy_tomorrow()

    def reset_grid_states(self):
        """重置网格状态（在卖出后调用）"""
        for key in list(self.grid_states.keys()):
            if key.startswith(self.kl_pd.name):
                self.grid_states.pop(key)

    def save_grid_log(resultlog):
        result = []
        today = datetime.date.today()
        result.append("------------" + str(today) + "-------------42非动态均线----------------")
        result.append(resultlog)
        string = "\n"
        with open('../todolist/stock_us_pool_grid.txt', 'a', encoding='utf-8') as f:
            f.write(string.join(result))