# -*- encoding:utf-8 -*-
"""
    选股并行多任务调度模块
"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

import itertools
import logging


from .ABuPickStockExecute import do_pick_stock_work, do_pick_stock_thread_work
from ..CoreBu import ABuEnv
from ..CoreBu.ABuEnv import EMarketDataFetchMode
from ..CoreBu.ABuEnvProcess import AbuEnvProcess
from ..MarketBu.ABuMarket import split_k_market, all_symbol
from ..MarketBu import ABuMarket
from ..CoreBu.ABuFixes import partial
from ..CoreBu.ABuParallel import delayed, Parallel
from ..CoreBu.ABuDeprecated import AbuDeprecated

"""
本模块 AbuPickStockMaster.py 主要用于选股流程的多任务/并行调度，负责根据市场股票池对选股任务进行切分、分发与汇总。
其核心类 AbuPickStockMaster 提供 do_pick_stock_with_process 方法，实现多进程/多任务的选股因子遍历和股票筛选，旨在提高大规模选股时的计算效率和吞吐能力。

主要内容说明：
- 封装了选股因子（stock_pickers）在多进程/多任务下对股票池进行分片选股的完整调度、管理及结果整合。
- 依据 CPU 核数等资源，自动平衡任务粒度，并对数据源（如hdf5、csv本地文件等）模式做出自适应判断，保障并行工作的稳定性。
- 选股worker由 do_pick_stock_work/do_pick_stock_thread_work 装饰处理，能保证进程/线程环境一致性。
- 支持 callback 钩子的自定义扩展，方便将其他选股策略嵌入整体流程。
- 兼容不同平台及存储模式，特别考虑了多进程下文件竞争/数据安全等特殊场景。

python3 优化建议与分析：
- 本模块 import 了 __future__ 相关内容（absolute_import, print_function, division），在 Python 3 下已为默认行为，可去除，无需保留。
- 并行与多任务相关逻辑已基于高层API封装并适配 python3，无明显语法问题。内部大量调用 itertools、partial、Parallel 等模块已兼容 python3。
- 日志、异常管理接口使用标准 logging ，符合现代规范。
- 若仅考虑 python3，可使用类型注解(type hints)进一步提升代码可读性和静态检查能力。
- 自动推导进程数量的逻辑可适配 python3 的 os.cpu_count() 工具，当前 AbuEnv.g_cpu_cnt 若为 int 亦符合预期。
- 若涉及 Pickle 或序列化，多进程间对象传递可考虑 dill/cloudpickle 增强兼容性，但现有装饰器机制已处理主要场景。

结论：
本模块在 python3 下已结构合理、可直接工作。可选提升空间主要是：移除 __future__ 相关import，引入类型注解，丰富文档字符串。如果不再支持python2，可放心精简相关兼容写法。
"""

class AbuPickStockMaster(object):
    """选股并行多任务调度类"""

    @classmethod
    def do_pick_stock_with_process(cls, capital, benchmark, stock_pickers, choice_symbols=None,
                                   n_process_pick_stock=ABuEnv.g_cpu_cnt,
                                   callback=None):
        """
        选股并行多任务对外接口
        :param capital: 资金类AbuCapital实例化对象
        :param benchmark: 交易基准对象，AbuBenchmark实例对象
        :param stock_pickers: 选股因子序列
        :param choice_symbols: 初始备选交易对象序列
        :param n_process_pick_stock: 控制启动多少进程并行选股操作
        :param callback: 并行选股工作函数
        :return: 最终选股结果序列
        """
        input_choice_symbols = True
        if choice_symbols is None or len(choice_symbols) == 0:
            choice_symbols = all_symbol()
            input_choice_symbols = False

        if n_process_pick_stock <= 0:
            # 因为下面要n_process > 1做判断而且要根据n_process_pick_stock来split_k_market
            n_process_pick_stock = ABuEnv.g_cpu_cnt
        if stock_pickers is not None:

            # TODO 需要区分hdf5和csv不同存贮情况，csv存贮模式下可以并行读写
            # 只有E_DATA_FETCH_FORCE_LOCAL才进行多任务模式，否则回滚到单进程模式n_process = 1
            if n_process_pick_stock > 1 and ABuEnv.g_data_fetch_mode != EMarketDataFetchMode.E_DATA_FETCH_FORCE_LOCAL:
                # 1. hdf5多进程容易写坏数据，所以只多进程读取，不并行写入
                # 2. MAC OS 10.9 之后并行联网＋numpy 系统bug crash，卡死等问题
                logging.info('batch get only support E_DATA_FETCH_FORCE_LOCAL for Parallel!')
                n_process_pick_stock = 1

            # 根据输入的choice_symbols和要并行的进程数，分配symbol到n_process_pick_stock进程中
            process_symbols = split_k_market(n_process_pick_stock, market_symbols=choice_symbols)

            # 因为切割会有余数，所以将原始设置的进程数切换为分割好的个数, 即32 -> 33 16 -> 17
            if n_process_pick_stock > 1:
                n_process_pick_stock = len(process_symbols)

            parallel = Parallel(
                n_jobs=n_process_pick_stock, verbose=0, pre_dispatch='2*n_jobs')

            if callback is None:
                callback = do_pick_stock_work

            # do_pick_stock_work被装饰器add_process_env_sig装饰，需要进程间内存拷贝对象AbuEnvProcess
            p_nev = AbuEnvProcess()
            # 开始并行任务执行
            out_choice_symbols = parallel(delayed(callback)(choice_symbols, benchmark,
                                                            capital,
                                                            stock_pickers, env=p_nev)
                                          for choice_symbols in process_symbols)

            # 将每一个进程返回的选股序列合并成一个序列
            choice_symbols = list(itertools.chain.from_iterable(out_choice_symbols))

        """
            如下通过env中的设置来切割训练集，测试集数据，或者直接使用训练集，测试集，
            注意现在的设置有优先级，即g_enable_last_split_test > g_enable_last_split_train > g_enable_train_test_split
            TODO: 使用enum替换g_enable_last_split_test， g_enable_last_split_train， g_enable_train_test_split设置
        """
        if not input_choice_symbols and ABuEnv.g_enable_last_split_test:
            # 只使用上次切割好的测试集交易对象
            choice_symbols = ABuMarket.market_last_split_test()
        elif not input_choice_symbols and ABuEnv.g_enable_last_split_train:
            # 只使用上次切割好的训练集交易对象
            choice_symbols = ABuMarket.market_last_split_train()
        elif ABuEnv.g_enable_train_test_split:
            # 切割训练集交易对象与测试集交易对象，返回训练集交易对象
            choice_symbols = ABuMarket.market_train_test_split(ABuEnv.g_split_tt_n_folds, choice_symbols)

        return choice_symbols

    @classmethod
    @AbuDeprecated('hdf5 store mode will crash or dead!')
    def do_pick_stock_with_process_mix_thread(cls, capital, benchmark, stock_pickers, choice_symbols=None, n_process=8,
                                              n_thread=10):
        """Deprecated不应该使用，因为默认hdf5多线程读取会有问题"""
        callback = partial(do_pick_stock_thread_work, n_thread=n_thread)
        return cls.do_pick_stock_with_process(capital, benchmark, stock_pickers, choice_symbols=choice_symbols,
                                              n_process_pick_stock=n_process, callback=callback)
