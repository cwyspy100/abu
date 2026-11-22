#!/usr/bin/env python3
"""A/HK/US obs=10 candidate generation and 120d-only evaluation on abu/data/csv."""

from __future__ import annotations

import argparse
import glob
import os
import sys
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


def _norm_a_symbol(symbol: str) -> str:
    s = str(symbol or "").strip().lower()
    if s.startswith(("sh", "sz")) and len(s) >= 8:
        return s
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) != 6:
        return s
    return ("sh" + digits) if digits.startswith(("6", "9", "5")) else ("sz" + digits)


def load_a_industry_map(basic_csv: str) -> Dict[str, str]:
    if not basic_csv or (not os.path.exists(basic_csv)):
        return {}
    try:
        df = pd.read_csv(basic_csv, usecols=lambda c: c in {"ts_code", "industry"})
    except Exception:
        return {}
    if df.empty or "ts_code" not in df.columns:
        return {}
    if "industry" not in df.columns:
        df["industry"] = "UNKNOWN"
    sym = (
        df["ts_code"]
        .astype(str)
        .str.upper()
        .str.replace(".SH", "", regex=False)
        .str.replace(".SZ", "", regex=False)
    )
    df["symbol"] = sym.map(_norm_a_symbol)
    return dict(zip(df["symbol"], df["industry"].fillna("UNKNOWN")))


def load_market_files(csv_dir: str, prefix: str, max_files: int) -> List[str]:
    files = [f for f in glob.glob(os.path.join(csv_dir, f"{prefix}*")) if os.path.isfile(f)]
    files = [f for f in files if not os.path.basename(f).startswith(f"{prefix}.")]
    return sorted(files)[:max_files]


def parse_symbol(path: str, prefix: str) -> str:
    b = os.path.basename(path)
    s = b[len(prefix) :].split("_")[0]
    return f"{prefix}{s}"


def build_events(csv_dir: str, prefix: str, obs_days: int, max_files: int) -> pd.DataFrame:
    events: List[Dict] = []
    for fp in load_market_files(csv_dir, prefix, max_files):
        try:
            d = pd.read_csv(fp)
        except Exception:
            continue
        if "close" not in d.columns:
            continue
        dcol = "Unnamed: 0" if "Unnamed: 0" in d.columns else ("date" if "date" in d.columns else None)
        if dcol is None:
            continue

        d["dt"] = pd.to_datetime(d[dcol].astype(str), errors="coerce")
        d = d.dropna(subset=["dt", "close"]).sort_values("dt").reset_index(drop=True)
        if len(d) < (140 + obs_days + 120):
            continue

        d["ma120"] = d["close"].rolling(120, min_periods=120).mean()
        d["ma120_prev"] = d["ma120"].shift(1)
        d["close_prev"] = d["close"].shift(1)
        d["ma120_slope5"] = d["ma120"] - d["ma120"].shift(5)
        cross = (d["close"] > d["ma120"]) & (d["close_prev"] <= d["ma120_prev"]) & (d["ma120_slope5"] > 0)
        idx = np.where(cross.fillna(False).values)[0]
        if len(idx) == 0:
            continue

        sym = parse_symbol(fp, prefix)
        c = d["close"].values
        dates = d["dt"].values
        for i in idx:
            p0 = i
            ev = i + obs_days
            buy = ev + 1
            s120 = buy + 120
            if s120 >= len(d):
                continue

            p0c = float(c[p0])
            evc = float(c[ev])
            buyc = float(c[buy])
            obs_slice = c[p0 + 1 : ev + 1]
            if len(obs_slice) == 0:
                continue

            close_above = int((obs_slice > p0c).sum())
            ret_obs = float(evc / p0c - 1.0)
            dd = float((obs_slice / p0c - 1.0).min())
            trend = close_above / float(obs_days)
            score = 60.0 * trend + 25.0 * max(ret_obs, 0.0) + 15.0 * (1.0 + dd)

            events.append(
                {
                    "market": prefix,
                    "symbol": sym,
                    "p0_date": pd.Timestamp(dates[p0]).date().isoformat(),
                    "eval_date": pd.Timestamp(dates[ev]).date().isoformat(),
                    "buy_date": pd.Timestamp(dates[buy]).date().isoformat(),
                    "sell_date_120d": pd.Timestamp(dates[s120]).date().isoformat(),
                    "close_above_p0_days": close_above,
                    "ret_obs_10d": ret_obs,
                    "max_drawdown_from_p0": dd,
                    "total_score": score,
                    "ret_120d": float(c[s120] / buyc - 1.0),
                }
            )

    out = pd.DataFrame(events)
    if not out.empty:
        out["eval_date"] = pd.to_datetime(out["eval_date"])
        out["pick_month"] = out["eval_date"].dt.to_period("M").astype(str)
    return out


def add_industry_strength_for_a(panel: pd.DataFrame, industry_map: Dict[str, str]) -> pd.DataFrame:
    if panel.empty:
        return panel
    out = panel.copy()
    out["industry"] = out["symbol"].map(industry_map).fillna("UNKNOWN")
    ind = (
        out.groupby(["pick_month", "industry"], as_index=False)
        .agg(
            ind_count=("symbol", "count"),
            ind_ret_obs_mean=("ret_obs_10d", "mean"),
            ind_close_above_mean=("close_above_p0_days", "mean"),
        )
    )
    ind["industry_strength_raw"] = (
        0.6 * ind["ind_ret_obs_mean"].fillna(0.0)
        + 0.4 * (ind["ind_close_above_mean"].fillna(0.0) / 10.0)
    )
    ind["industry_strength_score"] = (
        ind.groupby("pick_month")["industry_strength_raw"].rank(method="average", pct=True)
    )
    return out.merge(ind, on=["pick_month", "industry"], how="left")


def select_candidates(
    panel: pd.DataFrame,
    obs_days: int = 10,
    use_industry_filter: bool = False,
    industry_top_pct: float = 0.2,
) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    months = sorted(panel["pick_month"].unique())
    train_m, test_m, step = 8, 3, 3
    min_close = max(1, int(np.ceil(obs_days * 0.6)))
    picks: List[pd.DataFrame] = []

    for s in range(0, max(0, len(months) - train_m - test_m + 1), step):
        trm = months[s : s + train_m]
        tem = months[s + train_m : s + train_m + test_m]
        tr = panel[panel["pick_month"].isin(trm)].copy()
        te = panel[panel["pick_month"].isin(tem)].copy()
        if tr.empty or te.empty:
            continue

        gate = max(min_close, float(tr["close_above_p0_days"].quantile(0.6)))
        q_score = float(tr["total_score"].quantile(0.6))
        cand = te[(te["close_above_p0_days"] >= gate) & (te["total_score"] >= q_score)].copy()
        if use_industry_filter and "industry_strength_score" in cand.columns:
            cand = cand[cand["industry_strength_score"] >= (1.0 - float(industry_top_pct))].copy()
        for m, g in cand.groupby("pick_month"):
            top = g.sort_values("total_score", ascending=False).head(30).copy()
            if top.empty:
                continue
            top["train_start"] = trm[0]
            top["train_end"] = trm[-1]
            top["test_start"] = tem[0]
            top["test_end"] = tem[-1]
            top["gate_close_days"] = gate
            top["gate_score"] = q_score
            picks.append(top)
    return pd.concat(picks, ignore_index=True) if picks else pd.DataFrame()


def summary_from_picks(picks: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
    if picks.empty:
        return pd.DataFrame(), {"months": 0}
    monthly = (
        picks.groupby("pick_month", as_index=False)
        .agg(
            picks=("symbol", "count"),
            avg_ret_120d=("ret_120d", "mean"),
            med_ret_120d=("ret_120d", "median"),
            win_rate_120d=("ret_120d", lambda s: float((s > 0).mean())),
        )
        .sort_values("pick_month")
    )
    r = monthly["avg_ret_120d"]
    eq = (1 + r).cumprod()
    n = len(r)
    perf = {
        "months": int(n),
        "total_return": float(eq.iloc[-1] - 1) if n else np.nan,
        "cagr_label": float(eq.iloc[-1] ** (12.0 / n) - 1) if n and eq.iloc[-1] > 0 else np.nan,
        "annual_vol": float(r.std(ddof=0) * np.sqrt(12)) if n > 1 else 0.0,
        "max_drawdown": float((eq / eq.cummax() - 1).min()) if n else np.nan,
        "win_rate_monthly": float((r > 0).mean()) if n else np.nan,
        "pick_count": int(len(picks)),
        "avg_ret_120d_pick": float(picks["ret_120d"].mean()),
        "win_rate_120d_pick": float((picks["ret_120d"] > 0).mean()),
    }
    return monthly, perf


def _to_a_ts_code(symbol: str) -> str:
    s = str(symbol or "").lower().strip()
    if len(s) >= 8 and s[:2] in {"sh", "sz"}:
        return s[2:8]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else ""


def sync_a_picks_to_stock_pool(
    picks_a: pd.DataFrame,
    reset_market_status: bool = True,
) -> int:
    if picks_a.empty:
        return 0

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    from cy_ai.db import Database

    with Database() as db:
        cols = db.query_all(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'stock_pool_ma120'
            """
        )
        colset = {r["COLUMN_NAME"] for r in cols}
        if "industry_strength_score" not in colset:
            db.execute(
                "ALTER TABLE stock_pool_ma120 ADD COLUMN industry_strength_score DECIMAL(8,6) NULL COMMENT '行业强度分位0-1'"
            )
        if "industry_strength_raw" not in colset:
            db.execute(
                "ALTER TABLE stock_pool_ma120 ADD COLUMN industry_strength_raw DECIMAL(14,8) NULL COMMENT '行业强度原始分'"
            )
        if "candidate_score" not in colset:
            db.execute(
                "ALTER TABLE stock_pool_ma120 ADD COLUMN candidate_score DECIMAL(12,6) NULL COMMENT '候选评分'"
            )
        db.commit()

        if reset_market_status:
            db.execute("UPDATE stock_pool_ma120 SET status = 0, updated_at = NOW() WHERE market = 'A股'")
            db.commit()

        rows = picks_a.copy()
        rows["ts_code"] = rows["symbol"].map(_to_a_ts_code)
        rows = rows[rows["ts_code"] != ""].copy()
        rows = rows.drop_duplicates(subset=["ts_code"], keep="first")

        sql = """
            INSERT INTO stock_pool_ma120
                (ts_code, name, industry, break_date, up_percent, market, status,
                 industry_strength_score, industry_strength_raw, candidate_score)
            VALUES
                (%s, %s, %s, %s, %s, 'A股', 1, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                industry = VALUES(industry),
                break_date = VALUES(break_date),
                up_percent = VALUES(up_percent),
                status = 1,
                industry_strength_score = VALUES(industry_strength_score),
                industry_strength_raw = VALUES(industry_strength_raw),
                candidate_score = VALUES(candidate_score),
                updated_at = NOW()
        """
        n = 0
        for _, r in rows.iterrows():
            db.execute(
                sql,
                (
                    str(r["ts_code"]),
                    str(r.get("symbol", "")),
                    str(r.get("industry", "UNKNOWN")),
                    str(r.get("p0_date", "")),
                    float(r.get("ret_obs_10d", 0.0)) * 100.0,
                    float(r.get("industry_strength_score", np.nan)) if pd.notna(r.get("industry_strength_score", np.nan)) else None,
                    float(r.get("industry_strength_raw", np.nan)) if pd.notna(r.get("industry_strength_raw", np.nan)) else None,
                    float(r.get("total_score", np.nan)) if pd.notna(r.get("total_score", np.nan)) else None,
                ),
            )
            n += 1
        db.commit()
        return n


def run(
    csv_dir: str,
    output_dir: str,
    max_files: int,
    recent_months: int,
    use_industry_filter: bool,
    industry_top_pct: float,
    a_basic_csv: str,
    export_ab_compare: bool,
    sync_stock_pool: bool,
    reset_a_market_status: bool,
) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"obs10_ahk_us_latest_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    summary_rows: List[Dict] = []
    latest_all: List[pd.DataFrame] = []
    ab_rows: List[Dict] = []
    market_map = {"a": "sh", "hk": "hk", "us": "us"}
    a_industry_map = load_a_industry_map(a_basic_csv)
    a_latest_for_sync = pd.DataFrame()

    for market, prefix in market_map.items():
        panel = build_events(csv_dir, prefix, obs_days=10, max_files=max_files)
        if market == "a" and use_industry_filter:
            panel = add_industry_strength_for_a(panel, a_industry_map)
        panel.to_csv(os.path.join(out_dir, f"{market}_obs10_event_panel.csv"), index=False, encoding="utf-8-sig")

        picks_no_filter = select_candidates(panel, obs_days=10, use_industry_filter=False, industry_top_pct=industry_top_pct)
        picks = picks_no_filter
        if market == "a" and use_industry_filter:
            picks = select_candidates(panel, obs_days=10, use_industry_filter=True, industry_top_pct=industry_top_pct)
            if export_ab_compare:
                m0, p0 = summary_from_picks(picks_no_filter)
                m1, p1 = summary_from_picks(picks)
                m0.to_csv(os.path.join(out_dir, "a_obs10_monthly_summary_no_industry_filter.csv"), index=False, encoding="utf-8-sig")
                m1.to_csv(os.path.join(out_dir, "a_obs10_monthly_summary_with_industry_filter.csv"), index=False, encoding="utf-8-sig")
                picks_no_filter.to_csv(os.path.join(out_dir, "a_obs10_picks_detail_no_industry_filter.csv"), index=False, encoding="utf-8-sig")
                picks.to_csv(os.path.join(out_dir, "a_obs10_picks_detail_with_industry_filter.csv"), index=False, encoding="utf-8-sig")
                ab_rows.extend(
                    [
                        {"variant": "no_industry_filter", **p0},
                        {"variant": f"industry_top_{industry_top_pct:.2f}", **p1},
                    ]
                )
        picks.to_csv(os.path.join(out_dir, f"{market}_obs10_picks_detail.csv"), index=False, encoding="utf-8-sig")
        monthly, perf = summary_from_picks(picks)
        monthly.to_csv(os.path.join(out_dir, f"{market}_obs10_monthly_summary.csv"), index=False, encoding="utf-8-sig")

        if not picks.empty:
            lm = sorted(picks["pick_month"].unique())[-recent_months:]
            latest = picks[picks["pick_month"].isin(lm)].copy()
            latest.to_csv(
                os.path.join(out_dir, f"{market}_obs10_latest_{recent_months}m_candidates.csv"),
                index=False,
                encoding="utf-8-sig",
            )
            latest_all.append(latest)
            if market == "a":
                a_latest_for_sync = latest.copy()

        row = {
            "market": market,
            "events": int(len(panel)),
            "event_start": panel["eval_date"].min().date().isoformat() if not panel.empty else None,
            "event_end": panel["eval_date"].max().date().isoformat() if not panel.empty else None,
        }
        row.update(perf)
        summary_rows.append(row)

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(os.path.join(out_dir, "obs10_ahk_us_overall_summary.csv"), index=False, encoding="utf-8-sig")
    if ab_rows:
        pd.DataFrame(ab_rows).to_csv(os.path.join(out_dir, "a_industry_filter_ab_summary.csv"), index=False, encoding="utf-8-sig")
    if latest_all:
        pd.concat(latest_all, ignore_index=True).to_csv(
            os.path.join(out_dir, f"all_markets_obs10_latest_{recent_months}m_candidates.csv"),
            index=False,
            encoding="utf-8-sig",
        )
    if sync_stock_pool and (not a_latest_for_sync.empty):
        synced = sync_a_picks_to_stock_pool(a_latest_for_sync, reset_market_status=reset_a_market_status)
        with open(os.path.join(out_dir, "sync_stock_pool_result.txt"), "w", encoding="utf-8") as f:
            f.write(f"synced_rows={synced}\n")
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="A/HK/US obs=10 latest candidates on abu/data/csv")
    parser.add_argument("--csv-dir", default="/Users/water/abu/data/csv")
    parser.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    parser.add_argument("--max-files", type=int, default=2500)
    parser.add_argument("--recent-months", type=int, default=1)
    parser.add_argument("--use-industry-filter", action="store_true", help="A股应用行业强度过滤")
    parser.add_argument("--industry-top-pct", type=float, default=0.2, help="行业强度前多少比例")
    parser.add_argument("--a-basic-csv", default="/Users/water/mylearn/PycharmProjects/abu-master/todolist/stock_A_basic_list.csv")
    parser.add_argument("--export-ab-compare", action="store_true", help="导出A股行业过滤A/B对照")
    parser.add_argument("--sync-stock-pool", action="store_true", help="将A股最新候选同步写入stock_pool_ma120")
    parser.add_argument("--no-reset-a-market-status", action="store_true", help="同步时不先将A股status置0")
    args = parser.parse_args()
    print(
        run(
            args.csv_dir,
            args.output_dir,
            args.max_files,
            args.recent_months,
            args.use_industry_filter,
            args.industry_top_pct,
            args.a_basic_csv,
            args.export_ab_compare,
            args.sync_stock_pool,
            (not args.no_reset_a_market_status),
        )
    )


if __name__ == "__main__":
    main()
