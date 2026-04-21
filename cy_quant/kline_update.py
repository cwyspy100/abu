# -*- coding: utf-8 -*-
"""
将 A 股 K 线（约 n_folds 年）拉取并写入 abupy CSV 缓存目录，默认与文档一致：~/abu/data/csv。

用法（项目根目录，PYTHONPATH 含当前目录）::

  # 全市场约 1 年（耗时较长）
  python -m cy_quant.kline_update --full --n-folds 1

  # 仅更新池内股票（如 120 均线池），约 1 年
  python -m cy_quant.kline_update --pool cy_quant/sh_120ma.csv --n-folds 1

说明：底层使用 abupy 的 ``abu.run_kl_update`` 或 ``kl_df_dict_parallel``，
写入路径由 ``ABuEnv.g_project_kl_df_data_csv`` 决定（默认可通过 ``--data-root`` 覆盖为 ~/abu/data）。
"""

from __future__ import annotations

import argparse
import os
import sys


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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="更新 K 线到 ~/abu/data/csv（abupy CSV 缓存）")
    p.add_argument(
        "--data-root",
        default="~/abu/data",
        help="数据根目录，默认可展开为 ~/abu/data，CSV 在 其下 csv/",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--full", action="store_true", help="全市场 A 股（耗时长）")
    g.add_argument("--pool", metavar="CSV", help="仅更新池内 ts_code（CSV 含 ts_code 列）")
    p.add_argument(
        "--n-folds",
        type=float,
        default=1.0,
        help="请求约多少年的历史（默认 1 年）",
    )
    p.add_argument("--n-jobs", type=int, default=8, help="并行任务数")
    p.add_argument("--how", choices=("thread", "process", "main"), default="thread")
    args = p.parse_args(argv)

    _ensure_sys_path()
    # 先设路径再 import abupy（env 模块已加载，但后续写文件用 ABuEnv 运行时值）
    _apply_data_root(args.data_root)

    import abupy
    from abupy import EDataCacheType, EMarketSourceType, EMarketTargetType

    abupy.env.disable_example_env_ipython()
    abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_tx
    abupy.env.g_data_cache_type = EDataCacheType.E_DATA_CACHE_CSV
    abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_CN

    from abupy.CoreBu import ABuEnv

    print("CSV 目录: %s" % ABuEnv.g_project_kl_df_data_csv)

    if args.full:
        run_full_market(args.n_folds, args.n_jobs, args.how)
    else:
        run_pool_only(args.pool, args.n_folds, args.n_jobs, args.how)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
