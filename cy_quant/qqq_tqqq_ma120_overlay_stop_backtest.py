#!/usr/bin/env python3
"""QQQ core + TQQQ overlay with drawdown stop and MA120 re-add rules.

Baseline:
  - Hold 50% QQQ core permanently.
  - For the other 50% overlay: when QQQ close > QQQ MA120, switch overlay
    from QQQ to TQQQ; otherwise keep overlay in QQQ.
  - While overlay is in TQQQ, if TQQQ falls 10% from the cycle peak close,
    switch all overlay back to QQQ and wait for the next QQQ regime reset.

Variant:
  - Same 50% QQQ core and same QQQ > MA120 overlay activation.
  - While overlay is in TQQQ, if TQQQ falls 10% from cycle peak close, sell
    50% of current TQQQ overlay into QQQ.
  - If TQQQ falls 20% from cycle peak close, sell all remaining TQQQ overlay
    into QQQ.
  - While QQQ is still above MA120, if TQQQ is 20% below its own MA120,
    move 25% of total portfolio from overlay QQQ back into TQQQ.
  - If TQQQ is 30% below its own MA120, move another 25% of total portfolio
    from overlay QQQ back into TQQQ.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PerfRow:
    strategy: str
    cost_bps: float
    start_date: str
    end_date: str
    trading_days: int
    switches: int
    total_return: float
    cagr: float
    max_drawdown: float
    sharpe: float
    calmar: float
    final_value: float
    avg_tqqq_weight: float
    avg_qqq_weight: float
    signal_on_ratio: float


def _load_close(path: str, symbol: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date_dt"] = pd.to_datetime(df["Unnamed: 0"], errors="coerce")
    df = df.dropna(subset=["date_dt", "close"]).sort_values("date_dt").reset_index(drop=True)
    out = df[["date_dt", "close"]].copy()
    out.rename(columns={"close": symbol}, inplace=True)
    return out


def load_pair(qqq_path: str, tqqq_path: str) -> pd.DataFrame:
    qqq = _load_close(qqq_path, "qqq")
    tqqq = _load_close(tqqq_path, "tqqq")
    df = qqq.merge(tqqq, on="date_dt", how="inner").sort_values("date_dt").reset_index(drop=True)
    df["qqq_ma120"] = df["qqq"].rolling(120, min_periods=120).mean()
    df["tqqq_ma120"] = df["tqqq"].rolling(120, min_periods=120).mean()
    df["qqq_signal_on"] = df["qqq"] > df["qqq_ma120"]
    df["tqqq_vs_ma120"] = df["tqqq"] / df["tqqq_ma120"] - 1.0
    return df.dropna(subset=["qqq_ma120", "tqqq_ma120"]).reset_index(drop=True)


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float((equity / peak - 1.0).min())


def _cagr(equity: pd.Series, dates: pd.Series, initial_capital: float = 1.0) -> float:
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    if years <= 0 or initial_capital <= 0:
        return np.nan
    return float((equity.iloc[-1] / initial_capital) ** (1.0 / years) - 1.0)


def _sharpe(equity: pd.Series) -> float:
    ret = equity.pct_change().dropna()
    if ret.empty or ret.std(ddof=0) == 0:
        return np.nan
    return float(ret.mean() / ret.std(ddof=0) * np.sqrt(252))


def _perf_from_equity(equity: pd.DataFrame, strategy: str, cost_bps: float, switches: int) -> PerfRow:
    eq = equity["equity"].astype(float)
    cagr = _cagr(eq, equity["date"])
    max_dd = _max_drawdown(eq)
    return PerfRow(
        strategy=strategy,
        cost_bps=cost_bps,
        start_date=equity["date"].iloc[0].date().isoformat(),
        end_date=equity["date"].iloc[-1].date().isoformat(),
        trading_days=len(equity),
        switches=switches,
        total_return=float(eq.iloc[-1] - 1.0),
        cagr=cagr,
        max_drawdown=max_dd,
        sharpe=_sharpe(eq),
        calmar=float(cagr / abs(max_dd)) if max_dd < 0 and pd.notna(cagr) else np.nan,
        final_value=float(eq.iloc[-1]),
        avg_tqqq_weight=float(equity["tqqq_weight"].mean()),
        avg_qqq_weight=float(equity["qqq_weight"].mean()),
        signal_on_ratio=float(equity["signal_on"].mean()),
    )


def run_buy_hold(df: pd.DataFrame, cost_bps: float) -> tuple[PerfRow, pd.DataFrame]:
    cost = cost_bps / 10000.0
    qqq_shares = (1.0 - cost) / float(df["qqq"].iloc[0])
    out = df[["date_dt", "qqq"]].copy()
    out["equity"] = qqq_shares * out["qqq"]
    out["qqq_weight"] = 1.0
    out["tqqq_weight"] = 0.0
    out["signal_on"] = 0
    out["date"] = out["date_dt"]
    equity = out[["date", "equity", "qqq_weight", "tqqq_weight", "signal_on"]]
    return _perf_from_equity(equity, "qqq_buy_hold", cost_bps, 0), equity


def _move_value(from_shares: float, from_px: float, to_px: float, gross_value: float, cost: float) -> tuple[float, float]:
    if gross_value <= 0:
        return from_shares, 0.0
    shares_to_sell = min(from_shares, gross_value / from_px)
    proceeds = shares_to_sell * from_px * (1.0 - cost)
    return from_shares - shares_to_sell, proceeds * (1.0 - cost) / to_px


def run_overlay_strategy(df: pd.DataFrame, cost_bps: float, improved: bool) -> tuple[PerfRow, pd.DataFrame, pd.DataFrame]:
    cost = cost_bps / 10000.0
    qqq_core_shares = (0.5 * (1.0 - cost)) / float(df["qqq"].iloc[0])
    overlay_qqq_shares = (0.5 * (1.0 - cost)) / float(df["qqq"].iloc[0])
    overlay_tqqq_shares = 0.0
    switches = 0
    trades = []
    rows = []

    in_active_cycle = False
    peak_tqqq = np.nan
    sold_half = False
    sold_all = False
    rebuy20_done = False
    rebuy30_done = False

    for _, r in df.iterrows():
        date = r["date_dt"]
        qqq_px = float(r["qqq"])
        tqqq_px = float(r["tqqq"])
        signal_on = bool(r["qqq_signal_on"])
        tqqq_vs_ma120 = float(r["tqqq_vs_ma120"])
        action = "hold"

        if signal_on and not in_active_cycle:
            # start active cycle: switch overlay fully from QQQ into TQQQ
            gross_value = overlay_qqq_shares * qqq_px
            overlay_qqq_shares = 0.0
            overlay_tqqq_shares += gross_value * (1.0 - cost) * (1.0 - cost) / tqqq_px if gross_value > 0 else 0.0
            switches += 1
            in_active_cycle = True
            peak_tqqq = tqqq_px
            sold_half = False
            sold_all = False
            rebuy20_done = False
            rebuy30_done = False
            trades.append({"date": date, "type": "cycle_on_switch_to_tqqq", "qqq_px": qqq_px, "tqqq_px": tqqq_px})
            action = "cycle_on"

        elif (not signal_on) and in_active_cycle:
            # end active cycle: everything back to overlay QQQ
            gross_value = overlay_tqqq_shares * tqqq_px
            overlay_tqqq_shares = 0.0
            overlay_qqq_shares += gross_value * (1.0 - cost) * (1.0 - cost) / qqq_px if gross_value > 0 else 0.0
            switches += 1
            in_active_cycle = False
            peak_tqqq = np.nan
            sold_half = False
            sold_all = False
            rebuy20_done = False
            rebuy30_done = False
            trades.append({"date": date, "type": "cycle_off_switch_to_qqq", "qqq_px": qqq_px, "tqqq_px": tqqq_px})
            action = "cycle_off"

        if in_active_cycle and overlay_tqqq_shares > 0:
            peak_tqqq = max(float(peak_tqqq), tqqq_px)
            dd = tqqq_px / peak_tqqq - 1.0 if peak_tqqq > 0 else 0.0

            if improved:
                if (not sold_all) and dd <= -0.20:
                    gross_value = overlay_tqqq_shares * tqqq_px
                    overlay_tqqq_shares = 0.0
                    overlay_qqq_shares += gross_value * (1.0 - cost) * (1.0 - cost) / qqq_px if gross_value > 0 else 0.0
                    sold_all = True
                    sold_half = True
                    trades.append({"date": date, "type": "dd20_sell_all_to_qqq", "qqq_px": qqq_px, "tqqq_px": tqqq_px})
                    action = "dd20_sell_all"
                elif (not sold_half) and dd <= -0.10:
                    shares_to_sell = overlay_tqqq_shares * 0.5
                    gross_value = shares_to_sell * tqqq_px
                    overlay_tqqq_shares -= shares_to_sell
                    overlay_qqq_shares += gross_value * (1.0 - cost) * (1.0 - cost) / qqq_px if gross_value > 0 else 0.0
                    sold_half = True
                    trades.append({"date": date, "type": "dd10_sell_half_to_qqq", "qqq_px": qqq_px, "tqqq_px": tqqq_px})
                    action = "dd10_sell_half"
            else:
                if dd <= -0.10:
                    gross_value = overlay_tqqq_shares * tqqq_px
                    overlay_tqqq_shares = 0.0
                    overlay_qqq_shares += gross_value * (1.0 - cost) * (1.0 - cost) / qqq_px if gross_value > 0 else 0.0
                    sold_all = True
                    sold_half = True
                    trades.append({"date": date, "type": "dd10_sell_all_to_qqq", "qqq_px": qqq_px, "tqqq_px": tqqq_px})
                    action = "dd10_sell_all"

        if improved and in_active_cycle:
            # Re-add TQQQ from overlay QQQ while QQQ trend is still on.
            if (not rebuy20_done) and (tqqq_vs_ma120 <= -0.20):
                target_value = 0.25
                available_value = overlay_qqq_shares * qqq_px
                gross_value = min(target_value, available_value)
                if gross_value > 0:
                    overlay_qqq_shares = max(0.0, overlay_qqq_shares - gross_value / qqq_px)
                    overlay_tqqq_shares += gross_value * (1.0 - cost) * (1.0 - cost) / tqqq_px
                    rebuy20_done = True
                    trades.append({"date": date, "type": "rebuy20pct_below_tqqq_ma120", "qqq_px": qqq_px, "tqqq_px": tqqq_px})
                    action = "rebuy20"
            if (not rebuy30_done) and (tqqq_vs_ma120 <= -0.30):
                target_value = 0.25
                available_value = overlay_qqq_shares * qqq_px
                gross_value = min(target_value, available_value)
                if gross_value > 0:
                    overlay_qqq_shares = max(0.0, overlay_qqq_shares - gross_value / qqq_px)
                    overlay_tqqq_shares += gross_value * (1.0 - cost) * (1.0 - cost) / tqqq_px
                    rebuy30_done = True
                    trades.append({"date": date, "type": "rebuy30pct_below_tqqq_ma120", "qqq_px": qqq_px, "tqqq_px": tqqq_px})
                    action = "rebuy30"

        qqq_value = (qqq_core_shares + overlay_qqq_shares) * qqq_px
        tqqq_value = overlay_tqqq_shares * tqqq_px
        equity = qqq_value + tqqq_value
        rows.append(
            {
                "date": date,
                "equity": equity,
                "qqq_weight": qqq_value / equity if equity > 0 else np.nan,
                "tqqq_weight": tqqq_value / equity if equity > 0 else np.nan,
                "signal_on": int(signal_on),
                "action": action,
                "qqq_close": qqq_px,
                "tqqq_close": tqqq_px,
                "qqq_ma120": float(r["qqq_ma120"]),
                "tqqq_ma120": float(r["tqqq_ma120"]),
                "tqqq_vs_ma120": tqqq_vs_ma120,
                "peak_tqqq": peak_tqqq,
            }
        )

    equity = pd.DataFrame(rows)
    trades_df = pd.DataFrame(trades)
    name = "qqq50_tqqq50_overlay_dd10_20_rebuy" if improved else "qqq50_tqqq50_overlay_dd10_switch_to_qqq"
    perf = _perf_from_equity(equity, name, cost_bps, switches)
    return perf, equity, trades_df


def _write_report(out_dir: str, summary: pd.DataFrame, base_trades: pd.DataFrame, improved_trades: pd.DataFrame, args: argparse.Namespace) -> None:
    lines = [
        "# QQQ/TQQQ Overlay Stop Research",
        "",
        "## Config",
        "",
        f"- QQQ path: `{args.qqq_path}`",
        f"- TQQQ path: `{args.tqqq_path}`",
        f"- Core: `50% QQQ always held`",
        f"- Overlay activation: `QQQ close > QQQ MA120`",
        f"- Baseline stop: `TQQQ drawdown 10% from cycle peak => switch all overlay to QQQ`",
        f"- Improved stop: `10% drawdown => sell half to QQQ; 20% drawdown => sell all to QQQ`",
        f"- Improved rebuy: `TQQQ 20% below its MA120 => buy 25% total; 30% below => buy another 25% total`",
        f"- Cost bps: `{args.cost_bps}`",
        "",
        "## Summary",
        "",
        summary.to_markdown(index=False),
    ]
    if not base_trades.empty:
        lines.extend(["", "## Baseline First 20 Events", "", base_trades.head(20).to_markdown(index=False)])
    if not improved_trades.empty:
        lines.extend(["", "## Improved First 20 Events", "", improved_trades.head(20).to_markdown(index=False)])
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="QQQ/TQQQ overlay stop backtest")
    parser.add_argument("--qqq-path", default="/Users/water/abu/csv_his/usQQQ_20110808_20170808")
    parser.add_argument("--tqqq-path", default="/Users/water/abu/csv_his/usTQQQ_20110808_20170808")
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    df = load_pair(args.qqq_path, args.tqqq_path)
    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S_%f")
    cost_tag = str(args.cost_bps).replace(".", "p")
    out_dir = os.path.join(args.output_dir, f"qqq_tqqq_overlay_stop_cost{cost_tag}_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    bh_perf, bh_equity = run_buy_hold(df, args.cost_bps)
    base_perf, base_equity, base_trades = run_overlay_strategy(df, args.cost_bps, improved=False)
    imp_perf, imp_equity, imp_trades = run_overlay_strategy(df, args.cost_bps, improved=True)

    summary = pd.DataFrame([bh_perf.__dict__, base_perf.__dict__, imp_perf.__dict__]).sort_values("strategy").reset_index(drop=True)
    summary.to_csv(os.path.join(out_dir, "summary.csv"), index=False, encoding="utf-8-sig")
    bh_equity.to_csv(os.path.join(out_dir, "equity_qqq_buy_hold.csv"), index=False, encoding="utf-8-sig")
    base_equity.to_csv(os.path.join(out_dir, "equity_baseline.csv"), index=False, encoding="utf-8-sig")
    imp_equity.to_csv(os.path.join(out_dir, "equity_improved.csv"), index=False, encoding="utf-8-sig")
    base_trades.to_csv(os.path.join(out_dir, "trades_baseline.csv"), index=False, encoding="utf-8-sig")
    imp_trades.to_csv(os.path.join(out_dir, "trades_improved.csv"), index=False, encoding="utf-8-sig")
    _write_report(out_dir, summary, base_trades, imp_trades, args)

    print(out_dir)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
