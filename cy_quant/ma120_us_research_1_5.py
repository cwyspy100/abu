#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""US MA120 research runner for five checks.

Checks:
1) MA120 event right-tail vs same-date random trend stocks.
2) Account-level backtest for obs-window candidates.
3) Market filter comparison using S&P500/QQQ > MA200.
4) Exit rule comparison.
5) QQQ/TQQQ baseline comparison when data exists.
"""

from __future__ import annotations

import argparse
import glob
import os
import warnings
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)


@dataclass
class Position:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    weight: float
    last_price: float
    high_price: float


def symbol_from_path(path: str) -> str:
    return os.path.basename(path).split("_", 1)[0]


def scan_us_files(csv_dir: str, include_etf: bool = True, max_stocks: int = 2500) -> Dict[str, str]:
    files = sorted(f for f in glob.glob(os.path.join(csv_dir, "us*")) if os.path.isfile(f))
    out: Dict[str, str] = {}
    for fp in files:
        sym = symbol_from_path(fp)
        if "." in sym:
            continue
        if not include_etf and sym in {"usQQQ", "usTQQQ", "usSPY", "usVOO"}:
            continue
        out[sym] = fp
        if len(out) >= max_stocks:
            break
    return out


def find_first(csv_dir: str, symbols: Iterable[str]) -> Optional[str]:
    for sym in symbols:
        hits = sorted(glob.glob(os.path.join(csv_dir, f"{sym}*")))
        hits = [h for h in hits if os.path.isfile(h)]
        if hits:
            return hits[0]
    return None


def load_kline(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "close" not in df.columns:
        return pd.DataFrame()
    dcol = "date" if "date" in df.columns else ("Unnamed: 0" if "Unnamed: 0" in df.columns else None)
    if dcol is None:
        return pd.DataFrame()
    out = df.copy()
    raw = out[dcol].astype(str)
    if raw.str.fullmatch(r"\d{8}").mean() > 0.8:
        out["dt"] = pd.to_datetime(raw, format="%Y%m%d", errors="coerce")
    else:
        out["dt"] = pd.to_datetime(raw, errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["dt", "close"]).sort_values("dt").reset_index(drop=True)
    out["ma20"] = out["close"].rolling(20, min_periods=20).mean()
    out["ma120"] = out["close"].rolling(120, min_periods=120).mean()
    out["ma200"] = out["close"].rolling(200, min_periods=200).mean()
    out["ret1"] = out["close"].pct_change()
    return out


def build_events(
    csv_dir: str,
    obs_days: int,
    max_stocks: int,
    max_daily_jump: float,
    include_etf: bool,
) -> tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    files = scan_us_files(csv_dir, include_etf=include_etf, max_stocks=max_stocks)
    cache: Dict[str, pd.DataFrame] = {}
    rows: List[Dict[str, object]] = []
    for sym, fp in files.items():
        k = load_kline(fp)
        if len(k) < 260 + obs_days:
            continue
        if float(k["ret1"].abs().max(skipna=True) or 0.0) > max_daily_jump:
            continue
        cache[sym] = k
        above = (k["close"] > k["ma120"]).fillna(False).astype(bool)
        cross = above & (~above.shift(1, fill_value=False).astype(bool))
        idxs = np.where(cross.fillna(False).values)[0]
        last_i = -999
        for i in idxs:
            if i < 120 or i - last_i < 30:
                continue
            ev = i + obs_days
            buy = ev + 1
            h60 = buy + 60
            h90 = buy + 90
            h120 = buy + 120
            if buy >= len(k):
                continue
            p0 = float(k.at[i, "close"])
            buy_price = float(k.at[buy, "close"])
            if p0 <= 0 or buy_price <= 0:
                continue
            w = k.iloc[i : ev + 1].copy()
            if len(w) < obs_days:
                continue
            rets = w["close"].pct_change().fillna(0.0)
            close_above = int((w["close"] > p0).sum())
            above_ma120 = int((w["close"] > w["ma120"]).sum())
            up_days = int((rets > 0).sum())
            down_days = int((rets < 0).sum())
            dd = float((w["close"] / p0 - 1.0).min())
            ret_obs = float(w.iloc[-1]["close"] / p0 - 1.0)
            score = (
                35.0 * close_above / obs_days
                + 25.0 * above_ma120 / obs_days
                + 20.0 * max(up_days - down_days, 0) / obs_days
                + 10.0 * max(ret_obs, 0.0)
                + 10.0 * (1.0 + min(dd, 0.0))
            )
            rows.append(
                {
                    "symbol": sym,
                    "p0_idx": i,
                    "p0_date": k.at[i, "dt"],
                    "eval_date": k.at[ev, "dt"],
                    "buy_idx": buy,
                    "buy_date": k.at[buy, "dt"],
                    "close_above_p0_days": close_above,
                    "above_ma120_days": above_ma120,
                    "up_days": up_days,
                    "down_days": down_days,
                    "ret_obs": ret_obs,
                    "max_drawdown_from_p0": dd,
                    "score": score,
                    "ret_60d": float(k.at[h60, "close"] / buy_price - 1.0) if h60 < len(k) else np.nan,
                    "ret_90d": float(k.at[h90, "close"] / buy_price - 1.0) if h90 < len(k) else np.nan,
                    "ret_120d": float(k.at[h120, "close"] / buy_price - 1.0) if h120 < len(k) else np.nan,
                }
            )
            last_i = i
    panel = pd.DataFrame(rows)
    if not panel.empty:
        panel["buy_month"] = pd.to_datetime(panel["buy_date"]).dt.to_period("M").astype(str)
    return panel, cache


def attach_market(panel: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    if panel.empty or market.empty:
        panel["mkt_up200"] = np.nan
        return panel
    m = market[["dt", "close", "ma200"]].dropna().copy()
    m["mkt_up200"] = m["close"] > m["ma200"]
    out = pd.merge_asof(
        panel.sort_values("buy_date"),
        m[["dt", "mkt_up200"]].sort_values("dt"),
        left_on="buy_date",
        right_on="dt",
        direction="backward",
    )
    return out.drop(columns=["dt"])


def select_candidates(panel: pd.DataFrame, obs_days: int, top_n: int) -> pd.DataFrame:
    if panel.empty:
        return panel
    min_close = max(1, int(np.ceil(obs_days * 0.6)))
    min_ma = max(1, int(np.ceil(obs_days * 0.7)))
    cand = panel[
        (panel["close_above_p0_days"] >= min_close)
        & (panel["above_ma120_days"] >= min_ma)
        & (panel["ret_obs"] > 0)
        & (panel["max_drawdown_from_p0"] >= -0.08)
    ].copy()
    cand["rank_in_month"] = cand.groupby("buy_month")["score"].rank(method="first", ascending=False)
    return cand[cand["rank_in_month"] <= top_n].sort_values(["buy_date", "rank_in_month"]).reset_index(drop=True)


def summarize_returns(label: str, s: pd.Series) -> Dict[str, object]:
    r = pd.to_numeric(s, errors="coerce").dropna()
    if r.empty:
        return {"group": label, "n": 0}
    pos = r[r > 0].sort_values(ascending=False)
    top_share = np.nan
    if float(pos.sum()) > 0:
        top_share = float(pos.head(max(1, int(np.ceil(len(pos) * 0.1)))).sum() / pos.sum())
    return {
        "group": label,
        "n": int(len(r)),
        "mean": float(r.mean()),
        "median": float(r.median()),
        "win_rate": float((r > 0).mean()),
        "q10": float(r.quantile(0.10)),
        "q25": float(r.quantile(0.25)),
        "q75": float(r.quantile(0.75)),
        "q90": float(r.quantile(0.90)),
        "tail_gt20": float((r >= 0.20).mean()),
        "tail_gt30": float((r >= 0.30).mean()),
        "loss_lt10": float((r <= -0.10).mean()),
        "winner_top10_share": top_share,
    }


def right_tail(panel: pd.DataFrame, cache: Dict[str, pd.DataFrame], random_mult: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    cand = select_candidates(panel, obs_days=int(panel.attrs.get("obs_days", 10)), top_n=30)
    symbols = sorted(cache.keys())
    rows: List[Dict[str, object]] = []
    for _, row in cand.dropna(subset=["ret_120d"]).iterrows():
        rows.append({"group": "candidate", "symbol": row["symbol"], "buy_date": row["buy_date"], "ret_120d": row["ret_120d"]})
        sample = rng.choice(symbols, size=min(len(symbols), random_mult * 20), replace=False)
        n = 0
        for sym in sample:
            if n >= random_mult:
                break
            k = cache.get(str(sym))
            if k is None or k.empty:
                continue
            idx = k.index[k["dt"] >= row["buy_date"]]
            if len(idx) == 0:
                continue
            i = int(idx[0])
            h = i + 120
            if h >= len(k):
                continue
            if pd.isna(k.at[i, "ma120"]) or float(k.at[i, "close"]) <= float(k.at[i, "ma120"]):
                continue
            ret = float(k.at[h, "close"] / k.at[i, "close"] - 1.0)
            rows.append({"group": "random_trend", "symbol": sym, "buy_date": row["buy_date"], "ret_120d": ret})
            n += 1
    detail = pd.DataFrame(rows)
    summary = pd.DataFrame([summarize_returns(g, d["ret_120d"]) for g, d in detail.groupby("group")])
    return detail, summary


def row_on_or_before(k: pd.DataFrame, date: pd.Timestamp) -> Optional[pd.Series]:
    rows = k[k["dt"] <= date]
    return None if rows.empty else rows.iloc[-1]


def should_exit(pos: Position, row: pd.Series, exit_rule: str, stop_pct: float) -> Optional[str]:
    price = float(row["close"])
    ret = price / pos.entry_price - 1.0
    if exit_rule in {"stop5_ma120", "stop8_trail20"} and ret <= -stop_pct:
        return "stop"
    if exit_rule in {"ma120", "stop5_ma120"} and pd.notna(row["ma120"]) and price < float(row["ma120"]):
        return "below_ma120"
    if exit_rule == "stop8_trail20" and pd.notna(row["ma20"]) and price < float(row["ma20"]) and pos.high_price / pos.entry_price - 1.0 >= 0.08:
        return "trail_ma20"
    return None


def account_backtest(
    label: str,
    candidates: pd.DataFrame,
    cache: Dict[str, pd.DataFrame],
    market: pd.DataFrame,
    market_filter: str,
    exit_rule: str,
    initial_weight: float,
    total_cap: float,
    max_positions: int,
    stop_pct: float,
    cost_oneway: float,
) -> tuple[pd.DataFrame, pd.DataFrame, Dict[str, object]]:
    if candidates.empty or market.empty:
        return pd.DataFrame(), pd.DataFrame(), {"label": label, "days": 0}
    by_date: Dict[pd.Timestamp, List[pd.Series]] = {}
    for _, r in candidates.iterrows():
        by_date.setdefault(pd.Timestamp(r["buy_date"]), []).append(r)
    start = pd.Timestamp(candidates["buy_date"].min())
    end = pd.Timestamp(candidates["buy_date"].max()) + pd.Timedelta(days=180)
    cal = market[(market["dt"] >= start) & (market["dt"] <= min(end, market["dt"].max()))]["dt"].tolist()
    pos: Dict[str, Position] = {}
    trades: List[Dict[str, object]] = []
    daily: List[Dict[str, object]] = []
    equity = 1.0
    for date in cal:
        day_ret = 0.0
        to_close: List[tuple[str, str, float]] = []
        for sym, p in list(pos.items()):
            r = row_on_or_before(cache[sym], date)
            if r is None:
                continue
            price = float(r["close"])
            if p.last_price > 0:
                day_ret += p.weight * (price / p.last_price - 1.0)
            p.high_price = max(p.high_price, price)
            reason = should_exit(p, r, exit_rule, stop_pct)
            if reason:
                to_close.append((sym, reason, price))
            p.last_price = price
        for sym, reason, price in to_close:
            p = pos.pop(sym)
            day_ret -= cost_oneway * p.weight
            trades.append(
                {
                    "symbol": sym,
                    "entry_date": p.entry_date,
                    "exit_date": date,
                    "entry_price": p.entry_price,
                    "exit_price": price,
                    "ret": price / p.entry_price - 1.0,
                    "reason": reason,
                }
            )
        mr = row_on_or_before(market, date)
        mkt_ok = True
        if market_filter == "up200":
            mkt_ok = bool(mr is not None and pd.notna(mr["ma200"]) and float(mr["close"]) > float(mr["ma200"]))
        if mkt_ok:
            for r in by_date.get(pd.Timestamp(date), []):
                sym = str(r["symbol"])
                if sym in pos or sym not in cache or len(pos) >= max_positions:
                    continue
                exposure = sum(p.weight for p in pos.values())
                if exposure + initial_weight > total_cap + 1e-12:
                    continue
                kr = row_on_or_before(cache[sym], date)
                if kr is None:
                    continue
                price = float(kr["close"])
                pos[sym] = Position(sym, pd.Timestamp(date), price, initial_weight, price, price)
                day_ret -= cost_oneway * initial_weight
        equity *= 1.0 + day_ret
        daily.append({"date": date, "equity": equity, "day_ret": day_ret, "active_n": len(pos), "exposure": sum(p.weight for p in pos.values())})
    ddf = pd.DataFrame(daily)
    tdf = pd.DataFrame(trades)
    if ddf.empty:
        return ddf, tdf, {"label": label, "days": 0}
    eq = ddf["equity"]
    years = (pd.Timestamp(ddf["date"].iloc[-1]) - pd.Timestamp(ddf["date"].iloc[0])).days / 365.25
    summary = {
        "label": label,
        "market_filter": market_filter,
        "exit_rule": exit_rule,
        "days": int(len(ddf)),
        "start_date": str(pd.Timestamp(ddf["date"].iloc[0]).date()),
        "end_date": str(pd.Timestamp(ddf["date"].iloc[-1]).date()),
        "total_return": float(eq.iloc[-1] - 1.0),
        "cagr": float(eq.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and eq.iloc[-1] > 0 else np.nan,
        "max_drawdown": float((eq / eq.cummax() - 1.0).min()),
        "trades": int(len(tdf)),
        "win_rate": float((tdf["ret"] > 0).mean()) if not tdf.empty else np.nan,
        "avg_trade_ret": float(tdf["ret"].mean()) if not tdf.empty else np.nan,
        "avg_exposure": float(ddf["exposure"].mean()),
        "max_exposure": float(ddf["exposure"].max()),
    }
    return ddf, tdf, summary


def baseline_perf(name: str, k: pd.DataFrame) -> Dict[str, object]:
    d = k.dropna(subset=["close"]).copy()
    if d.empty:
        return {"label": name, "days": 0}
    eq = d["close"] / float(d["close"].iloc[0])
    years = (d["dt"].iloc[-1] - d["dt"].iloc[0]).days / 365.25
    return {
        "label": name,
        "days": int(len(d)),
        "start_date": str(d["dt"].iloc[0].date()),
        "end_date": str(d["dt"].iloc[-1].date()),
        "total_return": float(eq.iloc[-1] - 1.0),
        "cagr": float(eq.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and eq.iloc[-1] > 0 else np.nan,
        "max_drawdown": float((eq / eq.cummax() - 1.0).min()),
    }


def write_readme(out_dir: str, summaries: pd.DataFrame, right_summary: pd.DataFrame) -> None:
    lines = [
        "# US MA120 Research 1-5",
        "",
        "口径：价格上穿 MA120 后观察 obs_days；筛选稳定站上突破价/MA120、观察期收益为正、回撤不深的股票；再验证未来120日右尾，以及账户级买入卖出。",
        "",
        "## Right-tail summary",
        "",
        right_summary.to_markdown(index=False) if not right_summary.empty else "无结果",
        "",
        "## Account / baseline summary",
        "",
        summaries.to_markdown(index=False) if not summaries.empty else "无结果",
        "",
        "## 解释",
        "",
        "- `candidate`：MA120 上穿后通过10天观察筛选的候选。",
        "- `random_trend`：同一买入日期随机抽取、当日也在 MA120 上方的美股。",
        "- 账户级结果不是满仓押注，默认单股5%、总仓位30%、最多10只。",
        "- 若账户级收益明显弱于右尾验证，说明特征有方向性，但交易系统还需要改进持仓、卖出和加仓。",
    ]
    with open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def run(args: argparse.Namespace) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"ma120_us_research_1_5_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    panel, cache = build_events(args.csv_dir, args.obs_days, args.max_stocks, args.max_daily_jump, args.include_etf)
    panel.attrs["obs_days"] = args.obs_days
    market_path = find_first(args.csv_dir, ["us.INX", "usQQQ", "usSPY"])
    market = load_kline(market_path) if market_path else pd.DataFrame()
    panel = attach_market(panel, market)
    panel.to_csv(os.path.join(out_dir, "us_ma120_event_panel.csv"), index=False, encoding="utf-8-sig")

    candidates = select_candidates(panel, args.obs_days, args.top_n)
    candidates.to_csv(os.path.join(out_dir, "us_ma120_candidates.csv"), index=False, encoding="utf-8-sig")

    rt_detail, rt_summary = right_tail(panel, cache, args.random_mult, args.seed)
    rt_detail.to_csv(os.path.join(out_dir, "right_tail_detail.csv"), index=False, encoding="utf-8-sig")
    rt_summary.to_csv(os.path.join(out_dir, "right_tail_summary.csv"), index=False, encoding="utf-8-sig")

    summaries: List[Dict[str, object]] = []
    for market_filter in ["off", "up200"]:
        for exit_rule, stop_pct in [("ma120", args.stop_pct), ("stop5_ma120", 0.05), ("stop8_trail20", 0.08)]:
            label = f"acct_{market_filter}_{exit_rule}"
            daily, trades, summary = account_backtest(
                label,
                candidates,
                cache,
                market,
                market_filter,
                exit_rule,
                args.initial_weight,
                args.total_cap,
                args.max_positions,
                stop_pct,
                args.cost_oneway,
            )
            daily.to_csv(os.path.join(out_dir, f"{label}_daily.csv"), index=False, encoding="utf-8-sig")
            trades.to_csv(os.path.join(out_dir, f"{label}_trades.csv"), index=False, encoding="utf-8-sig")
            summaries.append(summary)

    for name, syms in [("QQQ_BUYHOLD", ["usQQQ"]), ("TQQQ_BUYHOLD", ["usTQQQ"])]:
        fp = find_first(args.csv_dir, syms)
        if fp:
            summaries.append(baseline_perf(name, load_kline(fp)))

    sdf = pd.DataFrame(summaries)
    sdf.to_csv(os.path.join(out_dir, "account_and_baseline_summary.csv"), index=False, encoding="utf-8-sig")
    write_readme(out_dir, sdf, rt_summary)
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Run US MA120 research checks 1-5.")
    parser.add_argument("--csv-dir", default="/Users/water/abu/csv_his")
    parser.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    parser.add_argument("--obs-days", type=int, default=10)
    parser.add_argument("--max-stocks", type=int, default=2500)
    parser.add_argument("--max-daily-jump", type=float, default=0.35)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--random-mult", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--initial-weight", type=float, default=0.05)
    parser.add_argument("--total-cap", type=float, default=0.30)
    parser.add_argument("--max-positions", type=int, default=10)
    parser.add_argument("--stop-pct", type=float, default=0.05)
    parser.add_argument("--cost-oneway", type=float, default=0.001)
    parser.add_argument("--include-etf", action="store_true")
    args = parser.parse_args()
    out = run(args)
    print(out)


if __name__ == "__main__":
    main()
