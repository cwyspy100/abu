# -*- coding: utf-8 -*-
"""
A 股方案 B：外置基本面选股（价值向），数据来自 Tushare fina_indicator（文档 doc_id=79）。

优先级：
1) 本地目录 ~/abu/tushare/finance 下 {6位代码}_{SZ|SH}_finance.csv（与现有爬虫/合并表一致）
2) 本地无文件时，使用 Tushare pro.fina_indicator（需 token，见 todolist/config.json 或环境变量 TUSHARE_TOKEN）

输出：abupy 可用的 choice_symbols，如 sh600000、sz000001。

用法示例：
    from cy_quant.pick_stock_cn_fina_value import pick_cn_value_pool, export_symbol_csv
    syms = pick_cn_value_pool(top_n=30)
    export_symbol_csv(syms, "cy_quant/output/cn_value_pool.csv")
    # abu.run_loop_back(..., choice_symbols=syms, ...)
"""

import glob
import json
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# fina_indicator 核心字段（本地宽表也包含这些列名）
VALUE_COLS = [
    "ts_code",
    "ann_date",
    "end_date",
    "roe",
    "roe_dt",
    "roic",
    "debt_to_assets",
    "netprofit_margin",
    "grossprofit_margin",
    "ocf_to_or",
]

DEFAULT_LOCAL_FINANCE_DIR = os.path.expanduser("~/abu/tushare/finance")


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tushare_token() -> str:
    tok = (os.environ.get("TUSHARE_TOKEN") or "").strip()
    if tok:
        return tok
    cfg_path = os.path.join(_project_root(), "todolist", "config.json")
    if os.path.isfile(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        tok = (cfg.get("token") or "").strip()
        if tok:
            return tok
    raise ValueError("未配置 Tushare token：请设置环境变量 TUSHARE_TOKEN 或在 todolist/config.json 中配置 token")


def ts_code_to_abu_symbol(ts_code: str) -> str:
    """600000.SH -> sh600000, 000001.SZ -> sz000001"""
    ts_code = str(ts_code).strip().upper()
    if "." not in ts_code:
        return ts_code.lower()
    code, mkt = ts_code.split(".", 1)
    return ("sh" if mkt == "SH" else "sz") + code


def abu_symbol_to_ts_code(symbol: str) -> str:
    """sh600000 -> 600000.SH"""
    s = str(symbol).strip().lower()
    if len(s) >= 2 and s[:2] in ("sh", "sz"):
        return f"{s[2:]}.{'SH' if s[:2] == 'sh' else 'SZ'}"
    return symbol


def _local_finance_path(ts_code: str, local_dir: str) -> str:
    ts_code = str(ts_code).strip().upper()
    code, mkt = ts_code.split(".", 1)
    fname = f"{code}_{mkt}_finance.csv"
    return os.path.join(local_dir, fname)


def read_local_fina_csv(ts_code: str, local_dir: str) -> Optional[pd.DataFrame]:
    path = _local_finance_path(ts_code, local_dir)
    if not os.path.isfile(path):
        return None
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        try:
            df = pd.read_csv(path, encoding="gbk")
        except Exception:
            return None
    if df.empty or "ts_code" not in df.columns or "end_date" not in df.columns:
        return None
    return df


def _normalize_ann_col(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "ann_date" not in out.columns and "ann_date_x" in out.columns:
        out["ann_date"] = out["ann_date_x"]
    return out


def latest_fina_row(df: pd.DataFrame) -> Optional[pd.Series]:
    """取最新报告期一行；同 end_date 取 ann_date 最大。"""
    if df is None or df.empty:
        return None
    d = _normalize_ann_col(df)
    d = d.copy()
    d["end_date"] = pd.to_numeric(d["end_date"], errors="coerce")
    d = d[pd.notnull(d["end_date"])]
    if d.empty:
        return None
    if "ann_date" in d.columns:
        def _ann_to_int(val):
            s = "".join(c for c in str(val) if c.isdigit())
            return int(s[:8]) if len(s) >= 8 else (int(s) if s else 0)

        d["_ann"] = d["ann_date"].map(_ann_to_int)
    else:
        d["_ann"] = 0
    d = d.sort_values(["end_date", "_ann"], ascending=[False, False])
    return d.iloc[0]


def _ensure_fina_columns(row: pd.Series) -> pd.Series:
    row = row.copy()
    for c in VALUE_COLS:
        if c not in row.index:
            row[c] = np.nan
    return row


def fetch_fina_indicator_tushare(
    pro: Any,
    ts_code: str,
    start_date: str = "20180101",
    end_date: str = "20301231",
    sleep_sec: float = 0.15,
) -> pd.DataFrame:
    """
    拉取单只股票 fina_indicator；超过 100 条时分段请求（按 end_date 递增窗口）。
    """
    ts_code = str(ts_code).strip().upper()
    all_parts: List[pd.DataFrame] = []
    cur_start = start_date
    while True:
        time.sleep(sleep_sec)
        chunk = pro.fina_indicator(ts_code=ts_code, start_date=cur_start, end_date=end_date)
        if chunk is None or len(chunk) == 0:
            break
        all_parts.append(chunk)
        if len(chunk) < 100:
            break
        last_end = str(int(chunk["end_date"].max()))
        if last_end <= cur_start:
            break
        cur_start = str(int(last_end) + 1)
    if not all_parts:
        return pd.DataFrame()
    out = pd.concat(all_parts, ignore_index=True)
    out = out.drop_duplicates(subset=["ts_code", "end_date", "ann_date"], keep="last")
    return out


def get_latest_metrics_for_symbol(
    ts_code: str,
    local_dir: str = DEFAULT_LOCAL_FINANCE_DIR,
    pro: Any = None,
) -> Optional[pd.Series]:
    """
    返回单标的最新一期财务指标（Series）；本地无数据且 pro 为 None 时返回 None。
    """
    ts_code = str(ts_code).strip().upper()
    df = read_local_fina_csv(ts_code, local_dir)
    if df is None and pro is not None:
        df = fetch_fina_indicator_tushare(pro, ts_code)
    if df is None or df.empty:
        return None
    row = latest_fina_row(df)
    if row is None:
        return None
    return _ensure_fina_columns(row)


def _numeric(row: pd.Series, key: str) -> float:
    v = row.get(key)
    try:
        if pd.isnull(v):
            return float("nan")
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def value_score(row: pd.Series) -> float:
    """
    简单价值综合分（越大越好）：ROE、扣非 ROE、ROIC 抬高；资产负债率降低。
    仅用于排序，非严谨多因子模型。
    """
    roe = _numeric(row, "roe")
    roe_dt = _numeric(row, "roe_dt")
    roic = _numeric(row, "roic")
    debt = _numeric(row, "debt_to_assets")
    npm = _numeric(row, "netprofit_margin")
    score = 0.0
    n = 0
    for x in (roe, roe_dt, roic):
        if pd.notnull(x):
            score += x
            n += 1
    if n:
        score = score / n
    if pd.notnull(debt):
        score -= 0.25 * debt
    if pd.notnull(npm):
        score += 0.1 * npm
    return score


def build_universe_from_local_dir(local_dir: str) -> List[str]:
    """从本地 finance 文件名解析 ts_code 列表。"""
    paths = glob.glob(os.path.join(local_dir, "*_SH_finance.csv")) + glob.glob(
        os.path.join(local_dir, "*_SZ_finance.csv")
    )
    codes: List[str] = []
    for p in paths:
        base = os.path.basename(p).replace("_finance.csv", "")
        if base.endswith("_SH"):
            codes.append(f"{base[:-3]}.SH")
        elif base.endswith("_SZ"):
            codes.append(f"{base[:-3]}.SZ")
    return sorted(set(codes))


def pick_cn_value_pool(
    universe: Optional[List[str]] = None,
    local_dir: str = DEFAULT_LOCAL_FINANCE_DIR,
    use_tushare_if_missing: bool = False,
    min_roe: float = 5.0,
    max_debt_to_assets: float = 85.0,
    min_roic: Optional[float] = None,
    top_n: int = 50,
    progress: Optional[Callable[[int, int], None]] = None,
) -> pd.DataFrame:
    """
    扫描 universe，取最新一期财报，过滤后按 value_score 排序取 top_n。

    :param universe: ts_code 列表；None 则用本地目录下全部股票
    :param use_tushare_if_missing: True 时本地无文件则请求 API（慢，注意积分与限速）
    :return: DataFrame 含 ts_code, abu_symbol, value_score 及主要财务列
    """
    if universe is None:
        universe = build_universe_from_local_dir(local_dir)
    pro = None
    if use_tushare_if_missing:
        import tushare as ts

        pro = ts.pro_api(load_tushare_token())

    rows: List[Dict[str, Any]] = []
    total = len(universe)
    for i, ts_code in enumerate(universe):
        if progress:
            progress(i + 1, total)
        row = get_latest_metrics_for_symbol(ts_code, local_dir=local_dir, pro=pro)
        if row is None:
            continue
        roe = _numeric(row, "roe")
        debt = _numeric(row, "debt_to_assets")
        roic_v = _numeric(row, "roic")
        if pd.notnull(roe) and roe < min_roe:
            continue
        if pd.notnull(debt) and debt > max_debt_to_assets:
            continue
        if min_roic is not None and pd.notnull(roic_v) and roic_v < min_roic:
            continue
        if pd.isnull(roe) and pd.isnull(_numeric(row, "roe_dt")):
            continue

        d = {c: row.get(c) for c in VALUE_COLS if c in row.index}
        d["ts_code"] = str(row.get("ts_code", ts_code)).upper()
        d["value_score"] = value_score(row)
        d["abu_symbol"] = ts_code_to_abu_symbol(d["ts_code"])
        rows.append(d)

    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out = out.sort_values("value_score", ascending=False).head(top_n)
    return out.reset_index(drop=True)


def export_symbol_csv(df: pd.DataFrame, path: str, column: str = "abu_symbol") -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    pd.DataFrame({column: df[column].tolist()}).to_csv(path, index=False, encoding="utf-8-sig")


def pick_cn_value_symbols(**kwargs):
    """返回 abupy choice_symbols 列表。"""
    df = pick_cn_value_pool(**kwargs)
    if df.empty:
        return []
    return df["abu_symbol"].tolist()


def _self_test() -> None:
    """少量本地测试：不调用网络。"""
    local = DEFAULT_LOCAL_FINANCE_DIR
    assert ts_code_to_abu_symbol("600000.SH") == "sh600000"
    assert ts_code_to_abu_symbol("000001.SZ") == "sz000001"
    assert abu_symbol_to_ts_code("sh600000") == "600000.SH"

    p = _local_finance_path("000001.SZ", local)
    if os.path.isfile(p):
        df = read_local_fina_csv("000001.SZ", local)
        assert df is not None
        row = latest_fina_row(df)
        assert row is not None
        assert "roe" in row.index or "end_date" in row.index

    small = ["600000.SH", "000001.SZ", "600519.SH"]
    pool = pick_cn_value_pool(
        universe=[c for c in small if os.path.isfile(_local_finance_path(c, local))],
        local_dir=local,
        use_tushare_if_missing=False,
        min_roe=-1e9,
        max_debt_to_assets=100,
        top_n=10,
    )
    assert isinstance(pool, pd.DataFrame)
    print("[pick_stock_cn_fina_value] self_test ok, sample pool rows:", len(pool))
    if not pool.empty:
        print(pool[["ts_code", "abu_symbol", "value_score", "roe", "debt_to_assets"]].head())


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="A股基本面价值选股（本地 finance + 可选 Tushare）")
    ap.add_argument("--local-dir", default=DEFAULT_LOCAL_FINANCE_DIR, help="本地 finance CSV 目录")
    ap.add_argument("--top-n", type=int, default=20, help="输出股票数量上限")
    ap.add_argument("--min-roe", type=float, default=5.0)
    ap.add_argument("--max-debt", type=float, default=85.0, dest="max_debt_to_assets")
    ap.add_argument("--use-api-missing", action="store_true", help="本地无文件时用 fina_indicator 拉取（慢）")
    ap.add_argument("--export", default="", help="导出 CSV 路径，如 cy_quant/output/cn_value_pool.csv")
    ap.add_argument("--self-test", action="store_true", help="仅运行内置自检")
    ap.add_argument(
        "--scan-all",
        action="store_true",
        help="扫描本地目录下全部 *_finance.csv（股票多时会较慢）",
    )
    ap.add_argument(
        "--symbols",
        default="",
        help="逗号分隔 ts_code，如 600000.SH,000001.SZ；不填且未 --scan-all 时仅用少量样例",
    )
    args = ap.parse_args()
    if args.self_test:
        _self_test()
        raise SystemExit(0)

    if not args.scan_all and not args.symbols.strip():
        _self_test()
        sample = ["600000.SH", "000001.SZ", "600519.SH"]
        uni = [c for c in sample if os.path.isfile(_local_finance_path(c, args.local_dir))]
        if not uni:
            print("样例 ts_code 在本地目录无文件，请使用 --scan-all 或 --symbols")
        else:
            df = pick_cn_value_pool(
                universe=uni,
                local_dir=args.local_dir,
                use_tushare_if_missing=args.use_api_missing,
                min_roe=args.min_roe,
                max_debt_to_assets=args.max_debt_to_assets,
                top_n=args.top_n,
            )
            print(df.to_string(index=False))
            if args.export and not df.empty:
                export_symbol_csv(df, args.export)
                print("exported:", args.export, "rows:", len(df))
        raise SystemExit(0)

    universe = None
    if args.symbols.strip():
        universe = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]

    df = pick_cn_value_pool(
        universe=universe,
        local_dir=args.local_dir,
        use_tushare_if_missing=args.use_api_missing,
        min_roe=args.min_roe,
        max_debt_to_assets=args.max_debt_to_assets,
        top_n=args.top_n,
    )
    print(df.head(min(15, len(df))).to_string(index=False))
    if args.export and not df.empty:
        export_symbol_csv(df, args.export)
        print("exported:", args.export, "rows:", len(df))
