# -*- encoding:utf-8 -*-
"""
动量规则链：选股 + 回测（参考 python/c8.py，拆成两阶段便于单独断点调试）。

- **run_momo_pick_only**：仅选股（AbuPickStockWorker，同 c8 sample_821_1），返回标的列表。
- **run_momo_backtest_only**：仅择时回测；``stock_picks=None`` 时对 ``choice_symbols`` 不再二次选股。
- **main**：``stage='all'`` 先 pick 再 backtest；``stage='pick'`` / ``stage='backtest'`` 单跑一阶段。
- **main_pick / main_backtest / main_all**：与 ``main`` 参数相同，在代码里直接换函数名即可（无需改 ``stage``）。
- **main_pick** 默认对当前市场**全表**选股，并只保留**本地已有 CSV** 的标的；返回的 ``list`` 可直接 ``main_backtest(picked_symbols=...)``。
  本地 CSV 过滤已改为**一次扫描目录**（abu 自带按标的 ``listdir`` 为 O(标的×文件)，极慢）。

**IDE 调试**：改文件底部 ``_DEBUG_KWARGS``，并在 ``if __name__`` 里选用 ``main_pick`` / ``main_backtest`` / ``main_all``。

命令行::

  python cy_quant/run_abu_momo_rule_backtest.py --stage pick hk
  python cy_quant/run_abu_momo_rule_backtest.py --stage backtest hk --picked-csv /path/picked.csv

环境变量：ABU_DATA_SOURCE、ABU_CSV_DIR

回测前打印「为何满足/不满足选股与择时条件」：``main_backtest(..., explain_strategy=True)`` 或命令行 ``--explain-strategy``。
"""

from __future__ import print_function

import argparse
import logging
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd

import abupy
from abupy import abu
from abupy import ABuMarket
import abupy.CoreBu.ABuEnv as _abu_env_mod
from abupy.CoreBu.ABuEnv import EMarketSourceType, EMarketTargetType
from abupy.MarketBu.ABuSymbol import IndexSymbol
from abupy.MetricsBu.ABuMetricsBase import AbuMetricsBase
from abupy.FactorSellBu.ABuFactorAtrNStop import AbuFactorAtrNStop
from abupy.TradeBu.ABuBenchmark import AbuBenchmark
from abupy.TradeBu.ABuCapital import AbuCapital
from abupy.TradeBu.ABuKLManager import AbuKLManager
from abupy.AlphaBu.ABuPickStockWorker import AbuPickStockWorker
from abupy.UtilBu import ABuProgress

from cy_quant.Analyze120MA import Analyze120MA
from cy_quant.abu_local_csv_config import configure_abu_data_source, configure_from_environ
from cy_quant.abu_momo_rule_factors import (
    AbuPickRuleMomentumBreakoutComp,
    AbuFactorBuyDualHighBreak,
    AbuRiskPctAtrPosition,
    AbuFactorSellTrendLowBreak,
    dual_high_break_diagnose_lines,
    momentum_pick_diagnose_lines,
)

STAGE_PICK = "pick"
STAGE_BACKTEST = "backtest"
STAGE_ALL = "all"

_MARKET_TARGET = {
    "cn": EMarketTargetType.E_MARKET_TARGET_CN,
    "us": EMarketTargetType.E_MARKET_TARGET_US,
    "hk": EMarketTargetType.E_MARKET_TARGET_HK,
}
_BENCH_SYMBOL = {
    "cn": IndexSymbol.SH.value,
    "us": IndexSymbol.IXIC.value,
    "hk": IndexSymbol.HSI.value,
}
_DEFAULT_CHOICE_SMALL = {
    "cn": ["sh600519", "sh600036", "sz000001", "sz300750"],
    "us": ["usAAPL", "usMSFT", "usGOOGL", "usAMZN", "usNVDA", "usMETA", "usTSLA"],
    "hk": ["hk00700", "hk09988", "hk03690", "hk01810", "hk00939", "hk09926"],
}


def symbols_from_input_csv(path):
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        raise IOError("input_csv not found: %s" % path)
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        df = pd.read_csv(path, encoding="gbk")
    if df.empty or "ts_code" not in df.columns:
        raise ValueError("input_csv 需为非空表且含 ts_code 列")
    out = []
    seen = set()
    for x in df["ts_code"].dropna().unique():
        p = Analyze120MA._stock_input_to_file_prefix(str(x).strip())
        if not p:
            continue
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def symbols_from_picked_csv(path):
    """回测阶段使用的已选标的表：须含 ts_code，格式同 symbols_from_input_csv。"""
    return symbols_from_input_csv(path)


def _ensure_logging(verbose):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("run_abu_momo_rule")


def _active_kline_csv_dir():
    """与 ABuDataCache._load_csv_key 一致：当前应扫描的日 K CSV 根目录。"""
    if getattr(_abu_env_mod, "_g_enable_example_env_ipython", False):
        return _abu_env_mod.g_project_kl_df_data_example
    return _abu_env_mod.g_project_kl_df_data_csv


def scan_kline_csv_symbol_index(csv_dir=None):
    """
    一次 ``listdir`` 建立「已有本地日 K CSV」的 symbol 集合。

    abu 自带的 ``check_symbol_in_local_csv`` 内部对每个标的都会 ``os.listdir`` 整个目录，
    全市场过滤时复杂度约为 O(标的数 × 文件数)，极慢；此处改为 O(文件数)。
    命名约定与 ``_load_csv_key`` 一致：文件名 ``{symbol_key}_{...}``。

    :return: (symbol_prefix_set, n_files_in_dir)
    """
    root = csv_dir or _active_kline_csv_dir()
    if not root or not os.path.isdir(root):
        return set(), 0
    found = set()
    n_files = 0
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if os.path.isdir(path):
            continue
        n_files += 1
        if "_" not in name:
            continue
        found.add(name.split("_", 1)[0])
    return found, n_files


def log_picked_symbols_for_backtest(picked, market, log):
    """逐条打印入选标的，便于复制为单标的 ``main_backtest`` 调用。"""
    sep = "======== picked %d symbols market=%s ========" % (len(picked), market)
    log.info(sep)
    print(sep)
    for i, sym in enumerate(picked, 1):
        line = (
            "[%d/%d] %s  |  main_backtest(market=%r, picked_symbols=[%r], "
            "verbose=True, data_source=\"local\")"
            % (i, len(picked), sym, market, sym)
        )
        log.info(line)
        print(line)
    end = "======== end picked list ========"
    log.info(end)
    print(end)


def momo_apply_data_source(verbose, data_source, csv_dir):
    log = _ensure_logging(verbose)
    env_local, env_csv = configure_from_environ()
    if data_source == "network":
        local_only = False
    elif data_source == "local":
        local_only = True
    else:
        local_only = True if env_local is None else env_local
    csv_eff = csv_dir or env_csv
    configure_abu_data_source(
        local_csv_only=local_only,
        csv_dir=csv_eff,
        market_source=EMarketSourceType.E_MARKET_SOURCE_tx,
        use_csv_cache=True,
    )
    log.info(
        "data switch: local_only=%s csv_dir=%s",
        local_only,
        csv_eff or "(default ~/abu/data/csv)",
    )
    return log


def momo_resolve_universe(
    market_key, bench_sym, all_symbols, input_csv, log, local_csv_only=False
):
    if input_csv:
        syms = symbols_from_input_csv(input_csv)
        syms = [s for s in syms if s != bench_sym]
        log.info(
            "universe input_csv: %s -> %d (ex bench %s)",
            input_csv,
            len(syms),
            bench_sym,
        )
        return syms
    if all_symbols:
        syms = list(ABuMarket.all_symbol())
        syms = [s for s in syms if s != bench_sym]
        if local_csv_only:
            listed_n = len(syms)
            log.info("local_csv scan root: %s", _active_kline_csv_dir())
            t0 = time.time()
            csv_index, n_csv_files = scan_kline_csv_symbol_index()
            syms = [s for s in syms if s in csv_index]
            elapsed = time.time() - t0
            log.warning(
                "universe ALL ∩ local_csv market=%s n=%d (listed %d, "
                "csv_dir_files=%d csv_symbol_keys=%d scan %.2fs)",
                market_key,
                len(syms),
                listed_n,
                n_csv_files,
                len(csv_index),
                elapsed,
            )
        else:
            log.warning("universe ALL listed market=%s n=%d", market_key, len(syms))
        return syms
    syms = list(_DEFAULT_CHOICE_SMALL[market_key])
    log.info("universe small-sample market=%s n=%d", market_key, len(syms))
    return syms


def momo_stock_picker_specs(
    progress_every,
    bench_ma_n,
    stock_ma_n,
    rs_lookback_n,
    rs_top_pct,
    atr_short_n,
    atr_long_n,
    pick_xd,
):
    return [
        {
            "class": AbuPickRuleMomentumBreakoutComp,
            "first_choice": True,
            "bench_ma_n": bench_ma_n,
            "stock_ma_n": stock_ma_n,
            "rs_lookback_n": rs_lookback_n,
            "rs_top_pct": rs_top_pct,
            "atr_short_n": atr_short_n,
            "atr_long_n": atr_long_n,
            "xd": pick_xd,
            "progress_every": progress_every,
        }
    ]


def momo_buy_sell_specs(
    xd_short,
    xd_long,
    risk_pct,
    stop_atr_mult,
    stop_loss_n,
    sell_low_n,
):
    buy_factors = [
        {
            "class": AbuFactorBuyDualHighBreak,
            "xd_short": xd_short,
            "xd_long": xd_long,
            "position": {
                "class": AbuRiskPctAtrPosition,
                "risk_pct": risk_pct,
                "stop_atr_mult": stop_atr_mult,
                "risk_basis": "initial",
            },
        }
    ]
    sell_factors = [
        {"stop_loss_n": stop_loss_n, "class": AbuFactorAtrNStop},
        {"low_n": sell_low_n, "class": AbuFactorSellTrendLowBreak},
    ]
    return buy_factors, sell_factors


def run_momo_pick_only(
    market="cn",
    all_symbols=False,
    local_csv_only=False,
    input_csv=None,
    progress_every=None,
    verbose=False,
    data_source=None,
    csv_dir=None,
    read_cash=1_000_000,
    n_folds=2,
    bench_ma_n=120,
    stock_ma_n=120,
    rs_lookback_n=60,
    rs_top_pct=0.2,
    atr_short_n=20,
    atr_long_n=60,
    pick_xd=252,
):
    """
    仅选股（c8 sample_821_1 方式）：AbuPickStockWorker.fit()，返回入选代码列表。

    ``all_symbols=True`` 时使用当前市场完整代码表（A股/港股/美股由 ``market`` 决定）。
    ``local_csv_only=True`` 时在上面的集合上再筛一层：仅保留本地已有日 K CSV 的标的（适合纯本地回测）。
    """
    if market not in _MARKET_TARGET:
        raise ValueError("market must be cn|us|hk")
    log = momo_apply_data_source(verbose, data_source, csv_dir)
    abupy.env.g_market_target = _MARKET_TARGET[market]
    bench_sym = _BENCH_SYMBOL[market]
    universe = momo_resolve_universe(
        market, bench_sym, all_symbols, input_csv, log, local_csv_only=local_csv_only
    )
    prog = progress_every
    if prog is None:
        prog = 500 if (all_symbols and not input_csv) else 50
    stock_pickers = momo_stock_picker_specs(
        prog, bench_ma_n, stock_ma_n, rs_lookback_n, rs_top_pct, atr_short_n, atr_long_n, pick_xd
    )
    benchmark = AbuBenchmark(n_folds=n_folds)
    capital = AbuCapital(read_cash, benchmark)
    kl_pd_manager = AbuKLManager(benchmark, capital)
    worker = AbuPickStockWorker(
        capital,
        benchmark,
        kl_pd_manager,
        choice_symbols=universe,
        stock_pickers=stock_pickers,
    )
    log.info("run_momo_pick_only: universe=%d", len(universe))
    worker.fit()
    picked = list(worker.choice_symbols) if worker.choice_symbols else []
    log.info("run_momo_pick_only: picked n=%d", len(picked))
    print("[run_momo_pick_only] n=%d: %s" % (len(picked), ", ".join(picked)))
    log_picked_symbols_for_backtest(picked, market, log)
    return picked


def log_momo_strategy_explain(
    choice_symbols,
    market,
    log,
    n_folds,
    read_cash,
    pick_xd,
    bench_ma_n,
    stock_ma_n,
    rs_lookback_n,
    rs_top_pct,
    atr_short_n,
    atr_long_n,
    xd_short,
    xd_long,
):
    """
    在 ``run_loop_back`` 之前，按与 ``main_pick`` / 回测相同的参数，打印：

    - **选股条件**（``AbuPickRuleMomentumBreakoutComp``）：逐项 √ / × / …
    - **择时条件**（``AbuFactorBuyDualHighBreak``）：截至最后一根 K 是否触发「次日买」

    RS「top 分位」为截面规则，单股只打印涨幅，无法单独判定是否进 pick 名单。
    """
    bench_sym = _BENCH_SYMBOL[market]
    benchmark = AbuBenchmark(n_folds=n_folds)
    capital = AbuCapital(read_cash, benchmark)
    kl_pd_manager = AbuKLManager(benchmark, capital)
    banner = "======== 策略条件诊断（回测前；√=满足 ×=不满足 …=仅信息）========"
    log.info(banner)
    print(banner)
    for sym in choice_symbols:
        sep = "---- %s ----" % sym
        log.info(sep)
        print(sep)
        for line in momentum_pick_diagnose_lines(
            sym,
            bench_sym,
            kl_pd_manager,
            pick_xd=pick_xd,
            bench_ma_n=bench_ma_n,
            stock_ma_n=stock_ma_n,
            rs_lookback_n=rs_lookback_n,
            rs_top_pct=rs_top_pct,
            atr_short_n=atr_short_n,
            atr_long_n=atr_long_n,
        ):
            log.info(line)
            print(line)
        for line in dual_high_break_diagnose_lines(
            sym, kl_pd_manager, pick_xd, xd_short, xd_long
        ):
            log.info(line)
            print(line)


def run_momo_backtest_only(
    choice_symbols,
    market="cn",
    verbose=False,
    data_source=None,
    csv_dir=None,
    read_cash=1_000_000,
    n_folds=2,
    bench_ma_n=120,
    stock_ma_n=120,
    rs_lookback_n=60,
    rs_top_pct=0.2,
    atr_short_n=20,
    atr_long_n=60,
    pick_xd=252,
    xd_short=20,
    xd_long=55,
    risk_pct=0.01,
    stop_atr_mult=1.0,
    stop_loss_n=1.0,
    sell_low_n=20,
    show_metrics=True,
    explain_strategy=False,
):
    """
    仅回测：对已有 ``choice_symbols`` 择时；``stock_picks=None`` 不再跑选股因子。

    ``explain_strategy=True``：先打印与 ``main_pick`` 一致的选股条件逐项结果，以及择时 dual-high
    在**最后一根 K** 上的快照（不替代回测逐日逻辑；历史成交请看 orders_pd）。
    """
    if market not in _MARKET_TARGET:
        raise ValueError("market must be cn|us|hk")
    if not choice_symbols:
        logging.getLogger("run_abu_momo_rule").warning("run_momo_backtest_only: empty choice_symbols")
        return None
    log = momo_apply_data_source(verbose, data_source, csv_dir)
    abupy.env.g_market_target = _MARKET_TARGET[market]
    if explain_strategy:
        log_momo_strategy_explain(
            choice_symbols,
            market,
            log,
            n_folds=n_folds,
            read_cash=read_cash,
            pick_xd=pick_xd,
            bench_ma_n=bench_ma_n,
            stock_ma_n=stock_ma_n,
            rs_lookback_n=rs_lookback_n,
            rs_top_pct=rs_top_pct,
            atr_short_n=atr_short_n,
            atr_long_n=atr_long_n,
            xd_short=xd_short,
            xd_long=xd_long,
        )
    buy_factors, sell_factors = momo_buy_sell_specs(
        xd_short, xd_long, risk_pct, stop_atr_mult, stop_loss_n, sell_low_n
    )
    log.info(
        "run_momo_backtest_only: symbols=%d (no stock_picks)",
        len(choice_symbols),
    )
    abu_result_tuple, _kl = abu.run_loop_back(
        read_cash,
        buy_factors,
        sell_factors,
        stock_picks=None,
        choice_symbols=list(choice_symbols),
        n_folds=n_folds,
    )
    if abu_result_tuple is None:
        log.warning("backtest: no result")
        return None
    orders_n = (
        len(abu_result_tuple.orders_pd)
        if abu_result_tuple.orders_pd is not None
        else 0
    )
    log.info("backtest done orders_pd rows=%d", orders_n)
    if show_metrics:
        ABuProgress.do_clear_output(wait=False)
        metrics = AbuMetricsBase(*abu_result_tuple)
        metrics.fit_metrics()
        AbuMetricsBase.show_general(*abu_result_tuple, only_show_returns=True)
    return abu_result_tuple


def main(
    market="cn",
    stage=STAGE_ALL,
    picked_symbols=None,
    picked_csv=None,
    all_symbols=False,
    local_csv_only=False,
    input_csv=None,
    progress_every=None,
    verbose=False,
    data_source=None,
    csv_dir=None,
    read_cash=1_000_000,
    n_folds=2,
    bench_ma_n=120,
    stock_ma_n=120,
    rs_lookback_n=60,
    rs_top_pct=0.2,
    atr_short_n=20,
    atr_long_n=60,
    pick_xd=252,
    xd_short=20,
    xd_long=55,
    risk_pct=0.01,
    stop_atr_mult=1.0,
    stop_loss_n=1.0,
    sell_low_n=20,
    show_metrics=True,
    explain_strategy=False,
):
    """
    :param stage: 'pick' | 'backtest' | 'all'
    :param picked_symbols: stage=backtest 时直接传入列表；若 None 可用 picked_csv
    :param picked_csv: stage=backtest 时从含 ts_code 的 CSV 读入已选标的
    :param all_symbols: pick / all 阶段是否用全市场代码表作候选池（见 ``local_csv_only``）
    :param local_csv_only: 在 ``all_symbols=True`` 时是否只保留本地已有日 K CSV 的标的

    若希望「在代码里一眼看出跑哪段」，可改用 ``main_pick`` / ``main_backtest`` / ``main_all``，
    参数与本函数相同（不必再传 ``stage``）。``main_pick`` 默认全市场且只筛本地有 CSV 的标的；
    返回值可直接作 ``main_backtest(..., picked_symbols=...)``。
    :param explain_strategy: ``stage=backtest|all`` 时传入 ``run_momo_backtest_only``：回测前打印选股/择时条件诊断。
    """
    if stage not in (STAGE_PICK, STAGE_BACKTEST, STAGE_ALL):
        raise ValueError("stage must be pick|backtest|all")

    if stage == STAGE_PICK:
        return run_momo_pick_only(
            market=market,
            all_symbols=all_symbols,
            local_csv_only=local_csv_only,
            input_csv=input_csv,
            progress_every=progress_every,
            verbose=verbose,
            data_source=data_source,
            csv_dir=csv_dir,
            read_cash=read_cash,
            n_folds=n_folds,
            bench_ma_n=bench_ma_n,
            stock_ma_n=stock_ma_n,
            rs_lookback_n=rs_lookback_n,
            rs_top_pct=rs_top_pct,
            atr_short_n=atr_short_n,
            atr_long_n=atr_long_n,
            pick_xd=pick_xd,
        )

    if stage == STAGE_BACKTEST:
        syms = picked_symbols
        if (not syms) and picked_csv:
            syms = symbols_from_picked_csv(picked_csv)
            bench = _BENCH_SYMBOL[market]
            syms = [s for s in syms if s != bench]
        if not syms:
            raise ValueError("stage=backtest 需要 picked_symbols 或 picked_csv")
        return run_momo_backtest_only(
            syms,
            market=market,
            verbose=verbose,
            data_source=data_source,
            csv_dir=csv_dir,
            read_cash=read_cash,
            n_folds=n_folds,
            bench_ma_n=bench_ma_n,
            stock_ma_n=stock_ma_n,
            rs_lookback_n=rs_lookback_n,
            rs_top_pct=rs_top_pct,
            atr_short_n=atr_short_n,
            atr_long_n=atr_long_n,
            pick_xd=pick_xd,
            xd_short=xd_short,
            xd_long=xd_long,
            risk_pct=risk_pct,
            stop_atr_mult=stop_atr_mult,
            stop_loss_n=stop_loss_n,
            sell_low_n=sell_low_n,
            show_metrics=show_metrics,
            explain_strategy=explain_strategy,
        )

    # STAGE_ALL: 先选股再回测（回测阶段不再选股）
    picked = run_momo_pick_only(
        market=market,
        all_symbols=all_symbols,
        local_csv_only=local_csv_only,
        input_csv=input_csv,
        progress_every=progress_every,
        verbose=verbose,
        data_source=data_source,
        csv_dir=csv_dir,
        read_cash=read_cash,
        n_folds=n_folds,
        bench_ma_n=bench_ma_n,
        stock_ma_n=stock_ma_n,
        rs_lookback_n=rs_lookback_n,
        rs_top_pct=rs_top_pct,
        atr_short_n=atr_short_n,
        atr_long_n=atr_long_n,
        pick_xd=pick_xd,
    )
    if not picked:
        _ensure_logging(verbose).warning("pick empty, skip backtest")
        return None
    return run_momo_backtest_only(
        picked,
        market=market,
        verbose=verbose,
        data_source=data_source,
        csv_dir=csv_dir,
        read_cash=read_cash,
        n_folds=n_folds,
        bench_ma_n=bench_ma_n,
        stock_ma_n=stock_ma_n,
        rs_lookback_n=rs_lookback_n,
        rs_top_pct=rs_top_pct,
        atr_short_n=atr_short_n,
        atr_long_n=atr_long_n,
        pick_xd=pick_xd,
        xd_short=xd_short,
        xd_long=xd_long,
        risk_pct=risk_pct,
        stop_atr_mult=stop_atr_mult,
        stop_loss_n=stop_loss_n,
        sell_low_n=sell_low_n,
        show_metrics=show_metrics,
        explain_strategy=explain_strategy,
    )


def main_pick(**kwargs):
    """
    全市场选股入口（A股/港股/美股由 ``market`` 决定）：

    - 默认 ``all_symbols=True``：候选池为当前市场完整代码表；
    - 默认 ``local_csv_only=True``：只保留本地已有日 K CSV 的标的（与「本地全量可回测股票」对齐）。

    返回 ``list`` 可直接传入 ``main_backtest(..., picked_symbols=...)``。
    若要用官方代码表里「未下载 CSV」的标的，可 ``main_pick(local_csv_only=False)``（本地模式可能缺数据）。
    """
    kwargs.pop("stage", None)
    if "all_symbols" not in kwargs:
        kwargs["all_symbols"] = True
    if "local_csv_only" not in kwargs:
        kwargs["local_csv_only"] = True
    return main(stage=STAGE_PICK, **kwargs)


def main_backtest(**kwargs):
    """
    直接回测（等价 ``main(..., stage='backtest')``）。须提供 ``picked_symbols`` 或 ``picked_csv``。

    单股排查条件时加 ``explain_strategy=True``：回测前打印选股/择时规则逐项是否满足（见 ``log_momo_strategy_explain``）。
    """
    kwargs.pop("stage", None)
    return main(stage=STAGE_BACKTEST, **kwargs)


def main_all(**kwargs):
    """
    先选股再回测（等价 ``main(..., stage='all')``，也是 ``main`` 默认行为）。
    """
    kwargs.pop("stage", None)
    return main(stage=STAGE_ALL, **kwargs)


def build_arg_parser():
    p = argparse.ArgumentParser(description="动量规则：选股 / 回测 分阶段（对齐 c8 思路）")
    p.add_argument(
        "market",
        nargs="?",
        default="cn",
        choices=("cn", "us", "hk"),
        help="市场",
    )
    p.add_argument(
        "--stage",
        choices=(STAGE_PICK, STAGE_BACKTEST, STAGE_ALL),
        default=STAGE_ALL,
        help="pick=仅选股；backtest=仅回测；all=先选股再回测（默认）",
    )
    p.add_argument(
        "--picked-csv",
        default=None,
        dest="picked_csv",
        help="stage=backtest 时：已选标的 CSV（含 ts_code）",
    )
    p.add_argument(
        "--input-csv",
        default=None,
        dest="input_csv",
        help="候选池 CSV（含 ts_code）；pick / all 时用",
    )
    p.add_argument("--all-symbols", action="store_true", dest="all_symbols")
    p.add_argument(
        "--pick-local-csv-only",
        action="store_true",
        dest="pick_local_csv_only",
        help="与 --all-symbols 合用：候选池仅保留本地已有日K CSV 的标的",
    )
    p.add_argument("--progress-every", type=int, default=None, dest="progress_every")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--data-source", choices=("local", "network"), default=None, dest="data_source")
    p.add_argument("--csv-dir", default=None, dest="csv_dir")
    p.add_argument("--cash", type=float, default=1_000_000, dest="read_cash")
    p.add_argument("--n-folds", type=int, default=2, dest="n_folds")
    p.add_argument("--bench-ma-n", type=int, default=120, dest="bench_ma_n")
    p.add_argument("--stock-ma-n", type=int, default=120, dest="stock_ma_n")
    p.add_argument("--rs-lookback-n", type=int, default=60, dest="rs_lookback_n")
    p.add_argument("--rs-top-pct", type=float, default=0.2, dest="rs_top_pct")
    p.add_argument("--pick-xd", type=int, default=252, dest="pick_xd")
    p.add_argument("--atr-short-n", type=int, default=20, dest="atr_short_n")
    p.add_argument("--atr-long-n", type=int, default=60, dest="atr_long_n")
    p.add_argument("--xd-short", type=int, default=20, dest="xd_short")
    p.add_argument("--xd-long", type=int, default=55, dest="xd_long")
    p.add_argument("--risk-pct", type=float, default=0.01, dest="risk_pct")
    p.add_argument("--stop-atr-mult", type=float, default=1.0, dest="stop_atr_mult")
    p.add_argument("--stop-loss-n", type=float, default=1.0, dest="stop_loss_n")
    p.add_argument("--sell-low-n", type=int, default=20, dest="sell_low_n")
    p.add_argument("--no-metrics", action="store_true", dest="no_metrics", help="backtest 阶段不输出 AbuMetrics 汇总")
    p.add_argument(
        "--explain-strategy",
        action="store_true",
        dest="explain_strategy",
        help="backtest 前打印选股+择时条件诊断（与 main_pick / 回测参数对齐）",
    )
    return p


def _main_cli(argv=None):
    args = build_arg_parser().parse_args(argv)
    return main(
        market=args.market,
        stage=args.stage,
        picked_csv=args.picked_csv,
        all_symbols=args.all_symbols,
        local_csv_only=args.pick_local_csv_only,
        input_csv=args.input_csv,
        progress_every=args.progress_every,
        verbose=args.verbose,
        data_source=args.data_source,
        csv_dir=args.csv_dir,
        read_cash=args.read_cash,
        n_folds=args.n_folds,
        bench_ma_n=args.bench_ma_n,
        stock_ma_n=args.stock_ma_n,
        rs_lookback_n=args.rs_lookback_n,
        rs_top_pct=args.rs_top_pct,
        atr_short_n=args.atr_short_n,
        atr_long_n=args.atr_long_n,
        pick_xd=args.pick_xd,
        xd_short=args.xd_short,
        xd_long=args.xd_long,
        risk_pct=args.risk_pct,
        stop_atr_mult=args.stop_atr_mult,
        stop_loss_n=args.stop_loss_n,
        sell_low_n=args.sell_low_n,
        show_metrics=not args.no_metrics,
        explain_strategy=args.explain_strategy,
    )


# IDE：改 stage / market / picked_symbols 等后 Run；无需命令行。
_DEBUG_KWARGS = dict(
    market="hk",
    stage=STAGE_ALL,
    picked_symbols=None,
    picked_csv=None,
    all_symbols=False,
    input_csv=None,
    progress_every=None,
    verbose=True,
    data_source="local",
    csv_dir=None,
    read_cash=1_000_000,
    n_folds=2,
    bench_ma_n=120,
    stock_ma_n=120,
    rs_lookback_n=60,
    rs_top_pct=0.2,
    atr_short_n=20,
    atr_long_n=60,
    pick_xd=252,
    xd_short=20,
    xd_long=55,
    risk_pct=0.01,
    stop_atr_mult=1.0,
    stop_loss_n=1.0,
    sell_low_n=20,
    show_metrics=True,
    explain_strategy=False,
)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        _main_cli(sys.argv[1:])
    else:
        # 单股回测并打印「选股+择时」条件是否满足：加 explain_strategy=True
        main_backtest(
            market="hk",
            picked_symbols=["hk00700"],
            verbose=True,
            data_source="local",
            explain_strategy=True,
        )
        # main_all(**_DEBUG_KWARGS)

