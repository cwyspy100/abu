# -*- encoding:utf-8 -*-
"""
指定交易日 as_of 的动量突破筛选（无未来函数），支持 **按步开启**（参数 ``enabled_steps`` / ``--steps``）：

1. **市场环境**：基准 close > MA(bench_ma_n)，默认 200 日（美股可用 ``--bench SPY`` 等）
2. **长期趋势**：个股 close > MA(stock_ma_n)，默认 120；可选均线斜率向上（``stock_ma_slope_bars``）
3. **相对强度 RS**：过去 rs_lookback_n 日收益，在已通过前面步骤的标的中取 top rs_top_pct（默认 20%）
4. **波动压缩**：ATR(atr_short_n) < ATR(atr_long_n)，默认 20 < 60
5. **突破确认**：收盘为近 xd_short / xd_long 日**收盘**最高价之一（二选一，与 Abu 双窗口新高口径一致）且放量：
   volume > vol_mult × 前 vol_ma_n 日均量（不含当日）

示例：``--steps 1,2,3`` 只开前三步；``--steps 1,5`` 只做大市 + 突破放量；不传则 ``1,2,3,4,5`` 全开。

输出：signal_date、forward_horizons 远期收益等。

K 线目录约定同 Analyze120MA：~/abu/data/csv 下 sh*/sz*/hk*/us*。

命令行::

  python cy_quant/ScreenAsOfMomentumBreakout.py --as-of 20240315 --steps 1,2,3,4,5
  python cy_quant/ScreenAsOfMomentumBreakout.py us --bench SPY --as-of 20240315 --steps 1,2
"""

from __future__ import print_function

import argparse
import glob
import logging
import os
import sys
import warnings
from collections import Counter

# 允许 `python cy_quant/ScreenAsOfMomentumBreakout.py` 直接运行（无需设置 PYTHONPATH）
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

import numpy as np
import pandas as pd

from cy_quant.Analyze120MA import Analyze120MA
from abupy.IndicatorBu.ABuNDAtr import calc_atr

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)

_BREAKOUT_FAIL_LABEL = {
    "bars_insufficient": "K线根数不足（high_n/vol_ma_n）",
    "missing_columns": "缺少 high/volume/close 列",
    "high_ref_invalid": "前高无效(NaN/≤0)",
    "price_not_above_prev_high": "收盘未突破前 high_n 日最高价",
    "volume_ma_invalid": "前均量无效(NaN/≤0)",
    "volume_below_threshold": "未放量(成交量未超过倍数×前均量)",
    "price_and_volume": "既未突破前高也未放量",
    "dual_high_fail": "未满足20/55日收盘新高（二选一）",
    "dual_high_ok_vol_fail": "新高满足但未放量",
    "missing_columns_atr": "ATR：缺少 high/low/close",
    "atr_invalid": "ATR 计算无效",
    "atr_not_compressed": "ATR短周期未小于长周期",
    "atr_bars_insufficient": "ATR：K线根数不足",
}

_DEFAULT_STEPS = frozenset({1, 2, 3, 4, 5})


def parse_enabled_steps(steps):
    """
    解析启用的步骤编号 1～5。None / 空 / "all" → 全开。
    支持: "1,2,3" / "1, 5" / [1,2,3] / {1,2}
    """
    if steps is None:
        return set(_DEFAULT_STEPS)
    if isinstance(steps, str):
        t = steps.strip().lower()
        if t in ("", "all", "*", "1-5", "1,2,3,4,5"):
            return set(_DEFAULT_STEPS)
        out = set()
        for p in t.replace(";", ",").split(","):
            p = p.strip()
            if not p:
                continue
            v = int(p)
            if v < 1 or v > 5:
                raise ValueError("enabled_steps 仅支持 1～5，非法: %r" % p)
            out.add(v)
        if not out:
            return set(_DEFAULT_STEPS)
        return out
    if isinstance(steps, (set, frozenset)):
        out = {int(x) for x in steps}
    elif isinstance(steps, (list, tuple)):
        out = {int(x) for x in steps}
    else:
        raise TypeError("enabled_steps 类型不支持: %s" % type(steps))
    for v in out:
        if v < 1 or v > 5:
            raise ValueError("enabled_steps 仅支持 1～5，非法: %s" % v)
    if not out:
        return set(_DEFAULT_STEPS)
    return out


def _np_quantile_local(arr, q):
    a = np.asarray(arr, dtype=float)
    if hasattr(np, "quantile"):
        return float(np.quantile(a, q))
    return float(np.percentile(a, q * 100.0))


def _atr_compression_ok(df_trunc, atr_short_n, atr_long_n):
    """最后一根 K：ATR(短) < ATR(长)。"""
    atr_short_n = int(atr_short_n)
    atr_long_n = int(atr_long_n)
    need = max(atr_short_n, atr_long_n) + 1
    if len(df_trunc) < need:
        return False, {
            "fail_reason": "atr_bars_insufficient",
            "need_bars": need,
            "have_bars": len(df_trunc),
        }
    if not {"high", "low", "close"}.issubset(df_trunc.columns):
        miss = sorted({"high", "low", "close"} - set(df_trunc.columns))
        return False, {"fail_reason": "missing_columns_atr", "missing": ",".join(miss)}
    h = pd.to_numeric(df_trunc["high"], errors="coerce")
    lo = pd.to_numeric(df_trunc["low"], errors="coerce")
    c = pd.to_numeric(df_trunc["close"], errors="coerce")
    a_s = calc_atr(h, lo, c, atr_short_n)
    a_l = calc_atr(h, lo, c, atr_long_n)
    if len(a_s) == 0 or np.isnan(a_s[-1]) or np.isnan(a_l[-1]):
        return False, {"fail_reason": "atr_invalid"}
    v_s, v_l = float(a_s[-1]), float(a_l[-1])
    if not (v_s < v_l):
        return False, {
            "fail_reason": "atr_not_compressed",
            "atr_short": round(v_s, 6),
            "atr_long": round(v_l, 6),
        }
    return True, {
        "atr_short": round(v_s, 6),
        "atr_long": round(v_l, 6),
    }


def _dual_high_volume_ok(df_trunc, xd_short, xd_long, vol_ma_n, vol_mult):
    """
    信号日：收盘为近 xd_short / xd_long 日「含当日」收盘窗口最高价之一，且放量。
    成交量：当日 > vol_mult × 前 vol_ma_n 日均量（不含当日）。
    """
    xd_short = int(xd_short)
    xd_long = int(xd_long)
    vol_ma_n = int(vol_ma_n)
    vol_mult = float(vol_mult)
    need_price = max(xd_short, xd_long)
    nmin = max(need_price + 1, vol_ma_n + 1)
    if len(df_trunc) < nmin:
        return False, {
            "fail_reason": "bars_insufficient",
            "need_bars": nmin,
            "have_bars": len(df_trunc),
        }
    if not {"close", "volume"}.issubset(df_trunc.columns):
        miss = sorted({"close", "volume"} - set(df_trunc.columns))
        return False, {"fail_reason": "missing_columns", "missing": ",".join(miss)}

    close = pd.to_numeric(df_trunc["close"], errors="coerce")
    today_ind = len(close) - 1
    if today_ind < need_price - 1:
        return False, {"fail_reason": "bars_insufficient"}

    win_s = close.iloc[today_ind - xd_short + 1 : today_ind + 1]
    win_l = close.iloc[today_ind - xd_long + 1 : today_ind + 1]
    last_c = float(close.iloc[-1])
    max_s = float(win_s.max())
    max_l = float(win_l.max())
    short_ok = last_c == max_s
    long_ok = last_c == max_l
    if not short_ok and not long_ok:
        return False, {
            "fail_reason": "dual_high_fail",
            "close": round(last_c, 4),
            "max_close_%dd" % xd_short: round(max_s, 4),
            "max_close_%dd" % xd_long: round(max_l, 4),
        }

    vol_tail = df_trunc["volume"].iloc[-(vol_ma_n + 1) : -1]
    vol_ma = float(pd.to_numeric(vol_tail, errors="coerce").mean())
    vol_last = float(pd.to_numeric(df_trunc["volume"].iloc[-1], errors="coerce"))
    if np.isnan(vol_ma) or vol_ma <= 0:
        return False, {"fail_reason": "volume_ma_invalid", "vol_ma": vol_ma}
    if not (vol_last > vol_mult * vol_ma):
        vol_ratio = vol_last / vol_ma if vol_ma else None
        return False, {
            "fail_reason": "dual_high_ok_vol_fail",
            "vol_last": round(vol_last, 4),
            "vol_ma_prev": round(vol_ma, 4),
            "vol_ratio": round(vol_ratio, 4) if vol_ratio is not None else None,
            "vol_mult_need": vol_mult,
            "dual_short": short_ok,
            "dual_long": long_ok,
        }

    vol_ratio = vol_last / vol_ma if vol_ma else None
    detail = {
        "dual_high_short_%dd" % xd_short: short_ok,
        "dual_high_long_%dd" % xd_long: long_ok,
        "volume_ma_prev": round(vol_ma, 4),
        "volume_ratio": round(vol_ratio, 4) if vol_ratio is not None else None,
        "close": round(last_c, 4),
    }
    return True, detail

# 与 Analyze120MA 类似：一个参数选市场，默认 A 股；扫描前缀见下，默认基准来自 abu IndexSymbol（可用 --bench 覆盖）
MARKET_PRESETS = {
    "cn": {"prefixes": ["sh", "sz"]},
    "us": {"prefixes": ["us"]},
    "hk": {"prefixes": ["hk"]},
}


def _default_benchmark_symbol_str(market_key):
    """
    与 abu 框架在 benchmark=None 时选用的大盘一致：
    abupy.TradeBu.ABuBenchmark.AbuBenchmark.__init__ 中按 g_market_target 赋值；
    符号定义见 abupy.MarketBu.ABuSymbol.IndexSymbol。

    Symbol.value 与本地 CSV 文件名前缀一致：A 股上证 sh000001，美股 us.IXIC，港股 hkHSI。
    """
    try:
        from abupy.MarketBu.ABuSymbol import IndexSymbol

        if market_key == "cn":
            return IndexSymbol.SH.value
        if market_key == "us":
            return IndexSymbol.IXIC.value
        if market_key == "hk":
            return IndexSymbol.HSI.value
    except Exception:
        pass
    return {"cn": "sh000001", "us": "us.IXIC", "hk": "hkHSI"}[market_key]


def _trade_date_key(val):
    return Analyze120MA._trade_date_key(val)


def _asof_key(as_of):
    s = str(as_of).strip()
    digits = "".join(c for c in s if c.isdigit())
    return digits[:8] if len(digits) >= 8 else digits


def _ensure_ohlcv(df):
    if "date" in df.columns and "trade_date" not in df.columns:
        df = df.rename(columns={"date": "trade_date"})
    vol_col = None
    for c in ("volume", "vol", "成交量"):
        if c in df.columns:
            vol_col = c
            break
    if vol_col and vol_col != "volume":
        df = df.rename(columns={vol_col: "volume"})
    return df


def _read_csv(path):
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        try:
            return pd.read_csv(path, encoding="gbk")
        except Exception:
            return pd.read_csv(path, encoding="utf-8")


def _resolve_latest_kline(csv_dir, stock_input):
    """与 Analyze120MA.debug_analyze_by_stock_code 一致：取文件名排序最新的一份。"""
    file_prefix = Analyze120MA._stock_input_to_file_prefix(stock_input)
    if file_prefix is None:
        return None, None
    patterns = [
        os.path.join(csv_dir, f"{file_prefix}_*.csv"),
        os.path.join(csv_dir, f"{file_prefix}_*"),
    ]
    matched = []
    for pattern in patterns:
        for f in glob.glob(pattern):
            if f not in matched:
                matched.append(f)
    if not matched:
        return None, file_prefix
    matched = sorted(matched, key=lambda x: os.path.basename(x), reverse=True)
    return matched[0], file_prefix


def _slice_through_asof(df, as_of):
    """
    保留 trade_date <= as_of 的 K 线；as_of 非交易日时落在不超过 as_of 的最后一根。
    返回副本，按日期升序；若为空返回 None。
    """
    if df is None or df.empty or "trade_date" not in df.columns:
        return None
    d = df.copy()
    d = d.sort_values("trade_date").reset_index(drop=True)
    d["_k"] = d["trade_date"].map(_trade_date_key)
    ak = _asof_key(as_of)
    if not ak:
        return None
    sub = d[d["_k"] <= ak].drop(columns=["_k"])
    if sub.empty:
        return None
    return sub


def _ma_last(close_series, n):
    """截断序列最后一根上的 MA(n)，不足 n 根则为 NaN。"""
    s = pd.to_numeric(close_series, errors="coerce")
    m = s.rolling(window=int(n), min_periods=int(n)).mean()
    if m.empty:
        return np.nan
    return float(m.iloc[-1])


def _stock_ma_slope_up(close_series, ma_n, slope_bars):
    """
    均线斜率 > 0（向上）：最后一根 MA(ma_n) 严格大于前推 slope_bars 根处同一均线值。
    slope_bars<=0：不检查，返回 (True, NaN)。
    需序列长度 >= ma_n + slope_bars（slope_bars>0 时）。
    """
    ma_n = int(ma_n)
    slope_bars = int(slope_bars)
    if slope_bars <= 0:
        return True, np.nan
    s = pd.to_numeric(close_series, errors="coerce")
    ma = s.rolling(window=ma_n, min_periods=ma_n).mean()
    if len(ma) < ma_n + slope_bars:
        return False, np.nan
    m_now = float(ma.iloc[-1])
    m_prev = float(ma.iloc[-1 - slope_bars])
    if np.isnan(m_now) or np.isnan(m_prev):
        return False, np.nan
    delta = m_now - m_prev
    return m_now > m_prev, delta


def _breakout_volume_ok(df_trunc, high_n, vol_ma_n, vol_mult):
    """
    在 df_trunc 最后一根上判定（与 PickBreakoutVolume 一致）。
    df_trunc 已排序且最后一根为信号日。
    返回 (是否通过, info_dict)；未通过时 info 含 fail_reason 及诊断字段。
    """
    high_n = int(high_n)
    vol_ma_n = int(vol_ma_n)
    vol_mult = float(vol_mult)
    nmin = max(high_n + 1, vol_ma_n + 1)
    if len(df_trunc) < nmin:
        return False, {
            "fail_reason": "bars_insufficient",
            "need_bars": nmin,
            "have_bars": len(df_trunc),
        }
    need_cols = {"close", "high", "volume"}
    if not need_cols.issubset(df_trunc.columns):
        miss = sorted(need_cols - set(df_trunc.columns))
        return False, {"fail_reason": "missing_columns", "missing": ",".join(miss)}

    hh_prev = df_trunc["high"].iloc[-(high_n + 1) : -1].max()
    close_last = float(df_trunc["close"].iloc[-1])
    if np.isnan(hh_prev) or hh_prev <= 0:
        return False, {
            "fail_reason": "high_ref_invalid",
            "hh_prev": hh_prev,
        }
    cond_price = close_last > hh_prev
    vol_tail = df_trunc["volume"].iloc[-(vol_ma_n + 1) : -1]
    vol_ma = float(vol_tail.mean())
    vol_last = float(df_trunc["volume"].iloc[-1])
    if np.isnan(vol_ma) or vol_ma <= 0:
        return False, {
            "fail_reason": "volume_ma_invalid",
            "vol_ma": vol_ma,
        }
    cond_vol = vol_last > vol_mult * vol_ma
    vol_ratio = vol_last / vol_ma if vol_ma else None

    if not cond_price and not cond_vol:
        return False, {
            "fail_reason": "price_and_volume",
            "close": round(close_last, 4),
            "hh_prev": round(float(hh_prev), 4),
            "vol_ratio": round(vol_ratio, 4) if vol_ratio is not None else None,
            "vol_mult_need": vol_mult,
        }
    if not cond_price:
        return False, {
            "fail_reason": "price_not_above_prev_high",
            "close": round(close_last, 4),
            "hh_prev": round(float(hh_prev), 4),
            "vol_ratio": round(vol_ratio, 4) if vol_ratio is not None else None,
        }
    if not cond_vol:
        return False, {
            "fail_reason": "volume_below_threshold",
            "vol_last": round(vol_last, 4),
            "vol_ma_prev": round(vol_ma, 4),
            "vol_ratio": round(vol_ratio, 4) if vol_ratio is not None else None,
            "vol_mult_need": vol_mult,
        }

    detail = {
        "high_prev_n_max": round(float(hh_prev), 4),
        "volume_ma_prev": round(vol_ma, 4),
        "volume_ratio": round(vol_ratio, 4) if vol_ratio is not None else None,
        "breakout_pct_vs_high": round((close_last / hh_prev - 1.0) * 100.0, 4),
    }
    return True, detail


def _forward_returns(full_df, signal_date_val, horizons):
    """在完整序列上按 signal 日收盘价，计算若干持有期简单收益。"""
    out = {}
    if full_df is None or full_df.empty:
        for h in horizons:
            out[f"fwd_ret_{h}d"] = np.nan
        return out
    d = full_df.copy()
    d = _ensure_ohlcv(d)
    d = d.sort_values("trade_date").reset_index(drop=True)
    d["_k"] = d["trade_date"].map(_trade_date_key)
    sk = _trade_date_key(signal_date_val)
    idxs = d.index[d["_k"] == sk].tolist()
    if not idxs:
        for h in horizons:
            out[f"fwd_ret_{h}d"] = np.nan
        return out
    i = int(idxs[-1])
    c0 = float(pd.to_numeric(d.loc[i, "close"], errors="coerce"))
    if np.isnan(c0) or c0 <= 0:
        for h in horizons:
            out[f"fwd_ret_{h}d"] = np.nan
        return out
    for h in horizons:
        h = int(h)
        j = i + h
        if j >= len(d):
            out[f"fwd_ret_{h}d"] = np.nan
            continue
        c1 = float(pd.to_numeric(d.loc[j, "close"], errors="coerce"))
        if np.isnan(c1):
            out[f"fwd_ret_{h}d"] = np.nan
        else:
            out[f"fwd_ret_{h}d"] = round((c1 / c0 - 1.0) * 100.0, 4)
    return out


class ScreenAsOfMomentumBreakout:
    def __init__(
        self,
        as_of,
        bench,
        prefixes=None,
        input_csv=None,
        csv_dir=None,
        bench_ma_n=200,
        stock_ma_n=120,
        stock_ma_slope_bars=1,
        rs_lookback_n=60,
        rs_top_pct=0.2,
        high_n=20,
        vol_ma_n=5,
        vol_mult=1.5,
        atr_short_n=20,
        atr_long_n=60,
        xd_short=20,
        xd_long=55,
        enabled_steps=None,
        forward_horizons=None,
        include_bench_forward=False,
        verbose=False,
        progress_every=200,
    ):
        self.as_of = as_of
        self.bench = bench
        self.csv_dir = os.path.expanduser(csv_dir or "~/abu/data/csv")
        self.scanner = Analyze120MA(prefixes=prefixes, input_csv=input_csv)
        self.scanner.csv_dir = self.csv_dir
        self.bench_ma_n = int(bench_ma_n)
        self.stock_ma_n = int(stock_ma_n)
        self.stock_ma_slope_bars = int(stock_ma_slope_bars)
        self.rs_lookback_n = int(rs_lookback_n)
        self.rs_top_pct = float(rs_top_pct)
        self.high_n = int(high_n)
        self.vol_ma_n = int(vol_ma_n)
        self.vol_mult = float(vol_mult)
        self.atr_short_n = int(atr_short_n)
        self.atr_long_n = int(atr_long_n)
        self.xd_short = int(xd_short)
        self.xd_long = int(xd_long)
        self.enabled_steps = parse_enabled_steps(enabled_steps)
        self.forward_horizons = (
            list(forward_horizons) if forward_horizons is not None else [60, 90]
        )
        self.include_bench_forward = bool(include_bench_forward)
        self.verbose = bool(verbose)
        self.progress_every = max(1, int(progress_every))

    def _steps_label(self):
        return ",".join(str(x) for x in sorted(self.enabled_steps))

    def _compute_min_len(self):
        s = self.enabled_steps
        parts = [1]
        if 2 in s:
            if self.stock_ma_slope_bars > 0:
                parts.append(self.stock_ma_n + self.stock_ma_slope_bars)
            else:
                parts.append(self.stock_ma_n)
        if 3 in s:
            parts.append(self.rs_lookback_n + 1)
        if 4 in s:
            parts.append(max(self.atr_short_n, self.atr_long_n) + 5)
        if 5 in s:
            parts.append(max(self.xd_short, self.xd_long) + 1)
            parts.append(self.vol_ma_n + 1)
        return max(parts)

    def _market_bench_only(self, bench_path):
        """仅读取基准 signal_date / 收盘，不做 MA 过滤（步骤 1 关闭时）。"""
        df = _read_csv(bench_path)
        df = _ensure_ohlcv(df)
        if "close" not in df.columns or "trade_date" not in df.columns:
            return False, "基准 CSV 缺少 trade_date/close", None, None
        trunc = _slice_through_asof(df, self.as_of)
        if trunc is None or trunc.empty:
            return False, "基准在 as_of 前无 K 线", None, None
        close = pd.to_numeric(trunc["close"], errors="coerce")
        last = float(close.iloc[-1])
        detail = {
            "bench_close": round(last, 4),
            "bench_ma": np.nan,
            "bench_ma_n": self.bench_ma_n,
            "signal_date": trunc.iloc[-1]["trade_date"],
            "step1_skipped": True,
        }
        return True, None, detail, df

    def _market_ok(self, bench_path):
        df = _read_csv(bench_path)
        df = _ensure_ohlcv(df)
        if "close" not in df.columns or "trade_date" not in df.columns:
            return False, "基准 CSV 缺少 trade_date/close", None, None
        trunc = _slice_through_asof(df, self.as_of)
        if trunc is None or trunc.empty:
            return False, "基准在 as_of 前无 K 线", None, None
        close = pd.to_numeric(trunc["close"], errors="coerce")
        ma = _ma_last(close, self.bench_ma_n)
        last = float(close.iloc[-1])
        if np.isnan(ma) or np.isnan(last):
            return (
                False,
                "基准均线或收盘价无效（历史可能不足 bench_ma_n）",
                None,
                df,
            )
        ok = last > ma
        detail = {
            "bench_close": round(last, 4),
            "bench_ma": round(ma, 4),
            "bench_ma_n": self.bench_ma_n,
            "signal_date": trunc.iloc[-1]["trade_date"],
        }
        if not ok:
            return (
                False,
                f"收盘未站上 MA{self.bench_ma_n}: close={last:.4f} <= ma={ma:.4f}",
                None,
                df,
            )
        return True, None, detail, df

    def _bench_prefix(self):
        _, pfx = _resolve_latest_kline(self.csv_dir, self.bench)
        return pfx

    def _should_skip_file(self, filepath, bench_prefix):
        base = os.path.basename(filepath)
        if bench_prefix and base.startswith(bench_prefix):
            return True
        return False

    def run(self):
        ak = _asof_key(self.as_of)
        if len(ak) != 8:
            logger.error("as_of 需为 YYYYMMDD（8 位数字）")
            return pd.DataFrame()

        es = self.enabled_steps
        logger.info("启用步骤: %s（1=大盘 2=个股MA 3=RS 4=ATR压缩 5=双新高+放量）", self._steps_label())

        bench_path, bench_pfx = _resolve_latest_kline(self.csv_dir, self.bench)
        if not bench_path:
            logger.error("未找到基准 K 线: %s（目录 %s）", self.bench, self.csv_dir)
            return pd.DataFrame()

        if 1 in es:
            m_ok, m_reason, bench_info, bench_full = self._market_ok(bench_path)
            if not m_ok:
                logger.warning("步骤1 市场过滤未通过: %s", m_reason)
                return pd.DataFrame()
            signal_date = bench_info["signal_date"]
            logger.info(
                "步骤1 通过: signal_date=%s bench_close=%s > MA%d=%s",
                signal_date,
                bench_info["bench_close"],
                self.bench_ma_n,
                bench_info["bench_ma"],
            )
        else:
            m_ok, m_reason, bench_info, bench_full = self._market_bench_only(bench_path)
            if not m_ok:
                logger.warning("基准数据无效: %s", m_reason)
                return pd.DataFrame()
            signal_date = bench_info["signal_date"]
            logger.info(
                "步骤1 已关闭: 使用基准 signal_date=%s bench_close=%s（未做 MA 过滤）",
                signal_date,
                bench_info["bench_close"],
            )

        if 2 in es and self.stock_ma_slope_bars > 0:
            logger.info(
                "步骤2: stock_ma_n=%d，斜率 MA(末)>MA(前推%d根)",
                self.stock_ma_n,
                self.stock_ma_slope_bars,
            )
        elif 2 in es:
            logger.info("步骤2: stock_ma_n=%d（斜率已关）", self.stock_ma_n)
        else:
            logger.info("步骤2 已关闭")

        stock_files = self.scanner.get_stock_files()
        if not stock_files:
            logger.warning("股票文件列表为空")
            return pd.DataFrame()

        n_files = len(stock_files)
        min_len = self._compute_min_len()
        logger.info(
            "待扫描文件 %d，最少 K 线=%d（progress 每 %d）",
            n_files,
            min_len,
            self.progress_every,
        )

        candidates = []
        skipped_bench = 0
        for idx, fp in enumerate(stock_files, start=1):
            if self._should_skip_file(fp, bench_pfx):
                skipped_bench += 1
                continue
            if idx == 1 or idx % self.progress_every == 0 or idx == n_files:
                logger.info(
                    "扫描 %d/%d，候选 %d，跳过基准文件 %d",
                    idx,
                    n_files,
                    len(candidates),
                    skipped_bench,
                )
            parsed = self.scanner.parse_filename(fp)
            if parsed is None:
                continue
            ts_code, _s, _e = parsed
            stock_code = ts_code.split(".")[0] if "." in ts_code else ts_code
            if stock_code.startswith(("399", "000")):
                continue

            df = _read_csv(fp)
            if df is None or df.empty:
                continue
            df = _ensure_ohlcv(df)
            if "close" not in df.columns or "trade_date" not in df.columns:
                continue

            trunc = _slice_through_asof(df, self.as_of)
            if trunc is None or len(trunc) < min_len:
                continue

            close = pd.to_numeric(trunc["close"], errors="coerce")
            slope_delta = np.nan
            ma_slope_delta_out = None

            if 2 in es:
                ma_s = _ma_last(close, self.stock_ma_n)
                last_c = float(close.iloc[-1])
                if np.isnan(ma_s) or np.isnan(last_c) or last_c <= ma_s:
                    continue
                slope_ok, slope_delta = _stock_ma_slope_up(
                    close, self.stock_ma_n, self.stock_ma_slope_bars
                )
                if not slope_ok:
                    continue
                if not np.isnan(slope_delta):
                    ma_slope_delta_out = float(slope_delta)

            r_ret = np.nan
            if len(close) > self.rs_lookback_n:
                c0 = float(close.iloc[-1])
                c_lag = float(close.iloc[-1 - self.rs_lookback_n])
                if not (np.isnan(c0) or np.isnan(c_lag) or c_lag <= 0):
                    r_ret = c0 / c_lag - 1.0
            if 3 in es and (np.isnan(r_ret) or r_ret != r_ret):
                continue

            candidates.append(
                {
                    "ts_code": ts_code,
                    "filepath": fp,
                    "trunc": trunc,
                    "full": df,
                    "rs_ret": float(r_ret) if not np.isnan(r_ret) else np.nan,
                    "ma_slope_delta": ma_slope_delta_out,
                }
            )

        if not candidates:
            logger.warning(
                "无候选（已启用步骤=%s；请检查 K 线长度与各步条件）",
                self._steps_label(),
            )
            return pd.DataFrame()

        logger.info("初始候选（步骤1之后、步骤3分位之前）: %d 只", len(candidates))

        q = np.nan
        pool = candidates
        if 3 in es:
            rs_list = np.array(
                [c["rs_ret"] for c in candidates if not np.isnan(c["rs_ret"])],
                dtype=float,
            )
            if rs_list.size == 0:
                logger.warning("步骤3 需要 RS，但候选 rs_ret 全无效")
                return pd.DataFrame()
            q = _np_quantile_local(rs_list, 1.0 - self.rs_top_pct)
            pool = [c for c in candidates if not np.isnan(c["rs_ret"]) and c["rs_ret"] >= q - 1e-12]
            if not pool:
                logger.warning(
                    "步骤3 RS 分位后为空（top %.1f%% 阈值 ret >= %.6f）",
                    self.rs_top_pct * 100,
                    q,
                )
                return pd.DataFrame()
            logger.info(
                "步骤3 通过: %d 只（分位阈值 rs_ret >= %.6f）",
                len(pool),
                q,
            )
        else:
            logger.info("步骤3 已关闭: 不分 RS 分位")

        rows = []
        brk_reason_counter = Counter()
        atr_reason_counter = Counter()
        debug_samples = []
        debug_atr = []

        for c in pool:
            trunc = c["trunc"]
            ts = c["ts_code"]

            if 4 in es:
                ok_a, atr_d = _atr_compression_ok(
                    trunc, self.atr_short_n, self.atr_long_n
                )
                if not ok_a:
                    reason = atr_d.get("fail_reason", "unknown")
                    atr_reason_counter[reason] += 1
                    if self.verbose:
                        logger.debug("%s 步骤4 ATR: %s %s", ts, reason, atr_d)
                    elif len(debug_atr) < 8:
                        debug_atr.append((ts, reason, atr_d))
                    continue
            else:
                atr_d = {}

            if 5 in es:
                ok_b, brk = _dual_high_volume_ok(
                    trunc,
                    self.xd_short,
                    self.xd_long,
                    self.vol_ma_n,
                    self.vol_mult,
                )
                if not ok_b:
                    reason = brk.get("fail_reason", "unknown")
                    brk_reason_counter[reason] += 1
                    if self.verbose:
                        logger.debug("%s 步骤5: %s %s", ts, reason, brk)
                    elif len(debug_samples) < 8:
                        debug_samples.append((ts, reason, brk))
                    continue
            else:
                brk = {}

            sig = trunc.iloc[-1]["trade_date"]
            last_close = float(pd.to_numeric(trunc.iloc[-1]["close"], errors="coerce"))

            row = {
                "as_of_requested": int(ak) if ak.isdigit() else ak,
                "signal_date": sig,
                "enabled_steps": self._steps_label(),
                "ts_code": c["ts_code"],
                "close": round(last_close, 4) if not np.isnan(last_close) else np.nan,
                "stock_ma_n": self.stock_ma_n if 2 in es else None,
                "stock_ma_slope_bars": self.stock_ma_slope_bars if 2 in es else None,
                "ma_slope_delta": round(c["ma_slope_delta"], 6)
                if c.get("ma_slope_delta") is not None
                else None,
                "rs_lookback_n": self.rs_lookback_n,
                "rs_ret_pct": round(c["rs_ret"] * 100.0, 4)
                if not np.isnan(c["rs_ret"])
                else np.nan,
                "rs_quantile_threshold_pct": round(q * 100.0, 4)
                if 3 in es and not np.isnan(q)
                else np.nan,
                "bench": str(self.bench),
                "bench_signal_close": bench_info["bench_close"],
                "bench_ma_n": self.bench_ma_n,
                "atr_short_n": self.atr_short_n if 4 in es else None,
                "atr_long_n": self.atr_long_n if 4 in es else None,
                "xd_short": self.xd_short if 5 in es else None,
                "xd_long": self.xd_long if 5 in es else None,
            }
            if atr_d:
                row["atr_short_last"] = atr_d.get("atr_short")
                row["atr_long_last"] = atr_d.get("atr_long")
            for k, v in brk.items():
                if k != "fail_reason" and k != "close":
                    row[str(k)] = v
            row.update(_forward_returns(c["full"], sig, self.forward_horizons))
            rows.append(row)

        out = pd.DataFrame(rows)
        if out.empty:
            logger.warning(
                "步骤4/5 后为空；步骤3 后曾 %d 只 | ATR=%s 新高+量=%s",
                len(pool),
                dict(atr_reason_counter),
                dict(brk_reason_counter),
            )
            if atr_reason_counter:
                logger.warning("步骤4 未通过统计:")
                for r, cnt in atr_reason_counter.most_common():
                    logger.warning(
                        "  - %s: %d",
                        _BREAKOUT_FAIL_LABEL.get(r, r),
                        cnt,
                    )
            if brk_reason_counter:
                logger.warning("步骤5 未通过统计:")
                for r, cnt in brk_reason_counter.most_common():
                    logger.warning(
                        "  - %s: %d",
                        _BREAKOUT_FAIL_LABEL.get(r, r),
                        cnt,
                    )
            if debug_atr and not self.verbose:
                for ts, reason, info in debug_atr:
                    logger.info(
                        "  [ATR] %s: %s",
                        ts,
                        {k: v for k, v in info.items() if k != "fail_reason"},
                    )
            if debug_samples and not self.verbose:
                for ts, reason, info in debug_samples:
                    logger.info(
                        "  [突破] %s: %s",
                        ts,
                        {k: v for k, v in info.items() if k != "fail_reason"},
                    )
            return out

        if self.include_bench_forward:
            br = _forward_returns(bench_full, signal_date, self.forward_horizons)
            for k, v in br.items():
                out[f"bench_{k}"] = v

        logger.info(
            "共命中 %d 只（as_of=%s signal_date=%s steps=%s）",
            len(out),
            ak,
            signal_date,
            self._steps_label(),
        )
        return out

    def save_results(self, df, filename=None):
        if df is None or df.empty:
            logger.warning("无数据可保存")
            return
        if filename is None:
            ak = _asof_key(self.as_of)
            pfx = self.scanner.prefixes[0] if self.scanner.prefixes else "screen"
            filename = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "output",
                f"asof_momo_breakout_{pfx}_{ak}.csv",
            )
        d = os.path.dirname(filename)
        if d:
            os.makedirs(d, exist_ok=True)
        df.to_csv(filename, index=False, encoding="utf-8-sig")
        logger.info("已保存: %s", filename)


def main():
    """
    命令行（在项目根目录）::

      python cy_quant/ScreenAsOfMomentumBreakout.py --as-of 20240315
      python cy_quant/ScreenAsOfMomentumBreakout.py us --as-of 20240315
      python cy_quant/ScreenAsOfMomentumBreakout.py hk --as-of 20240315

    程序化请直接调用 _main_impl(market, as_of, ...) 或 ScreenAsOfMomentumBreakout(...)。
    """
    parser = argparse.ArgumentParser(
        description="as_of 截面：可选步骤1～5（大盘/个股MA/RS/ATR/双新高+放量），见 --steps"
    )
    parser.add_argument(
        "market",
        nargs="?",
        default="cn",
        choices=sorted(MARKET_PRESETS.keys()),
        help="市场：cn=A股+上证 sh000001(默认，abu IndexSymbol.SH)，us=IXIC，hk=HSI；可用 --bench 覆盖",
    )
    parser.add_argument(
        "--as-of", required=True, dest="as_of", help="信号日 YYYYMMDD（非交易日则落到上一交易日）"
    )
    parser.add_argument(
        "--bench",
        default=None,
        help="覆盖 abu 默认大盘：cn=IndexSymbol.SH，us=IndexSymbol.IXIC，hk=IndexSymbol.HSI",
    )
    parser.add_argument(
        "--prefixes",
        nargs="+",
        default=None,
        help="覆盖默认扫描前缀（一般不需要，用 market 即可）",
    )
    parser.add_argument("--input-csv", default=None, help="含 ts_code 的 CSV，仅分析其中股票")
    parser.add_argument("--csv-dir", default=None, help="K 线目录，默认 ~/abu/data/csv")
    parser.add_argument(
        "--bench-ma-n",
        type=int,
        default=200,
        help="大盘均线周期，默认 200（与类 ScreenAsOfMomentumBreakout 默认一致）",
    )
    parser.add_argument("--stock-ma-n", type=int, default=120, help="个股均线周期，默认 120")
    parser.add_argument(
        "--stock-ma-slope-bars",
        type=int,
        default=1,
        help="个股 MA 斜率向上：要求 MA(信号日) > MA(信号日前第 N 根)；默认 1=高于昨日均线；0=不检查斜率",
    )
    parser.add_argument("--rs-lookback-n", type=int, default=60, help="RS 回看交易日，默认 60")
    parser.add_argument(
        "--rs-top-pct",
        type=float,
        default=0.2,
        help="RS 取前百分之几，默认 0.2 即 top 20%%",
    )
    parser.add_argument(
        "--steps",
        default=None,
        help="启用的步骤，逗号分隔 1～5，如 1,2,3 或 1,5；默认 1,2,3,4,5 全开",
    )
    parser.add_argument("--atr-short-n", type=int, default=20, help="步骤4 ATR 短周期，默认 20")
    parser.add_argument("--atr-long-n", type=int, default=60, help="步骤4 ATR 长周期，默认 60")
    parser.add_argument("--xd-short", type=int, default=20, help="步骤5 收盘新高短窗口（含当日），默认 20")
    parser.add_argument("--xd-long", type=int, default=55, help="步骤5 收盘新高长窗口（含当日），默认 55")
    parser.add_argument(
        "--high-n",
        type=int,
        default=20,
        help="已弃用于步骤5（步骤5 用 --xd-short/--xd-long）；保留兼容仅写入类字段",
    )
    parser.add_argument("--vol-ma-n", type=int, default=5, help="步骤5 均量窗口（不含当日）")
    parser.add_argument("--vol-mult", type=float, default=1.5, help="步骤5 放量倍数阈值")
    parser.add_argument(
        "--forward-horizons",
        type=int,
        nargs="+",
        default=[60, 90],
        help="远期持有期（交易日），如 60 90",
    )
    parser.add_argument(
        "--include-bench-forward",
        action="store_true",
        help="输出列附带基准同一持有期远期收益",
    )
    parser.add_argument("-o", "--output", default=None, help="输出 CSV 路径")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG：逐只打印突破放量未通过原因",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=200,
        help="扫描文件进度日志间隔，默认每 200 个文件一条",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    return _main_impl(
        market=args.market,
        as_of=args.as_of,
        bench=args.bench,
        prefixes=args.prefixes,
        input_csv=args.input_csv,
        csv_dir=args.csv_dir,
        bench_ma_n=args.bench_ma_n,
        stock_ma_n=args.stock_ma_n,
        stock_ma_slope_bars=args.stock_ma_slope_bars,
        rs_lookback_n=args.rs_lookback_n,
        rs_top_pct=args.rs_top_pct,
        high_n=args.high_n,
        vol_ma_n=args.vol_ma_n,
        vol_mult=args.vol_mult,
        atr_short_n=args.atr_short_n,
        atr_long_n=args.atr_long_n,
        xd_short=args.xd_short,
        xd_long=args.xd_long,
        enabled_steps=args.steps,
        forward_horizons=args.forward_horizons,
        include_bench_forward=args.include_bench_forward,
        output=args.output,
        verbose=args.verbose,
        progress_every=args.progress_every,
    )


def _main_impl(
    market,
    as_of,
    bench=None,
    prefixes=None,
    input_csv=None,
    csv_dir=None,
    bench_ma_n=200,
    stock_ma_n=120,
    stock_ma_slope_bars=1,
    rs_lookback_n=60,
    rs_top_pct=0.2,
    high_n=20,
    vol_ma_n=5,
    vol_mult=1.5,
    atr_short_n=20,
    atr_long_n=60,
    xd_short=20,
    xd_long=55,
    enabled_steps=None,
    forward_horizons=None,
    include_bench_forward=False,
    output=None,
    verbose=False,
    progress_every=200,
):
    preset = MARKET_PRESETS[market]
    bench_eff = bench if bench is not None else _default_benchmark_symbol_str(market)
    prefixes_eff = prefixes if prefixes is not None else preset["prefixes"]
    logger.info(
        "market=%s prefixes=%s bench=%s（可用 --bench 覆盖）",
        market,
        prefixes_eff,
        bench_eff,
    )

    sc = ScreenAsOfMomentumBreakout(
        as_of=as_of,
        bench=bench_eff,
        prefixes=prefixes_eff,
        input_csv=input_csv,
        csv_dir=csv_dir,
        bench_ma_n=bench_ma_n,
        stock_ma_n=stock_ma_n,
        stock_ma_slope_bars=stock_ma_slope_bars,
        rs_lookback_n=rs_lookback_n,
        rs_top_pct=rs_top_pct,
        high_n=high_n,
        vol_ma_n=vol_ma_n,
        vol_mult=vol_mult,
        atr_short_n=atr_short_n,
        atr_long_n=atr_long_n,
        xd_short=xd_short,
        xd_long=xd_long,
        enabled_steps=enabled_steps,
        forward_horizons=forward_horizons,
        include_bench_forward=include_bench_forward,
        verbose=verbose,
        progress_every=progress_every,
    )
    df = sc.run()
    if not df.empty:
        sc.save_results(df, output)
    return df


if __name__ == "__main__":
    # python3.9 cy_quant/ScreenAsOfMomentumBreakout.py hk --as-of 20250501 --steps 1,2,3
    main()
