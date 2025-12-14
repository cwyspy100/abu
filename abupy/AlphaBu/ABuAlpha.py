
# noinspection PyUnresolvedReferences
from .ABuPickStockExecute import do_pick_stock_work
# noinspection PyUnresolvedReferences
from .ABuPickTimeExecute import do_symbols_with_same_factors, do_symbols_with_diff_factors
# noinspection all
from . import ABuPickTimeWorker as pick_time_worker

# 这个文件是 AlphaBu 模块的 ABuAlpha.py 文件，主要作用是定义了一个名为 alpha 的模块，
# 其中包含了 AbuPickTimeWorker 和 pick_time_worker 两个子模块。
# 通过 from . import ABuPickTimeWorker as pick_time_worker 的导入方式，
# 可以方便地在其他模块中使用 AbuPickTimeWorker 和 pick_time_worker 的功能。
# 同时，noinspection all 注解用于抑制 pylint 对导入模块的警告。

"""
__init__ 和 ABuAlpha 的区别如下：

1. __init__.py 是 Python 包的初始化文件。它的作用是表明包含它的文件夹是一个 Python 包，可以用来做包的初始化工作，例如导入子模块、设置包的元数据等。__init__.py 文件在包被导入时自动执行。

2. ABuAlpha.py 是包中的一个普通模块文件。它实现具体功能，比如定义变量、类、函数等。在 ABuAlpha.py 里导入其他子模块，或者被其他模块导入时，只会执行 ABuAlpha.py 中定义的内容。

简而言之，__init__ 主要用于定义包的初始化行为；而 ABuAlpha 只是一个包中的普通模块，承载具体功能代码。

关于“ABuAlpha目前有用吗”：
ABuAlpha.py 目前的主要作用是集中导入和暴露 AbuPickStockExecute、AbuPickTimeExecute 及 AbuPickTimeWorker 等子模块的功能，方便其他模块统一导入和使用
（如 from AlphaBu.ABuAlpha import ...）。如果项目中其它地方通过 ABuAlpha.py 来统一调用选股、择时等功能模块，
那么它是有用的；否则，如果没有其他模块引用这里提供的接口或者这些功能已经在其它地方集中管理，则 ABuAlpha.py 的作用会比较有限。
所以其是否有用，要看项目整体结构和具体用法。如果后续设计需要集中管理模块暴露，ABuAlpha.py 会是有用的结构出口。
"""

