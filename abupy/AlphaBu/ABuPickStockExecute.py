# -*- encoding:utf-8 -*-
"""
    包装选股worker进行，完善前后工作
"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

from .ABuPickStockWorker import AbuPickStockWorker
from ..CoreBu.ABuEnvProcess import add_process_env_sig
from ..MarketBu.ABuMarket import split_k_market
from ..TradeBu.ABuKLManager import AbuKLManager
from ..CoreBu.ABuFixes import ThreadPoolExecutor

__author__ = '阿布'
__weixin__ = 'abu_quant'

"""
本模块 `ABuPickStockExecute.py` 的主要功能是包装和分发选股任务，支持多线程和多进程的选股操作，并与选股工作者 AbuPickStockWorker 进行解耦。

主要作用说明：
- 提供了 `do_pick_stock_work` 方法：包装一次完整的选股流程，实例化 AbuPickStockWorker，调用其 fit() 方法得到选股结果。
- 提供了 `do_pick_stock_thread_work` 方法：利用线程池（ThreadPoolExecutor）并发地对股票池做分割选股，提升大规模选股时的效率。
- 这些方法都通过 `add_process_env_sig` 装饰器保证在多进程/多线程下环境变量的正确设置。
- 依赖 split_k_market 将股票池均匀分配到各线程/进程；依赖 AbuKLManager 和 ABuPickStockWorker 实现具体选股逻辑。

关于 Python 3 优化建议：
- 目前代码已采用 Python 3 写法（如 ThreadPoolExecutor, with 语法），无需兼容 Python 2。
- 可以适当去除 `from __future__` 的相关导入（absolute_import, print_function, division），在只支持 Python 3 的情况下，这些已是默认行为。
- `ThreadPoolExecutor` as pool 的写法是规范的，future 回调 (add_done_callback) 方式更高效地整合线程结果，不影响主线程流畅运行。
- 如果进一步追求性能，对 I/O 较重的任务，线程池是合适的；如需 CPU 密集型操作可考虑进程池（concurrent.futures.ProcessPoolExecutor）。
- Python 3.7+ 支持 contextvars，可以让 add_process_env_sig 装饰器以及各类并行任务对环境变量的管理更精细，但此处不强制要求更改。
- 若并发规模极大，后期可考虑分布式任务队列等高级优化，但目前这一代码结构对于普通选股并发任务已经简洁高效。

结论：本模块代码结构已较为现代化且合理，在 Python 3 环境下使用无需更改。如无其它兼容性要求，可移除 `from __future__` 相关兼容导入，使代码更清晰。
"""



@add_process_env_sig
def do_pick_stock_work(choice_symbols, benchmark, capital, stock_pickers):
    """
    包装AbuPickStockWorker进行选股
    :param choice_symbols: 初始备选交易对象序列
    :param benchmark: 交易基准对象，AbuBenchmark实例对象
    :param capital: 资金类AbuCapital实例化对象
    :param stock_pickers: 选股因子序列
    :return:
    """
    kl_pd_manager = AbuKLManager(benchmark, capital)
    stock_pick = AbuPickStockWorker(capital, benchmark, kl_pd_manager, choice_symbols=choice_symbols,
                                    stock_pickers=stock_pickers)
    stock_pick.fit()
    return stock_pick.choice_symbols


@add_process_env_sig
def do_pick_stock_thread_work(choice_symbols, benchmark, capital, stock_pickers, n_thread):
    """包装AbuPickStockWorker启动线程进行选股"""
    result = []

    def when_thread_done(r):
        result.extend(r.result())

    with ThreadPoolExecutor(max_workers=n_thread) as pool:
        thread_symbols = split_k_market(n_thread, market_symbols=choice_symbols)
        for symbols in thread_symbols:
            future_result = pool.submit(do_pick_stock_work, symbols, benchmark, capital, stock_pickers)
            future_result.add_done_callback(when_thread_done)

    return result
