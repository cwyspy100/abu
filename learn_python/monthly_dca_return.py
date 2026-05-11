# -*- coding: utf-8 -*-
"""
按月定额定投，从 ~/abu/data/csv 读取 K 线，计算累计投入、总收益与年化收益。

依赖：pandas、numpy（无 abupy）

K 线文件命名：sh600000_20240126_20260504 或 .csv，取同前缀最新文件（按文件名排序）。

用法：
    python learn_python/monthly_dca_return.py --code sh600000 --amount 3000
    python learn_python/monthly_dca_return.py --code 600000.SH --amount 5000 --csv-dir ~/abu/data/csv

或在代码中：
    from learn_python.monthly_dca_return import run_monthly_dca_from_code
    r = run_monthly_dca_from_code("sz000001", monthly_amount=2000)
"""

from __future__ import print_function

import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

DEFAULT_CSV_DIR = os.path.expanduser("~/abu/data/csv")


def code_to_file_prefix(code):
    """
    sh600000 / 600000.SH / 600000 -> sh600000
    sz000001 / 000001.SZ -> sz000001
    """
    c = str(code).strip()
    if not c:
        raise ValueError("code 不能为空")
    low = c.lower()
    if len(low) >= 2 and low[:2] in ("sh", "sz", "hk", "us"):
        return low[:2] + c[2:].upper().replace(".", "")
    if "." in c:
        num, mkt = c.split(".", 1)
        num = num.strip()
        mkt = mkt.strip().upper()
        if mkt == "SH":
            return "sh" + num
        if mkt == "SZ":
            return "sz" + num
        raise ValueError("不支持的交易所后缀: {}".format(mkt))
    if c.isdigit():
        return ("sh" if c.startswith("6") else "sz") + c
    raise ValueError("无法解析 code: {}".format(code))


def find_latest_kline_file(csv_dir, prefix):
    """同前缀多文件时取文件名最大者（通常结束日期最新）。"""
    csv_dir = os.path.expanduser(csv_dir)
    if not os.path.isdir(csv_dir):
        raise FileNotFoundError("目录不存在: {}".format(csv_dir))
    matched = []
    for pat in (f"{prefix}_*.csv", f"{prefix}_*"):
        matched.extend(glob.glob(os.path.join(csv_dir, pat)))
    if not matched:
        raise FileNotFoundError("未找到 K 线文件: {}_* （目录 {}）".format(prefix, csv_dir))
    matched = sorted(set(matched), key=lambda p: os.path.basename(p), reverse=True)
    return matched[0]


def load_abu_kline_csv(filepath):
    """
    读取 abu 导出的日 K，统一为 trade_date + close。
    支持列名 date（YYYYMMDD 整数或字符串）或 trade_date。
    """
    try:
        df = pd.read_csv(filepath, encoding="utf-8-sig")
    except Exception:
        df = pd.read_csv(filepath, encoding="gbk")

    if "close" not in df.columns:
        raise ValueError("文件缺少 close 列: {}".format(filepath))

    if "trade_date" in df.columns:
        dcol = "trade_date"
    elif "date" in df.columns:
        dcol = "date"
    else:
        raise ValueError("文件需含 date 或 trade_date 列: {}".format(filepath))

    out = pd.DataFrame()
    raw = df[dcol]
    num = pd.to_numeric(raw, errors="coerce")

    def _cell_to_dt(v):
        if pd.isnull(v):
            return pd.NaT
        try:
            return pd.to_datetime(str(int(float(v))), format="%Y%m%d")
        except Exception:
            return pd.NaT

    if num.notnull().sum() >= max(1, len(num) // 2):
        out["trade_date"] = num.map(_cell_to_dt)
    else:
        out["trade_date"] = pd.to_datetime(raw, errors="coerce")
    out["close"] = pd.to_numeric(df["close"], errors="coerce")
    out = out.dropna(subset=["trade_date", "close"]).sort_values("trade_date")
    out = out.reset_index(drop=True)
    if len(out) < 2:
        raise ValueError("有效 K 线不足 2 行: {}".format(filepath))
    return out


def run_monthly_dca(
    df,
    monthly_amount,
    date_col="trade_date",
    close_col="close",
):
    """
    :param df: K 线，含 date_col, close_col
    :param monthly_amount: 每月买入金额（元）
    :return: dict
    """
    if monthly_amount <= 0:
        raise ValueError("monthly_amount 必须 > 0")
    d = df[[date_col, close_col]].copy()
    d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
    d[close_col] = pd.to_numeric(d[close_col], errors="coerce")
    d = d.dropna().sort_values(date_col).reset_index(drop=True)
    if len(d) < 2:
        raise ValueError("有效行情不足 2 行")

    d["ym"] = d[date_col].dt.to_period("M")
    first_idx = d.groupby("ym", sort=True).head(1).index.tolist()

    shares = 0.0
    total_invested = 0.0
    trades = []
    for idx in first_idx:
        row = d.iloc[idx]
        px = float(row[close_col])
        if px <= 0:
            continue
        amt = float(monthly_amount)
        sh = amt / px
        shares += sh
        total_invested += amt
        trades.append(
            {
                "date": row[date_col],
                "close": px,
                "amount": amt,
                "shares": sh,
            }
        )

    if total_invested <= 0:
        raise ValueError("未发生任何定投（请检查数据）")

    last_px = float(d[close_col].iloc[-1])
    last_dt = d[date_col].iloc[-1]
    final_value = shares * last_px
    profit_amount = final_value - total_invested
    total_return = final_value / total_invested - 1.0

    first_dt = trades[0]["date"]
    days = max((last_dt - first_dt).days, 1)
    years = days / 365.25
    if years <= 0:
        annualized = total_return
    else:
        annualized = (1.0 + total_return) ** (1.0 / years) - 1.0

    return {
        "n_months": len(trades),
        "total_invested": total_invested,
        "final_value": final_value,
        "profit_amount": profit_amount,
        "last_close": last_px,
        "total_shares": shares,
        "total_return_pct": total_return * 100.0,
        "annualized_return_pct": annualized * 100.0,
        "holding_days": days,
        "holding_years": years,
        "trades": trades,
    }


def run_monthly_dca_from_code(
    code,
    monthly_amount,
    csv_dir=DEFAULT_CSV_DIR,
):
    """
    按股票代码从 abu/data/csv 读最新 K 线并跑按月定投。
    """
    prefix = code_to_file_prefix(code)
    path = find_latest_kline_file(csv_dir, prefix)
    df = load_abu_kline_csv(path)
    out = run_monthly_dca(df, monthly_amount=monthly_amount)
    out["code"] = prefix
    out["kline_file"] = path
    return out


def _print_result(r, encoding=None):
    """encoding: 如 'utf-8' 则写入 bytes，避免部分终端 ascii 报错。"""
    lines = [
        "code={} file={}".format(r.get("code", "-"), r.get("kline_file", "-")),
        "months={} monthly_amount={:.2f}".format(r["n_months"], r.get("monthly_amount") or 0),
        "total_invested={:.2f}".format(r["total_invested"]),
        "final_value={:.2f} last_close={:.4f}".format(r["final_value"], r["last_close"]),
        "profit_amount={:.2f}".format(r["profit_amount"]),
        "total_return_pct={:.2f}%".format(r["total_return_pct"]),
        "annualized_return_pct={:.2f}% holding_days={} holding_years={:.2f}".format(
            r["annualized_return_pct"], r["holding_days"], r["holding_years"]),
    ]
    text = "\n".join(lines) + "\n"
    if encoding:
        getattr(sys.stdout, "buffer", sys.stdout).write(text.encode(encoding))
    else:
        try:
            print(text, end="")
        except UnicodeEncodeError:
            getattr(sys.stdout, "buffer", sys.stdout).write(text.encode("utf-8", errors="replace"))


def _demo_synthetic():
    rng = np.random.RandomState(0)
    n = 600
    r = rng.normal(0.0005, 0.015, size=n)
    close = 10 * np.exp(np.cumsum(r))
    dates = pd.bdate_range("2018-01-05", periods=n, freq="B")
    df = pd.DataFrame({"trade_date": dates, "close": close})
    out = run_monthly_dca(df, monthly_amount=2000)
    out["code"] = "DEMO"
    out["monthly_amount"] = 2000
    print("=== synthetic demo ===")
    _print_result(out)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description="从 abu/data/csv 读 K 线，按月定投并算收益")
    parser.add_argument("--code", type=str, default="", help="如 sh600000、600000.SH、sz000001")
    parser.add_argument("--amount", type=float, default=3000.0, help="每月定投金额（元）")
    parser.add_argument("--csv-dir", type=str, default=DEFAULT_CSV_DIR, help="K 线目录，默认 ~/abu/data/csv")
    parser.add_argument("--demo", action="store_true", help="用随机数据演示，不读文件")
    args = parser.parse_args(argv)

    if args.demo or not args.code.strip():
        if not args.code.strip():
            print("No --code: running synthetic demo. Example: --code sh600000 --amount 3000\n")
        _demo_synthetic()
        return 0

    r = run_monthly_dca_from_code(args.code.strip(), args.amount, csv_dir=args.csv_dir)
    r["monthly_amount"] = args.amount
    _print_result(r)
    return 0


if __name__ == "__main__":
    sys.exit(main("sh600000"))
