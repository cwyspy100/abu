# -*- encoding:utf-8 -*-
"""
    择时与选股抽象基类
    Python 3.9 版本
"""


from abc import ABCMeta, abstractmethod

from ..CoreBu.ABuBase import AbuParamBase

__author__ = '阿布'
__weixin__ = 'abu_quant'


class AbuPickTimeWorkBase(AbuParamBase, metaclass=ABCMeta):
    """择时抽象基类"""

    @abstractmethod
    def fit(self, *args, **kwargs):
        """
        fit在整个项目中的意义为开始对象最重要的工作，
        对于择时对象即为开始择时操作，或者从字面理解
        开始针对交易数据进行拟合择时操作
        """
        pass

    @abstractmethod
    def init_sell_factors(self, *args, **kwargs):
        """
        初始化择时卖出因子
        """
        pass

    @abstractmethod
    def init_buy_factors(self, *args, **kwargs):
        """
        初始化择时买入因子
        """
        pass


class AbuPickStockWorkBase(AbuParamBase, metaclass=ABCMeta):
    """选股抽象基"""

    @abstractmethod
    def fit(self, *args, **kwargs):
        """
        fit在整个项目中的意义为开始对象最重要的工作，
        对于选股对象即为开始选股操作，或者从字面理解
        开始针对交易数据进行拟合选股操作
        """
        pass

    @abstractmethod
    def init_stock_pickers(self, *args, **kwargs):
        """
        初始化选股因子
        """
        pass
