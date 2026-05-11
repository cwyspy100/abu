'''
通过均线实现智能定投策略：
1. 从回测第一天起即可按月定投（不再等待 xd 日才允许首笔）
2. 未满 xd 根 K 线时无有效均线，按基准金额定投（系数 1.0）
3. 满 xd 日均线后，按价格相对均线偏离度调整系数（高于均线过多则当月跳过买入等，逻辑同下）
4. 当价格低于均线20%时，投资金额为基准的2倍
5. 当价格低于均线10%时，投资金额为基准的1.5倍
6. 其他情况维持基准投资金额

xd：均线周期（默认 120），仅当该周期均线可算时启用偏离度逻辑。
'''

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

from abupy import AbuFactorBuyBase, BuyCallMixin
import pandas as pd

# noinspection PyAttributeOutsideInit
class AbuFactorBuyFixedInvest(AbuFactorBuyBase, BuyCallMixin):
    """固定金额定投策略，根据价格相对均线位置动态调整投资金额"""

    def _init_self(self, **kwargs):
        """kwargs 可选:
        1. xd: 均线周期（默认 120），满周期后才计算偏离度
        2. invest_base_amount: 每月基准投资金额
        """
        self.xd = int(kwargs.get('xd', 120))
        if self.xd < 1:
            self.xd = 1
        self._invest_base_amount = float(kwargs.get('invest_base_amount', 10000))
        self.invest_base_amount = self._invest_base_amount
        # 记录上次投资的月份
        self.last_invest_month = None
        # 在输出生成的orders_pd中显示的名字
        self.factor_name = '{}:{}:{}'.format(self.__class__.__name__, self.xd, int(self._invest_base_amount))

    def fit_day(self, today):
        """
        针对每一天交易日进行定投判断
        :param today: 当前驱动的交易日金融时间序列数据
        :return: None if no transaction else AbuOrder
        """
        # 计算当前交易日所属月份
        today_str = str(int(today.date))  # 将20240506.0转换为"20240506"
        current_date = pd.to_datetime(today_str, format='%Y%m%d')
        current_month = current_date.strftime('%Y%m')  # 格式化为"202405"

        # 如果已经在本月进行过投资，跳过
        if self.last_invest_month == current_month:
            return None

        xd = self.xd
        # 仅当满 xd 根 K 线时才有有效均线；此前不计算偏离度，按基准定投
        self.kl_pd['ma'] = self.kl_pd['close'].rolling(window=xd, min_periods=xd).mean()
        current_ma = self.kl_pd['ma'].iloc[self.today_ind]

        if pd.isnull(current_ma) or current_ma == 0:
            coefficient = 1.0
            deviation = float('nan')
        else:
            deviation = (today.close - current_ma) * 100.0 / current_ma
            # 根据偏离度确定投资金额系数（仅在有有效均线时启用）
            if deviation > 20:
                # 股价高于均线20%以上，当月不投
                return None
            elif deviation > 10:
                # 股价高于均线10%-20%，当月不投
                return None
            elif deviation > -10:
                # 股价在均线上下10%内，正常投入
                coefficient = 1.0
            elif deviation > -20:
                # 股价低于均线10%-20%，增加20%投入
                coefficient = 1.2
            elif deviation > -40:
                # 股价低于均线20%-40%，增加50%投入
                coefficient = 1.5
            else:
                # 股价低于均线40%以上，加倍投入
                coefficient = 2.0

        self.invest_base_amount = self._invest_base_amount * coefficient
        print(
            "today_str {} current_ma {} today.close {} deviation {} coefficient {} invest_base_amount {}".format(
                today_str,
                current_ma,
                today.close,
                deviation,
                coefficient,
                self.invest_base_amount,
            )
        )

        # 更新上次投资月份
        self.last_invest_month = current_month

        # 生成买入订单
        return self.buy_tomorrow()