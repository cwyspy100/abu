'''
通过均线实现智能定投策略：
1. 每月定投固定金额
2. 当价格低于均线20%时，投资金额为基准的2倍
3. 当价格低于均线10%时，投资金额为基准的1.5倍
4. 其他情况维持基准投资金额
'''

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

from abupy import AbuFactorBuyBase, BuyCallMixin
import datetime
import pandas as pd

# noinspection PyAttributeOutsideInit
class AbuFactorBuyFixedInvest(AbuFactorBuyBase, BuyCallMixin):
    """固定金额定投策略，根据价格相对均线位置动态调整投资金额"""

    def _init_self(self, **kwargs):
        """kwargs中必须包含: 
        1. xd: 均线周期，默认20天
        2. invest_base_amount: 每月基准投资金额
        """
        self.xd = kwargs.get('xd', 20)
        self.invest_base_amount = kwargs.get('invest_base_amount', 10000)
        # 记录上次投资的月份
        self.last_invest_month = None
        # 在输出生成的orders_pd中显示的名字
        self.factor_name = '{}:{}:{}'.format(self.__class__.__name__, self.xd, self.invest_base_amount)

    def fit_day(self, today):
        """
        针对每一天交易日进行定投判断
        :param today: 当前驱动的交易日金融时间序列数据
        :return: None if no transaction else AbuOrder
        """
        # 忽略不符合买入的天（统计周期内前xd天）
        if self.today_ind < self.xd - 1:
            return None

        # 计算当前交易日所属月份
        today_str = str(int(today.date))  # 将20240506.0转换为"20240506"
        current_date = pd.to_datetime(today_str, format='%Y%m%d')  # 正确格式应为%Y%m%d
        current_month = current_date.strftime('%Y%m')  # 格式化为"202405"

        # 如果已经在本月进行过投资，跳过
        if self.last_invest_month == current_month:
            return None

        # 计算均线
        self.kl_pd['ma'] = self.kl_pd['close'].rolling(window=120).mean()

        # 不足周期时用收盘价替代均线
        self.kl_pd['ma'] = self.kl_pd['ma'].fillna(self.kl_pd['close'])
        current_ma = self.kl_pd['ma'].iloc[self.today_ind]

        # 计算当前价格相对均线的偏离度
        deviation = (today.close - current_ma) * 100 / current_ma


        # 根据偏离度确定投资金额倍数
        # 根据偏离度确定投资金额系数
        handle = False
        if deviation > 20:
            # 股价高于均线20%以上，投入减半
            coefficient = 0.5
            return None
        elif deviation > 10:
            # 股价高于均线10%-20%，投入80%
            coefficient = 0.8
            return None
        elif deviation > -10:
            # 股价在均线上下10%内，正常投入
            coefficient = 1.0
            handle = True
        elif deviation > -20:
            # 股价低于均线10%-20%，增加20%投入
            coefficient = 1.2
        elif deviation > -40:
            # 股价低于均线20%-40%，增加50%投入
            coefficient = 1.5
        else:
            # 股价低于均线40%以上，加倍投入
            coefficient = 2.0

        self.invest_base_amount = 10000 * coefficient
        print("today_str {} current_ma {} today.close {}  deviation {} coefficient {}  invest_base_amount {} ".format(today_str, current_ma, today.close,
                                                                                deviation, coefficient, self.invest_base_amount))

        # 更新上次投资月份
        self.last_invest_month = current_month

        # # 设置本次交易的资金使用率
        # self.position.pos_base = invest_rate

        # 生成买入订单
        return self.buy_tomorrow()