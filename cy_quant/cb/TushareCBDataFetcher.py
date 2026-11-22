"""
可转债数据拉取工具（Tushare）

功能：
1) 拉取可转债基础信息（cb_basic）
2) 基于基础信息中的 ts_code，拉取近两年可转债日线行情（cb_daily）
3) 数据保存到本地目录（默认 /Users/water/abu/data/cb）

使用示例：
  python -m cy_quant.cb.TushareCBDataFetcher
  python -m cy_quant.cb.TushareCBDataFetcher --years 2 --calls-per-minute 40
  python -m cy_quant.cb.TushareCBDataFetcher --token your_token --output-dir /Users/water/abu/data/cb
"""

import argparse
import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import pandas as pd
import tushare as ts


DEFAULT_OUTPUT_DIR = "/Users/water/abu/data/cb"
DEFAULT_CB_BASIC_FIELDS = "ts_code,bond_short_name,stk_code,stk_short_name,list_date,delist_date"
DEFAULT_CB_DAILY_FIELDS = (
    "ts_code,trade_date,pre_close,open,high,low,close,change,pct_chg,vol,amount,"
    "bond_value,bond_over_rate,cb_value,cb_over_rate"
)
DEFAULT_CALLS_PER_MINUTE = 40
DEFAULT_YEARS = 2


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MinuteRateLimiter:
    """简单限速：两次调用间隔 >= 60/calls_per_minute 秒。"""

    def __init__(self, calls_per_minute: int = DEFAULT_CALLS_PER_MINUTE) -> None:
        if calls_per_minute <= 0:
            raise ValueError("calls_per_minute 必须为正整数")
        self._min_interval = 60.0 / float(calls_per_minute)
        self._last_ts: float = 0.0

    def wait(self) -> None:
        now = time.time()
        if self._last_ts > 0:
            elapsed = now - self._last_ts
            need = self._min_interval - elapsed
            if need > 0:
                time.sleep(need)
        self._last_ts = time.time()


def _load_token(token: Optional[str] = None) -> str:
    if token:
        return token.strip()

    config_path = os.path.join(_project_root(), "todolist", "config.json")
    if not os.path.exists(config_path):
        raise ValueError("未提供 token，且未找到 todolist/config.json")

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    tok = (cfg.get("token") or cfg.get("tushare_token") or "").strip()
    if not tok:
        raise ValueError("未提供 token，且 todolist/config.json 中 token/tushare_token 为空")
    return tok


def _date_yyyymmdd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def _parse_yyyymmdd(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y%m%d")


def _shift_day(date_str: str, days: int) -> str:
    return _date_yyyymmdd(_parse_yyyymmdd(date_str) + timedelta(days=days))


def fetch_cb_basic(pro, fields: str = DEFAULT_CB_BASIC_FIELDS) -> pd.DataFrame:
    df = pro.cb_basic(fields=fields)
    if df is None:
        return pd.DataFrame()
    return df


def scope_bonds_to_window(cb_basic_df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    """保留研究窗口内曾上市交易的转债，避免下载早已退市的历史代码。"""
    out = cb_basic_df.drop_duplicates(subset=["ts_code"], keep="first").copy()
    if out.empty:
        return out

    start = pd.to_datetime(start_date, format="%Y%m%d", errors="coerce")
    end = pd.to_datetime(end_date, format="%Y%m%d", errors="coerce")
    listed = pd.to_datetime(out.get("list_date"), format="%Y%m%d", errors="coerce")
    delisted = pd.to_datetime(out.get("delist_date"), format="%Y%m%d", errors="coerce")

    # 上市日在窗口结束日前，且未退市或退市日在窗口开始日后，才可能有样本数据。
    in_window = (listed.isna() | (listed <= end)) & (delisted.isna() | (delisted >= start))
    return out.loc[in_window].reset_index(drop=True)


def _to_symbol_prefix(ts_code: str) -> str:
    """128144.SZ -> sz128144, 113519.SH -> sh113519"""
    if "." not in ts_code:
        return ts_code.lower()
    code, ex = ts_code.split(".", 1)
    return f"{ex.lower()}{code}"


def _find_existing_range_file(per_bond_dir: str, symbol: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    在目录中寻找该 symbol 已有文件，格式：sz128144_20230410_20240419（无扩展名）
    返回: (file_path, start_date, end_date)
    """
    if not os.path.isdir(per_bond_dir):
        return None, None, None
    pat = re.compile(rf"^{re.escape(symbol)}_(\d{{8}})_(\d{{8}})$")
    best = None
    best_days = -1
    for name in os.listdir(per_bond_dir):
        m = pat.match(name)
        if not m:
            continue
        s, e = m.group(1), m.group(2)
        try:
            days = (_parse_yyyymmdd(e) - _parse_yyyymmdd(s)).days
        except Exception:
            continue
        if days > best_days:
            best_days = days
            best = (os.path.join(per_bond_dir, name), s, e)
    if best is None:
        return None, None, None
    return best


def fetch_cb_daily_for_all(
    pro,
    cb_basic_df: pd.DataFrame,
    start_date: str,
    end_date: str,
    output_dir: str,
    target_days: int,
    fields: str = DEFAULT_CB_DAILY_FIELDS,
    calls_per_minute: int = DEFAULT_CALLS_PER_MINUTE,
) -> pd.DataFrame:
    if cb_basic_df.empty or "ts_code" not in cb_basic_df.columns:
        return pd.DataFrame()

    limiter = MinuteRateLimiter(calls_per_minute=calls_per_minute)
    symbols: List[str] = cb_basic_df["ts_code"].dropna().astype(str).drop_duplicates().tolist()

    chunks: List[pd.DataFrame] = []
    total = len(symbols)
    per_bond_dir = os.path.join(output_dir, "daily_by_bond")
    os.makedirs(per_bond_dir, exist_ok=True)

    for i, ts_code in enumerate(symbols, start=1):
        symbol = _to_symbol_prefix(ts_code)
        existing_path, existing_start, existing_end = _find_existing_range_file(per_bond_dir, symbol)
        old_df = pd.DataFrame()
        has_existing = bool(existing_path and existing_start and existing_end and os.path.exists(existing_path))
        if has_existing:
            try:
                old_df = pd.read_csv(existing_path, dtype={"trade_date": str})
                if "trade_date" in old_df.columns:
                    old_df["trade_date"] = old_df["trade_date"].astype(str)
            except Exception as e:
                print(f"[{i}/{total}] {ts_code} 读取已有文件失败，将忽略已有文件: {e}")
                old_df = pd.DataFrame()
                has_existing = False

        need_ranges: List[Tuple[str, str]] = []
        if has_existing:
            # 目标区间已被已有文件覆盖，直接复用已有数据（不重复请求）
            if existing_start <= start_date and existing_end >= end_date:
                merged_df = old_df.copy()
                print(
                    f"[{i}/{total}] {ts_code} 已覆盖目标区间({existing_start}-{existing_end})，跳过拉取"
                )
            else:
                # 仅拉取缺失区间：左缺口 + 右缺口（满足“已有2年，仅补前3年”）
                if start_date < existing_start:
                    left_end = _shift_day(existing_start, -1)
                    if start_date <= left_end:
                        need_ranges.append((start_date, left_end))
                if end_date > existing_end:
                    right_start = _shift_day(existing_end, 1)
                    if right_start <= end_date:
                        need_ranges.append((right_start, end_date))
                merged_df = old_df.copy()
        else:
            need_ranges.append((start_date, end_date))
            merged_df = pd.DataFrame()

        pulled_list: List[pd.DataFrame] = []
        for seg_start, seg_end in need_ranges:
            limiter.wait()
            try:
                seg_df = pro.cb_daily(
                    ts_code=ts_code,
                    start_date=seg_start,
                    end_date=seg_end,
                    fields=fields,
                )
            except Exception as e:
                print(f"[{i}/{total}] {ts_code} 拉取失败({seg_start}-{seg_end}): {e}")
                continue
            if seg_df is None or seg_df.empty:
                print(f"[{i}/{total}] {ts_code} 区间无数据({seg_start}-{seg_end})")
                continue
            pulled_list.append(seg_df)
            print(f"[{i}/{total}] {ts_code} 补拉 {seg_start}-{seg_end} -> {len(seg_df)} 条")

        if pulled_list:
            merged_df = pd.concat([merged_df] + pulled_list, ignore_index=True)

        if merged_df is None or merged_df.empty:
            print(f"[{i}/{total}] {ts_code} 无数据")
            continue

        if {"ts_code", "trade_date"}.issubset(merged_df.columns):
            merged_df["trade_date"] = merged_df["trade_date"].astype(str)
            merged_df = merged_df.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
        merged_df = merged_df.sort_values(by=["trade_date"]).reset_index(drop=True)

        # 聚合文件和单券文件均对齐到目标区间，避免混入区间外数据
        if "trade_date" in merged_df.columns:
            merged_df = merged_df[
                (merged_df["trade_date"] >= start_date) & (merged_df["trade_date"] <= end_date)
            ].copy()

        if merged_df.empty:
            print(f"[{i}/{total}] {ts_code} 目标区间无数据")
            continue

        min_trade_date = str(merged_df["trade_date"].min()) if "trade_date" in merged_df.columns else start_date
        max_trade_date = str(merged_df["trade_date"].max()) if "trade_date" in merged_df.columns else end_date
        per_file = f"{symbol}_{min_trade_date}_{max_trade_date}"
        per_path = os.path.join(per_bond_dir, per_file)
        merged_df.to_csv(per_path, index=False, encoding="utf-8-sig")
        if has_existing and existing_path and existing_path != per_path and os.path.exists(existing_path):
            try:
                os.remove(existing_path)
            except Exception:
                pass

        chunks.append(merged_df)
        print(f"[{i}/{total}] {ts_code} -> {len(merged_df)} 条, 已保存 {per_file}")

    if not chunks:
        return pd.DataFrame()

    out = pd.concat(chunks, ignore_index=True)
    if {"ts_code", "trade_date"}.issubset(set(out.columns)):
        out = out.drop_duplicates(subset=["ts_code", "trade_date"], keep="first")
    return out


def run(
    token: Optional[str] = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    years: int = DEFAULT_YEARS,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    calls_per_minute: int = DEFAULT_CALLS_PER_MINUTE,
    cb_basic_fields: str = DEFAULT_CB_BASIC_FIELDS,
    cb_daily_fields: str = DEFAULT_CB_DAILY_FIELDS,
) -> None:
    if years <= 0:
        raise ValueError("years 必须为正整数")

    tok = _load_token(token)
    ts.set_token(tok)
    pro = ts.pro_api()

    os.makedirs(output_dir, exist_ok=True)

    today = datetime.now()
    if end_date is None:
        end_date = _date_yyyymmdd(today)
    if start_date is None:
        start_dt = _parse_yyyymmdd(end_date) - timedelta(days=365 * years)
        start_date = _date_yyyymmdd(start_dt)
    target_days = (_parse_yyyymmdd(end_date) - _parse_yyyymmdd(start_date)).days
    if target_days <= 0:
        raise ValueError("end_date 必须大于 start_date")

    print("开始拉取 cb_basic ...")
    cb_basic_df = fetch_cb_basic(pro, fields=cb_basic_fields)
    basic_path = os.path.join(output_dir, "cb_basic.csv")
    cb_basic_df.to_csv(basic_path, index=False, encoding="utf-8-sig")
    print(f"cb_basic 已保存 {len(cb_basic_df)} 条 -> {basic_path}")

    scoped = scope_bonds_to_window(cb_basic_df, start_date=start_date, end_date=end_date)
    print(f"研究窗口内转债范围: {len(scoped)} / {len(cb_basic_df)}")

    print(f"开始拉取 cb_daily（区间 {start_date} ~ {end_date}）...")
    cb_daily_df = fetch_cb_daily_for_all(
        pro,
        cb_basic_df=scoped,
        start_date=start_date,
        end_date=end_date,
        output_dir=output_dir,
        target_days=target_days,
        fields=cb_daily_fields,
        calls_per_minute=calls_per_minute,
    )

    daily_path = os.path.join(output_dir, f"cb_daily_{start_date}_{end_date}.csv")
    cb_daily_df.to_csv(daily_path, index=False, encoding="utf-8-sig")
    print(f"cb_daily 已保存 {len(cb_daily_df)} 条 -> {daily_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Tushare 可转债基础信息+近两年行情拉取")
    parser.add_argument("--token", default=None, help="Tushare token（默认读 todolist/config.json）")
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录（默认 {DEFAULT_OUTPUT_DIR}）",
    )
    parser.add_argument("--years", type=int, default=DEFAULT_YEARS, help="拉取近 N 年数据，默认 2")
    parser.add_argument("--start-date", default=None, help="起始日期 YYYYMMDD（设置后优先于 years）")
    parser.add_argument("--end-date", default=None, help="结束日期 YYYYMMDD（默认今天）")
    parser.add_argument(
        "--calls-per-minute",
        type=int,
        default=DEFAULT_CALLS_PER_MINUTE,
        help="每分钟最多 API 调用次数，默认 40",
    )
    parser.add_argument(
        "--cb-basic-fields",
        default=DEFAULT_CB_BASIC_FIELDS,
        help="cb_basic 字段列表",
    )
    parser.add_argument(
        "--cb-daily-fields",
        default=DEFAULT_CB_DAILY_FIELDS,
        help="cb_daily 字段列表",
    )
    args = parser.parse_args()

    run(
        token=args.token,
        output_dir=args.output_dir,
        years=args.years,
        start_date=args.start_date,
        end_date=args.end_date,
        calls_per_minute=args.calls_per_minute,
        cb_basic_fields=args.cb_basic_fields,
        cb_daily_fields=args.cb_daily_fields,
    )


if __name__ == "__main__":
    main()
