# -*- encoding:utf-8 -*-
"""
    选股具体工作者，整合金融时间序列，选股因子，资金类进行
    选股操作，在择时金融时间序列之前一段时间上迭代初始交易对象
    进行选股因子的拟合操作
"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

import copy

from .ABuPickBase import AbuPickStockWorkBase
from ..MarketBu.ABuMarket import all_symbol
from ..PickStockBu.ABuPickStockBase import AbuPickStockBase
from ..UtilBu.ABuProgress import AbuMulPidProgress

__author__ = '阿布'
__weixin__ = 'abu_quant'

"""
AbuPickStockWorker 分析与 Python3 优化建议

类 AbuPickStockWorker 负责将资金、基准、选股因子和股票池等关键对象整合，循环迭代初始证券池，利用股票选股因子拟合后输出选股结果。
其职责为：
- 持有资本、基准、证券池和金融时间序列管理器，对引入的 stock_pickers 进行初始化、复合和执行。
- 通过 init_stock_pickers 方法动态实例化与验证每个选股因子。
- 支持灵活传入选股因子构造参数和对象检查。

Python3 优化点建议如下：
1. 移除 `from __future__` 相关导入：这些导入只为兼容 Python2，当前仅支持 Python3 可删去。
2. 类型注解：为 __init__ 和核心方法增加类型注解（如 capital: AbuCapital），提升代码可读性和静态检查能力。
3. 深拷贝优化：copy.deepcopy 在参数已标准化的情况下可考虑浅拷贝或 dict unpack，减少性能开销，具体要结合实测需求。
4. 使用 super()：若 AbuPickStockWorkBase 为新式类（继承 object），可直接用 super().__init__()，更规范。
5. f-string 优化：__str__ 方法可使用 f-string 替代 format，代码更现代。
6. 抛出异常类型可补充提示信息，如 TypeError、ValueError 内容详实，并可自定义新异常。
7. 去除多余的中英注释混排。如确定仅服务于中文用户，可统一中文注释，否则建议主要用英文，提升国际化能力。
8. 模块文档字符串（docstring）可补充方法参数与返回类型说明，按照 PEP 257 精简格式。
9. 若有并发需求，stock_pickers/init 过程可探索异步优化或者多线程/进程实例化（如有大量因子）。

总之，本类及模块总体已结构清晰，对于 Python3 兼容性良好。主要提升空间为类型注解、现代语法和适当性能细节优化。
"""

class AbuPickStockWorker(AbuPickStockWorkBase):
    """选股类"""

    def __init__(self, capital, benchmark, kl_pd_manager, choice_symbols=None, stock_pickers=None):
        """
        :param capital: 资金类AbuCapital实例化对象
        :param benchmark: 交易基准对象，AbuBenchmark实例对象
        :param kl_pd_manager: 金融时间序列管理对象，AbuKLManager实例
        :param choice_symbols: 初始备选交易对象序列
        :param stock_pickers: 选股因子序列
        """
        self.capital = capital
        self.benchmark = benchmark
        self.choice_symbols = choice_symbols
        self.kl_pd_manager = kl_pd_manager
        self.stock_pickers = []
        self.first_stock_pickers = []
        self.init_stock_pickers(stock_pickers)

    def __str__(self):
        """打印对象显示：选股因子序列＋选股交易对象"""
        return 'stock_pickers:{}\nchoice_symbols:{}'.format(self.stock_pickers, self.choice_symbols)

    __repr__ = __str__

    def init_stock_pickers(self, stock_pickers):
        """
        通过stock_pickers实例化各个选股因子
        :param stock_pickers:list中元素为dict，每个dict为因子的构造元素，如class，构造参数等
        :return:
        """
        if stock_pickers is not None:
            for picker_class in stock_pickers:
                if picker_class is None:
                    continue

                if 'class' not in picker_class:
                    # 必须要有需要实例化的类信息
                    raise ValueError('picker_class class key must name class !!!')

                picker_class_cp = copy.deepcopy(picker_class)
                # pop出类信息后剩下的都为类需要的参数
                class_fac = picker_class_cp.pop('class')
                # 整合capital，benchmark等实例化因子对象
                picker = class_fac(self.capital, self.benchmark, **picker_class_cp)

                if not isinstance(picker, AbuPickStockBase):
                    # 因子对象类型检测
                    raise TypeError('factor must base AbuPickStockBase')

                if 'first_choice' in picker_class and picker_class['first_choice']:
                    # 如果参数设置first_choice且是True, 添加到first_stock_pickers选股序列
                    self.first_stock_pickers.append(picker)
                else:
                    self.stock_pickers.append(picker)
        if self.choice_symbols is None or len(self.choice_symbols) == 0:
            # 如果参数中初始备选交易对象序列为none, 从对应市场中获取所有的交易对象，详情查阅all_symbol
            self.choice_symbols = all_symbol()

    def fit(self):
        """
        选股开始工作，与择时不同，选股是数据多对多，
        即多个交易对象对多个选股因子配合资金基准等参数工作
        :return:
        """

        def _first_batch_fit():
            """
            first_choice选股：针对备选池进行选股，迭代选股因子，使用因子的fit_first_choice方法
            即因子内部提供批量选股高效的首选方法
            :return:
            """
            if self.first_stock_pickers is None or len(self.first_stock_pickers) == 0:
                # 如果没有first_stock_picker要返回self.choice_symbols，代表没有投任何反对票，全部通过
                return self.choice_symbols

            # 首选将所有备选对象赋予inner_first_choice_symbols
            inner_first_choice_symbols = self.choice_symbols
            with AbuMulPidProgress(len(self.first_stock_pickers), 'pick first_choice stocks complete') as progress:
                for epoch, first_choice in enumerate(self.first_stock_pickers):
                    progress.show(epoch + 1)
                    # 每一个选股因子通过fit_first_choice对inner_first_choice_symbols进行筛选，滤网一层一层过滤
                    inner_first_choice_symbols = first_choice.fit_first_choice(self, inner_first_choice_symbols)
            return inner_first_choice_symbols

        def _batch_fit():
            """
            普通选股：针对备选池进行选股，迭代初始选股序列，在迭代中再迭代选股因子，选股因子决定是否对
            symbol投出反对票，一旦一个因子投出反对票，即筛出序列，一票否决
            :return:
            """
            if self.stock_pickers is None or len(self.stock_pickers) == 0:
                # 如果没有stock_pickers要返回self.choice_symbols，代表没有投任何反对票，全部通过
                return self.choice_symbols

            with AbuMulPidProgress(len(self.choice_symbols), 'pick stocks complete') as progress:
                # 启动选股进度显示
                inner_choice_symbols = []
                for epoch, target_symbol in enumerate(self.choice_symbols):
                    progress.show(epoch + 1)

                    add = True
                    for picker in self.stock_pickers:
                        kl_pd = self.kl_pd_manager.get_pick_stock_kl_pd(target_symbol, picker.xd, picker.min_xd)
                        if kl_pd is None:
                            # 注意get_pick_stock_kl_pd内部对选股金融序列太少的情况进行过滤，详情get_pick_stock_kl_pd
                            add = False
                            break
                        sub_add = picker.fit_pick(kl_pd, target_symbol)
                        if sub_add is False:
                            # 只要一个选股因子投了反对票，就刷出
                            add = False
                            break
                    if add:
                        inner_choice_symbols.append(target_symbol)
                return inner_choice_symbols

        # 筛选各个因first_choice序列，返回给self.choice_symbols，_batch_fit继续晒
        self.choice_symbols = _first_batch_fit()
        # 通过两次迭代继续筛选
        self.choice_symbols = _batch_fit()
