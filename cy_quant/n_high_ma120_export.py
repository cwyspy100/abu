# -*- coding: utf-8 -*-
"""
传入交易日天数 N：用最后一根 K 为「当天」，对比**不含当天**的前 N 个交易日最高价；
若当天收盘价 > 该最高价，则再计算「当前站上 120 日均线区间起点价 → 今日收盘」的涨幅，导出 CSV。

参考：Analyze120MA（120 日均线突破）、kline_update / monitor（股票池与 K 线路径）。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

# 保证可导入 cy_quant
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def _ensure_trade_date_str(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "trade_date" not in out.columns:
        return out
    td = out["trade_date"]
    if pd.api.types.is_datetime64_any_dtype(td):
        out["trade_date"] = td.dt.strftime("%Y%m%d")
    else:
        out["trade_date"] = td.astype(str).str.replace(r"[\s\-:]", "", regex=True).str.slice(0, 8)
    return out


def eval_one_stock(
    df: pd.DataFrame,
    n: int,
    analyzer: Any,
) -> Optional[Dict[str, Any]]:
    """
    :param df: 已含 trade_date, open, high, low, close，按日期升序
    :param n: 前 N 个交易日（不含当天）
    """
    if df is None or df.empty:
        return None
    df = df.sort_values("trade_date").reset_index(drop=True)
    need = max(121, n + 1)
    if len(df) < need:
        return None

    last = len(df) - 1
    if last < n:
        return None

    # 不含当天：前 N 根 K 线 high 的最高值 → 区间 [last-n, last-1]
    prev_max_high = float(df["high"].iloc[last - n : last].max())
    today_close = float(df["close"].iloc[last])
    last_date = df["trade_date"].iloc[last]

    if today_close <= prev_max_high:
        return None

    df_ma = analyzer.calculate_120ma(df)
    bt = analyzer.find_last_breakthrough(df_ma)
    if bt is None:
        return None

    start_date, start_price, _cur, growth_rate, trading_days = bt

    return {
        "last_trade_date": str(last_date),
        "today_close": round(today_close, 4),
        "prev_n_days": n,
        "prev_n_max_high": round(prev_max_high, 4),
        "n_day_high_break": True,
        "ma120_breakthrough_date": str(start_date),
        "price_at_ma120_segment_start": round(float(start_price), 4),
        "growth_pct_ma120_start_to_today": round(float(growth_rate), 4),
        "days_since_ma120_segment": int(trading_days),
    }


def scan_pool(
    pool_csv: str,
    out_csv: str,
    n: int,
    data_roots: Optional[List[str]] = None,
    *,
    export_all_attempts: bool = False,
) -> pd.DataFrame:
    from cy_quant.Analyze120MA import Analyze120MA
    from cy_quant.monitor.kline_loader import KlineLoader
    from cy_quant.monitor.pool_check import read_pool_codes

    roots = data_roots or [
        os.path.expanduser("~/abu/data/csv/astock"),
        os.path.expanduser("~/abu/data/csv"),
    ]
    loader = KlineLoader(data_roots=roots)
    analyzer = Analyze120MA(input_csv=None)
    codes = read_pool_codes(pool_csv)

    rows: List[Dict[str, Any]] = []
    for ts_code in codes:
        df = loader.load(ts_code)
        if df is None or df.empty:
            if export_all_attempts:
                rows.append({"ts_code": ts_code, "error": "无K线"})
            continue
        df = _ensure_trade_date_str(df)
        try:
            rec = eval_one_stock(df, n, analyzer)
        except Exception as e:
            if export_all_attempts:
                rows.append({"ts_code": ts_code, "error": str(e)[:200]})
            continue
        if rec is None:
            if export_all_attempts:
                rows.append(
                    {
                        "ts_code": ts_code,
                        "note": "未满足：收盘>前N日高 或 未在120日线上/无突破",
                    }
                )
            continue
        rec["ts_code"] = ts_code
        rows.append(rec)

    out = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(os.path.abspath(out_csv)) or ".", exist_ok=True)
    out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="前N日最高价突破 + 站上120日均线起点至今涨幅，导出 CSV",
    )
    p.add_argument(
        "--n",
        type=int,
        required=True,
        help="前 N 个交易日（不含当天）的最高价窗口",
    )
    p.add_argument(
        "--pool",
        default=None,
        help="股票池 CSV（须含 ts_code），默认 cy_quant/sh_120ma.csv",
    )
    p.add_argument(
        "--out",
        default=None,
        help="输出 CSV 路径；默认 cy_quant/output/n_high_ma120_<日期>.csv",
    )
    p.add_argument(
        "--all-rows",
        action="store_true",
        help="导出全部扫描行（含未通过原因）；默认仅导出满足条件的行",
    )
    args = p.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    pool = args.pool or os.path.join(here, "sh_120ma.csv")
    pool = os.path.normpath(os.path.expanduser(pool))
    if not os.path.isfile(pool):
        print("找不到股票池: %s" % pool, file=sys.stderr)
        return 1

    day = datetime.now().strftime("%Y%m%d")
    out = args.out or os.path.join(here, "output", "n_high_ma120_%s.csv" % day)

    print("N=%s  pool=%s  -> %s" % (args.n, pool, out))
    df = scan_pool(pool, out, args.n, export_all_attempts=args.all_rows)
    print("导出行数: %s" % len(df))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
