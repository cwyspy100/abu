"""US phase-C monthly validation without MA120-slope filter.

Universe:
1) price crosses above MA120 (no MA120 slope constraint)
2) monthly cross-sectional validation

Core rules:
- r_close: close_above_p0_days >= 18
- r_updown: up_days >= 12 and down_days <= 10
- r_dd: max_drawdown_from_p0 >= -0.08
- r_ma120: above_ma120_days >= 15
- c_core/c_core_dd/c_core_ma
- soft_top30/40/50
"""

from __future__ import annotations

import argparse
import glob
import os
from typing import Dict, List

import numpy as np
import pandas as pd


def _load_us_files(csv_dir: str, max_stocks: int) -> List[str]:
    files = sorted(f for f in glob.glob(os.path.join(csv_dir, "us*")) if os.path.isfile(f))
    # keep equities like usAAPL..., skip index-style us.INX/us.DJI with dot
    files = [f for f in files if "." not in os.path.basename(f).split("_")[0]]
    return files[:max_stocks]


def build_event_panel_no_slope(csv_dir: str, obs_days: int, max_stocks: int) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for fp in _load_us_files(csv_dir, max_stocks):
        sym = os.path.basename(fp).split("_")[0]
        try:
            df = pd.read_csv(fp, usecols=lambda c: c in {"date", "open", "high", "low", "close", "volume"})
        except Exception:
            continue
        if "date" not in df.columns or "close" not in df.columns:
            continue
        df["trade_date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce")
        for c in ["open", "high", "low", "close", "volume"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["trade_date", "close", "high", "low"]).sort_values("trade_date").reset_index(drop=True)
        if len(df) < 300:
            continue

        df["ma120"] = df["close"].rolling(120, min_periods=120).mean()
        df["above"] = df["close"] > df["ma120"]
        last_i = -999
        for i in range(121, len(df) - max(obs_days, 120) - 1):
            if i - last_i < 60:
                continue
            if pd.isna(df.at[i, "ma120"]) or pd.isna(df.at[i - 1, "ma120"]):
                continue
            if not (bool(df.at[i, "above"]) and not bool(df.at[i - 1, "above"])):
                continue

            w = df.iloc[i : i + obs_days].copy()
            if len(w) < obs_days:
                continue
            p0 = float(df.at[i, "close"])
            rets = w["close"].pct_change().fillna(0.0)
            down = rets[rets < 0]
            rows.append(
                {
                    "symbol": sym,
                    "p0_date": df.at[i, "trade_date"],
                    "ret_obs": float(w.iloc[-1]["close"] / p0 - 1),
                    "close_above_p0_days": int((w["close"] > p0).sum()),
                    "above_ma120_days": int((w["close"] > w["ma120"]).sum()),
                    "up_days": int((rets > 0).sum()),
                    "down_days": int((rets < 0).sum()),
                    "sum_down_abs_pct": float((-down).sum()),
                    "max_drawdown_from_p0": float((w["close"] / p0 - 1).min()),
                    "ret_60d": float(df.iloc[i + 60]["close"] / p0 - 1),
                    "ret_90d": float(df.iloc[i + 90]["close"] / p0 - 1),
                    "ret_120d": float(df.iloc[i + 120]["close"] / p0 - 1),
                }
            )
            last_i = i
    return pd.DataFrame(rows)


def attach_market_regime(panel: pd.DataFrame, csv_dir: str) -> pd.DataFrame:
    inx_files = glob.glob(os.path.join(csv_dir, "us.INX*"))
    if not inx_files:
        panel["mkt_up200"] = np.nan
        return panel
    b = pd.read_csv(inx_files[0], usecols=lambda c: c in {"date", "close"})
    b["trade_date"] = pd.to_datetime(b["date"].astype(str), format="%Y%m%d", errors="coerce")
    b["close"] = pd.to_numeric(b["close"], errors="coerce")
    b = b.dropna(subset=["trade_date", "close"]).sort_values("trade_date")
    b["ma200"] = b["close"].rolling(200, min_periods=200).mean()
    b["mkt_up200"] = b["close"] > b["ma200"]
    reg_map = dict(zip(b["trade_date"], b["mkt_up200"]))
    out = panel.copy()
    out["mkt_up200"] = out["eval_date"].map(reg_map)
    return out


def monthly_roll(sub: pd.DataFrame, picked: pd.DataFrame, min_ev_month: int) -> tuple[int, bool, float, float]:
    months = np.array(sorted(sub["eval_month"].dropna().unique()))
    folds = 3
    min_train = 12
    min_valid = 6
    rows = []
    for fold in range(folds):
        te = min_train + fold * max(1, (len(months) - min_train - min_valid) // max(folds - 1, 1))
        ve = min(len(months), te + min_valid)
        vms = months[te:ve]
        if len(vms) < min_valid:
            continue
        v_all = sub[sub["eval_month"].isin(vms)]
        v_hit = picked[picked["eval_month"].isin(vms)]
        b = float(v_all["ret_120d"].mean())
        r = float(v_hit["ret_120d"].mean()) if not v_hit.empty else np.nan
        ev = float(v_hit.groupby("eval_month").size().mean()) if not v_hit.empty else 0.0
        rows.append({"ev": ev, "alpha": r - b if pd.notna(r) else np.nan})
    rr = pd.DataFrame(rows)
    if rr.empty:
        return 0, False, np.nan, np.nan
    eff = int(((rr["ev"] >= min_ev_month) & (rr["alpha"] > 0)).sum())
    return eff, eff >= 2, float(rr["alpha"].mean()), float(rr["ev"].mean())


def run(csv_dir: str, output_dir: str, obs_days: int, max_stocks: int) -> str:
    panel = build_event_panel_no_slope(csv_dir, obs_days, max_stocks)
    if panel.empty:
        raise RuntimeError("No events built for US panel.")
    panel["eval_date"] = pd.to_datetime(panel["p0_date"])
    panel["eval_month"] = panel["eval_date"].dt.to_period("M").dt.to_timestamp("M")
    panel = attach_market_regime(panel, csv_dir)

    rules = {
        "r_close": panel["close_above_p0_days"] >= 18,
        "r_updown": (panel["up_days"] >= 12) & (panel["down_days"] <= 10),
        "r_dd": panel["max_drawdown_from_p0"] >= -0.08,
        "r_ma120": panel["above_ma120_days"] >= 15,
    }
    combos = {
        "c_core": rules["r_close"] & rules["r_updown"],
        "c_core_dd": rules["r_close"] & rules["r_updown"] & rules["r_dd"],
        "c_core_ma": rules["r_close"] & rules["r_updown"] & rules["r_ma120"],
    }

    panel["s_close"] = panel.groupby("eval_month")["close_above_p0_days"].rank(pct=True)
    panel["s_ud_raw"] = panel["up_days"] - panel["down_days"]
    panel["s_ud"] = panel.groupby("eval_month")["s_ud_raw"].rank(pct=True)
    panel["s_dd"] = panel.groupby("eval_month")["max_drawdown_from_p0"].rank(pct=True)
    panel["s_ma"] = panel.groupby("eval_month")["above_ma120_days"].rank(pct=True)
    panel["soft"] = 0.35 * panel["s_close"] + 0.30 * panel["s_ud"] + 0.20 * panel["s_dd"] + 0.15 * panel["s_ma"]

    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"us_monthly_phase_c_no_slope_{stamp}")
    os.makedirs(out_dir, exist_ok=True)
    panel.to_csv(os.path.join(out_dir, "us_panel_obs_no_slope.csv"), index=False, encoding="utf-8-sig")

    rows: List[Dict[str, object]] = []
    for regime in ["all", "up200"]:
        sub = panel if regime == "all" else panel[panel["mkt_up200"] == True]
        if len(sub) < 500:
            continue

        for name, mask in [
            ("r_close", rules["r_close"]),
            ("r_updown", rules["r_updown"]),
            ("r_dd", rules["r_dd"]),
            ("r_ma120", rules["r_ma120"]),
            ("c_core", combos["c_core"]),
            ("c_core_dd", combos["c_core_dd"]),
            ("c_core_ma", combos["c_core_ma"]),
        ]:
            m = mask.loc[sub.index]
            pick = sub[m].copy()
            if pick.empty:
                continue
            e8, s8, a8, ev8 = monthly_roll(sub, pick, 8)
            e12, s12, a12, ev12 = monthly_roll(sub, pick, 12)
            rows.append(
                {
                    "regime": regime,
                    "rule": name,
                    "events": int(len(pick)),
                    "ret120": float(pick["ret_120d"].mean()),
                    "alpha120": float(pick["ret_120d"].mean() - sub["ret_120d"].mean()),
                    "stable8": s8,
                    "stable12": s12,
                    "eff8": e8,
                    "eff12": e12,
                    "avg_ev12": ev12,
                    "avg_alpha12": a12,
                }
            )

        for pct in [0.3, 0.4, 0.5]:
            picks = []
            for _, g in sub.groupby("eval_month"):
                if g.empty:
                    continue
                k = max(1, int(np.ceil(len(g) * pct)))
                picks.append(g.sort_values("soft", ascending=False).head(k))
            pick = pd.concat(picks, ignore_index=True) if picks else pd.DataFrame()
            if pick.empty:
                continue
            e8, s8, a8, ev8 = monthly_roll(sub, pick, 8)
            e12, s12, a12, ev12 = monthly_roll(sub, pick, 12)
            rows.append(
                {
                    "regime": regime,
                    "rule": f"soft_top{int(pct * 100)}",
                    "events": int(len(pick)),
                    "ret120": float(pick["ret_120d"].mean()),
                    "alpha120": float(pick["ret_120d"].mean() - sub["ret_120d"].mean()),
                    "stable8": s8,
                    "stable12": s12,
                    "eff8": e8,
                    "eff12": e12,
                    "avg_ev12": ev12,
                    "avg_alpha12": a12,
                }
            )

    res = pd.DataFrame(rows).sort_values(["stable12", "stable8", "alpha120"], ascending=[False, False, False])
    res.to_csv(os.path.join(out_dir, "monthly_results_no_slope.csv"), index=False, encoding="utf-8-sig")
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="US monthly phase-C validation without MA120 slope filter.")
    parser.add_argument("--csv-dir", default="/Users/water/abu/csv_his")
    parser.add_argument("--output-dir", default="cy_quant/output")
    parser.add_argument("--obs-days", type=int, default=20)
    parser.add_argument("--max-stocks", type=int, default=1200)
    args = parser.parse_args()
    out = run(args.csv_dir, args.output_dir, args.obs_days, args.max_stocks)
    print(f"输出目录: {out}")


if __name__ == "__main__":
    main()
