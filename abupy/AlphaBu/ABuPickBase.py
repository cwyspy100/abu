# -*- encoding:utf-8 -*-
"""
    择时与选股抽象基类
"""
# 在本文件顶部引入 `from __future__` 相关指令（如 absolute_import, print_function, division）是为了确保无论是在 Python 2 还是 Python 3 下，代码的行为始终一致、兼容。虽然这些 future 指令在本文件中没有直接调用或者看起来“用到”，但它们会影响整个文件中的导入机制、print语法以及除法操作的默认行为，是一种全局影响。
# 具体说：
# - `absolute_import`：避免相对导入和绝对导入混淆，保证`import xxx`一定是从顶层导入包。
# - `print_function`：使 print 表达式强制采用函数语法，兼容 Python 3 的 print() 写法。
# - `division`：让 `/` 运算符执行真正的浮点除法，`//` 表示地板除。
# 这么做的目的是将源代码用一种“将来兼容”的方式编写，避免 Python 2/3 细节差异带来隐蔽 bug，这是一种良好的代码习惯。
# 如果你的项目完全不需要兼容 Python2，仅在 Python3 环境下运行和维护，那么这些 `from __future__` 的导入（如 absolute_import, print_function, division）是可以不用的。
# Python3 已经将这些行为（绝对导入、print 函数语法、/ 真除）作为默认标准，因此无需额外指定兼容。
# 不过移除这些不会对 Python3 带来实际影响，只是清理无用代码，让代码更简洁。



from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

from abc import ABCMeta, abstractmethod

from ..CoreBu.ABuFixes import six
from ..CoreBu.ABuBase import AbuParamBase

__author__ = '阿布'
__weixin__ = 'abu_quant'

# six.with_metaclass 是用于为类指定 metaclass 的一种兼容 Python 2 和 Python 3 的写法。
# 由于在 Python 2 和 3 中指定 metaclass 的语法不同，直接写 metaclass= 会在 Python 2 下报错。
# six.with_metaclass 能让类同时支持 Python 2 和 3 下的 metaclass。
#
# 具体地说，例如：
# class MyClass(six.with_metaclass(ABCMeta, BaseClass)):
#     pass
#
# 这样的写法能保证无论在 Python 2 还是 Python 3，MyClass 的 metaclass 都是 ABCMeta。
# 在 Python3 中，直接使用 `metaclass=` 语法定义元类即可，
# 不再需要 `six.with_metaclass` 来兼容 Python2/3。
# 例如可以直接这样定义基类：
#
# class AbuPickTimeWorkBase(AbuParamBase, metaclass=ABCMeta):
#     ...
#
# 但是如果还需要兼容 Python2，则 `six.with_metaclass` 是必要的。

# ABCMeta 是 Python 的抽象基类元类（Abstract Base Class Meta），
# 用于定义抽象基类。当一个类指定 metaclass=ABCMeta，
# 并且用 @abstractmethod 修饰方法时，表示该方法是抽象方法，
# 该类不能被实例化，只有实现了所有抽象方法的子类才能被实例化。
# 这样可以强制子类实现某些方法，从而规范接口和行为。

class AbuPickTimeWorkBase(six.with_metaclass(ABCMeta, AbuParamBase)):
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


class AbuPickStockWorkBase(six.with_metaclass(ABCMeta, AbuParamBase)):
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
