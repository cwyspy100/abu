# -*- encoding:utf-8 -*-
# """成交量选股模块开发"""

import abu_local_env
import abupy
from abc import abstractmethod
from abupy.CoreBu import ABuEnv
from abupy.PickStockBu import ABuPickStockBase


class TradeVolumeStrategy(ABuPickStockBase):
    """成交量选股策略类"""

    def _init_self(self, **kwargs):
        """通过kwargs设置选股条件，配置因子参数"""
        # 选股参数day_num：成交量选股因子的参数, 默认5
        self.day_num = kwargs.pop('day_num', 5)


    @abstractmethod
    def fit_pick(self, kl_pd, target_symbol):
        """
        选股因子的fit_pick方法，根据选股条件进行选股
        :param kl_pd: kline数据
        :param target_symbol: 选股目标symbol
        :return: True or False
        """
        day_num = self.day_num
        # 通过交易量来进行选股，当n+1天的交易量是当前n天的交易量平局值的3倍的时候，选择该股票
        if len(kl_pd) < day_num + 1:
            return False

        avg_volume = kl_pd['volume'][-day_num-1:-1].mean()
        ratio = kl_pd['volume'].iloc[-1] / avg_volume

        return ratio > 3


    @abstractmethod
    def fit_first_choice(self, pick_worker, choice_symbols, *args, **kwargs):
        """
        选股因子的fit_first_choice方法，根据选股条件进行选股
        :param pick_worker: 选股对象
        :param choice_symbols: 选股目标symbol集合
        :param args
        :param kwargs
        :return: True or False
        """
        pass


if __name__ == '__main__':
    pass
