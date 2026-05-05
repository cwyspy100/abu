# -*- coding: utf-8 -*-
"""
将 A 股 K 线（约 n_folds 年）拉取并写入 abupy CSV 缓存目录，默认与文档一致：~/abu/data/csv。

用法（项目根目录，PYTHONPATH 含当前目录）::

  # 无参数：默认按 cy_quant/sh_120ma.csv 股票池更新约 1 年 K 线到 ~/abu/data/csv
  python -m cy_quant.kline_update

  # 全市场约 1 年（耗时较长）
  python -m cy_quant.kline_update --full --n-folds 1

  # 指定其它池
  python -m cy_quant.kline_update --pool path/to/pool.csv

在代码里直接传股票池（不走命令行解析）::

  from cy_quant.kline_update import main
  main(pool_csv="/绝对路径/或相对工作目录/sh_120ma.csv", n_folds=1.0)
  main(pool_csv="/path/pool.csv", data_root="~/abu/data", n_jobs=16)
  main(full=True, n_folds=1.0)  # 全市场

说明：底层使用 abupy 的 ``abu.run_kl_update`` 或 ``kl_df_dict_parallel``，
写入路径由 ``ABuEnv.g_project_kl_df_data_csv`` 决定（默认可通过 ``--data-root`` 覆盖为 ~/abu/data）。
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional


def _apply_data_root(data_root: str) -> None:
    """将 abupy 数据根目录设为 ~/abu/data，使 CSV 落在 ~/abu/data/csv。"""
    from abupy.CoreBu import ABuEnv

    root = os.path.expanduser(data_root)
    if os.path.basename(root.rstrip(os.sep)) == "data":
        data_dir = root
        project_root = os.path.dirname(data_dir)
    else:
        project_root = root
        data_dir = os.path.join(project_root, "data")

    ABuEnv.g_project_root = project_root
    ABuEnv.g_project_data_dir = data_dir
    ABuEnv.g_project_kl_df_data_csv = os.path.join(data_dir, "csv")
    os.makedirs(ABuEnv.g_project_kl_df_data_csv, exist_ok=True)


def _default_pool_csv() -> str:
    """与本模块同目录下的默认股票池（如 120 均线池）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "sh_120ma.csv"))


def _setup_abupy_common(data_root: str) -> None:
    """配置数据源与 CSV 目录后，再执行 run_full_market / run_pool_only。"""
    _apply_data_root(data_root)
    import abupy
    from abupy import EDataCacheType, EMarketSourceType, EMarketTargetType

    abupy.env.disable_example_env_ipython()
    abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_tx
    abupy.env.g_data_cache_type = EDataCacheType.E_DATA_CACHE_CSV
    abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_CN

    from abupy.CoreBu import ABuEnv

    print("CSV 目录: %s" % ABuEnv.g_project_kl_df_data_csv)


def _ensure_sys_path() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(os.path.join(here, ".."))
    if repo not in sys.path:
        sys.path.insert(0, repo)
    try:
        import abu_local_env  # noqa: F401
    except ImportError:
        pass


def run_full_market(n_folds: float, n_jobs: int, how: str) -> None:
    from abupy import abu, EMarketTargetType

    abu.run_kl_update(
        n_folds=n_folds,
        market=EMarketTargetType.E_MARKET_TARGET_CN,
        n_jobs=n_jobs,
        how=how,
    )


def run_pool_only(pool_csv: str, n_folds: float, n_jobs: int, how: str) -> None:
    from abupy import EDataCacheType, EMarketDataFetchMode, EMarketSourceType, EMarketTargetType
    from abupy.CoreBu import ABuEnv
    from abupy.MarketBu.ABuSymbolPd import kl_df_dict_parallel
    import abupy

    abupy.env.disable_example_env_ipython()
    abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_tx
    abupy.env.g_data_cache_type = EDataCacheType.E_DATA_CACHE_CSV
    abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_CN

    from cy_quant.monitor.pool_check import read_pool_codes
    from cy_quant.monitor.abupy_pool_scan import ts_code_to_abupy_symbol

    codes = read_pool_codes(pool_csv)
    symbols = []
    for c in codes:
        try:
            symbols.append(ts_code_to_abupy_symbol(c))
        except Exception as e:
            print("跳过 %s: %s" % (c, e), file=sys.stderr)

    if not symbols:
        print("无有效代码", file=sys.stderr)
        raise SystemExit(1)

    ABuEnv.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_FORCE_NET
    kl_df_dict_parallel(symbols, n_folds=n_folds, n_jobs=n_jobs, how=how, save=True)
    ABuEnv.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_FORCE_LOCAL
    print("已写入: %s" % ABuEnv.g_project_kl_df_data_csv)


def main(
    argv: Optional[List[str]] = None,
    *,
    pool_csv: Optional[str] = None,
    data_root: str = "~/abu/data",
    full: bool = False,
    n_folds: float = 1.0,
    n_jobs: int = 8,
    how: str = "thread",
) -> int:
    """
    更新 K 线到 abupy CSV 目录。

    - **命令行**：``main()`` 或 ``main(sys.argv[1:])``，未传 ``pool_csv`` 且 ``full`` 为 False 时解析 ``argv``。
    - **代码里直接传参**：``main(pool_csv="/path/to/pool.csv")`` 或 ``main(full=True)`` 时**不再解析命令行**，
      使用本函数传入的 ``pool_csv`` / ``full`` / ``n_folds`` 等。

    :param pool_csv: 股票池 CSV 路径（须含 ``ts_code`` 列）。与 ``full`` 二选一；为 None 且非全市场时用默认 ``cy_quant/sh_120ma.csv``。
    """
    _ensure_sys_path()

    # 显式传入 pool_csv，或 full=True 时，视为代码调用，不走路径解析
    use_cli = pool_csv is None and not full

    if use_cli:
        p = argparse.ArgumentParser(description="更新 K 线到 ~/abu/data/csv（abupy CSV 缓存）")
        p.add_argument(
            "--data-root",
            default="~/abu/data",
            help="数据根目录，CSV 在 其下 csv/",
        )
        p.add_argument("--full", action="store_true", help="全市场 A 股（耗时长）；不加则按股票池更新")
        p.add_argument(
            "--pool",
            default=None,
            metavar="CSV",
            help="股票池 CSV（须含 ts_code 列）；默认使用本包同目录 sh_120ma.csv",
        )
        p.add_argument(
            "--n-folds",
            type=float,
            default=1.0,
            help="请求约多少年的历史（默认 1 年）",
        )
        p.add_argument("--n-jobs", type=int, default=8, help="并行任务数")
        p.add_argument("--how", choices=("thread", "process", "main"), default="thread")
        if argv is None:
            argv = sys.argv[1:]
        args = p.parse_args(argv)
        data_root = args.data_root
        full = args.full
        n_folds = args.n_folds
        n_jobs = args.n_jobs
        how = args.how
        pool_csv = args.pool

    if not full:
        if pool_csv is None:
            pool_csv = _default_pool_csv()
        pool_csv = os.path.normpath(os.path.expanduser(pool_csv))
        if not os.path.isfile(pool_csv):
            print("未找到股票池文件: %s（请放置 sh_120ma.csv 或传入 pool_csv=）" % pool_csv, file=sys.stderr)
            return 1

    _setup_abupy_common(data_root)

    if full:
        run_full_market(n_folds, n_jobs, how)
    else:
        print("股票池: %s（约 %.1f 年）" % (pool_csv, n_folds))
        run_pool_only(pool_csv, n_folds, n_jobs, how)

    return 0


if __name__ == "__main__":
    # python -m cy_quant.kline_update --pool other.csv
    # python3.9 -m cy_quant.kline_update --pool cy_quant/sh_120ma.csv
    raise SystemExit(main())
