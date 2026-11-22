"""Audit local A-share price and finance data for value-momentum research.

This script checks whether the agreed local data sources are clean enough for
the first value + momentum + 12-month-MA validation pass. It does not run a
strategy; it only reports schema, coverage, and splice consistency.
"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


ASHARE_FILE_RE = re.compile(r"^(sh|sz|bj)(\d{6})_(\d{8})_(\d{8})$", re.IGNORECASE)
FINANCE_FILE_RE = re.compile(r"^(\d{6})_(SH|SZ|BJ)_finance\.csv$", re.IGNORECASE)


@dataclass(frozen=True)
class AuditConfig:
    csv_his_dir: Path = Path("/Users/water/abu/csv_his")
    astock_dir: Path = Path("/Users/water/abu/data/csv/astock")
    finance_dir: Path = Path("/Users/water/abu/tushare/finance")
    output_dir: Path = Path("cy_quant/output")
    max_overlap_codes: Optional[int] = None


def ts_code_from_market_code(market: str, code: str) -> str:
    return f"{code}.{market.upper()}"


def ts_code_from_price_path(path: Path) -> Optional[str]:
    match = ASHARE_FILE_RE.match(path.name)
    if not match:
        return None
    market, code, _, _ = match.groups()
    return ts_code_from_market_code(market, code)


def price_file_inventory(root: Path) -> pd.DataFrame:
    rows = []
    if not root.exists():
        return pd.DataFrame(columns=["ts_code", "path", "start", "end", "market"])
    for path in root.iterdir():
        if not path.is_file():
            continue
        match = ASHARE_FILE_RE.match(path.name)
        if not match:
            continue
        market, code, start, end = match.groups()
        rows.append(
            {
                "ts_code": ts_code_from_market_code(market, code),
                "path": str(path),
                "start": pd.to_datetime(start, format="%Y%m%d", errors="coerce"),
                "end": pd.to_datetime(end, format="%Y%m%d", errors="coerce"),
                "market": market.upper(),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["ts_code", "path", "start", "end", "market"])
    return pd.DataFrame(rows).sort_values(["ts_code", "end", "start"])


def latest_file_by_code(inventory: pd.DataFrame) -> Dict[str, str]:
    if inventory.empty:
        return {}
    latest = inventory.sort_values(["ts_code", "end", "start"]).groupby("ts_code", as_index=False).tail(1)
    return dict(zip(latest["ts_code"], latest["path"]))


def read_price_csv(path: str) -> pd.DataFrame:
    needed = {"date", "open", "close", "high", "low", "volume", "pre_close", "p_change"}
    df = pd.read_csv(path, usecols=lambda col: col in needed)
    if "date" not in df.columns:
        return pd.DataFrame()
    df["trade_date"] = pd.to_datetime(df["date"].astype(str).str.split(".").str[0], format="%Y%m%d", errors="coerce")
    for col in ["open", "close", "high", "low", "volume", "pre_close", "p_change"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["trade_date"]).sort_values("trade_date")


def schema_sample(path: Optional[str]) -> Tuple[List[str], int, str, str]:
    if not path:
        return [], 0, "", ""
    df = pd.read_csv(path, nrows=5)
    rows = len(pd.read_csv(path, usecols=[0]))
    date_col = "date" if "date" in df.columns else None
    if not date_col:
        return list(df.columns), rows, "", ""
    all_dates = pd.read_csv(path, usecols=["date"])
    dates = pd.to_datetime(all_dates["date"].astype(str).str.split(".").str[0], format="%Y%m%d", errors="coerce")
    return list(df.columns), rows, str(dates.min().date()), str(dates.max().date())


def audit_overlap(csv_his_files: Dict[str, str], astock_files: Dict[str, str], max_codes: Optional[int]) -> pd.DataFrame:
    common = sorted(set(csv_his_files) & set(astock_files))
    if max_codes is not None:
        common = common[:max_codes]
    rows = []
    for ts_code in common:
        old = read_price_csv(csv_his_files[ts_code])
        new = read_price_csv(astock_files[ts_code])
        if old.empty or new.empty:
            rows.append({"ts_code": ts_code, "status": "missing_readable_price"})
            continue
        old_overlap = old[old["trade_date"].isin(set(new["trade_date"]))]
        new_overlap = new[new["trade_date"].isin(set(old["trade_date"]))]
        if old_overlap.empty or new_overlap.empty:
            rows.append({"ts_code": ts_code, "status": "no_overlap"})
            continue
        merged = old_overlap.merge(new_overlap, on="trade_date", suffixes=("_csv_his", "_astock"))
        close_abs = (merged["close_csv_his"] - merged["close_astock"]).abs()
        close_base = merged[["close_csv_his", "close_astock"]].abs().max(axis=1).replace(0, np.nan)
        close_rel = close_abs / close_base
        pchg_abs = (
            (merged["p_change_csv_his"] - merged["p_change_astock"]).abs()
            if {"p_change_csv_his", "p_change_astock"}.issubset(merged.columns)
            else pd.Series(dtype=float)
        )
        rows.append(
            {
                "ts_code": ts_code,
                "status": "ok",
                "overlap_days": int(len(merged)),
                "overlap_start": str(merged["trade_date"].min().date()),
                "overlap_end": str(merged["trade_date"].max().date()),
                "max_close_abs_diff": float(close_abs.max()),
                "max_close_rel_diff": float(close_rel.max()) if not close_rel.empty else np.nan,
                "mean_close_rel_diff": float(close_rel.mean()) if not close_rel.empty else np.nan,
                "max_p_change_abs_diff": float(pchg_abs.max()) if not pchg_abs.empty else np.nan,
            }
        )
    return pd.DataFrame(rows)


def finance_inventory(finance_dir: Path) -> pd.DataFrame:
    rows = []
    if not finance_dir.exists():
        return pd.DataFrame(columns=["ts_code", "path"])
    for path in finance_dir.iterdir():
        if not path.is_file():
            continue
        match = FINANCE_FILE_RE.match(path.name)
        if not match:
            continue
        code, market = match.groups()
        rows.append({"ts_code": f"{code}.{market.upper()}", "path": str(path)})
    return pd.DataFrame(rows).sort_values("ts_code") if rows else pd.DataFrame(columns=["ts_code", "path"])


def audit_finance(finance_files: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    required_groups = {
        "identity": ["ts_code", "end_date"],
        "asof": ["ann_date_x", "ann_date_y", "f_ann_date", "ann_date"],
        "quality": ["roe", "gross_margin", "netprofit_margin", "grossprofit_margin"],
        "stability": ["debt_to_assets", "current_ratio", "quick_ratio", "ocfps"],
        "improvement": ["tr_yoy", "or_yoy", "netprofit_yoy", "dt_netprofit_yoy", "roe_yoy", "q_roe"],
    }
    coverage_rows = []
    file_rows = []
    for _, item in finance_files.iterrows():
        path = item["path"]
        try:
            df = pd.read_csv(path, nrows=200)
        except Exception as exc:
            file_rows.append({"ts_code": item["ts_code"], "status": f"read_error:{exc}", "rows": 0})
            continue
        cols = set(df.columns)
        ann_cols = [col for col in required_groups["asof"] if col in cols]
        all_dates = pd.read_csv(path, usecols=lambda col: col in set(required_groups["asof"] + ["end_date"]))
        ann = pd.Series(pd.NaT, index=all_dates.index)
        for col in ann_cols:
            ann = ann.fillna(pd.to_datetime(all_dates[col].astype(str).str.split(".").str[0], format="%Y%m%d", errors="coerce"))
        end = (
            pd.to_datetime(all_dates["end_date"].astype(str).str.split(".").str[0], format="%Y%m%d", errors="coerce")
            if "end_date" in all_dates.columns
            else pd.Series(pd.NaT, index=all_dates.index)
        )
        row = {
            "ts_code": item["ts_code"],
            "status": "ok",
            "rows": int(len(all_dates)),
            "ann_date_cols": ",".join(ann_cols),
            "ann_min": str(ann.min().date()) if ann.notna().any() else "",
            "ann_max": str(ann.max().date()) if ann.notna().any() else "",
            "end_min": str(end.min().date()) if end.notna().any() else "",
            "end_max": str(end.max().date()) if end.notna().any() else "",
        }
        for group, group_cols in required_groups.items():
            row[f"{group}_cols_present"] = ",".join([col for col in group_cols if col in cols])
            row[f"{group}_cols_missing"] = ",".join([col for col in group_cols if col not in cols])
        file_rows.append(row)
    file_audit = pd.DataFrame(file_rows)
    if not file_audit.empty:
        for group in required_groups:
            present_counts = file_audit[f"{group}_cols_present"].astype(str).str.len().gt(0).sum()
            coverage_rows.append(
                {
                    "group": group,
                    "files_with_any_group_field": int(present_counts),
                    "files_total": int(len(file_audit)),
                    "coverage": round(float(present_counts / len(file_audit)), 4),
                }
            )
    return file_audit, pd.DataFrame(coverage_rows)


def audit_stock_basic(finance_dir: Path) -> Dict[str, object]:
    path = finance_dir / "stock_basic_all.csv"
    if not path.exists():
        return {"exists": False}
    df = pd.read_csv(path)
    name_col = "name" if "name" in df.columns else None
    st_count = int(df[name_col].astype(str).str.contains("ST", case=False, na=False).sum()) if name_col else 0
    return {
        "exists": True,
        "rows": int(len(df)),
        "columns": ",".join(df.columns.tolist()),
        "industry_non_null": int(df["industry"].notna().sum()) if "industry" in df.columns else 0,
        "st_name_count": st_count,
    }


def summarize_inventory(name: str, inventory: pd.DataFrame) -> Dict[str, object]:
    if inventory.empty:
        return {"source": name, "files": 0}
    return {
        "source": name,
        "files": int(len(inventory)),
        "codes": int(inventory["ts_code"].nunique()),
        "start_min": str(inventory["start"].min().date()),
        "start_max": str(inventory["start"].max().date()),
        "end_min": str(inventory["end"].min().date()),
        "end_max": str(inventory["end"].max().date()),
        "sh_codes": int((inventory["market"] == "SH").sum()),
        "sz_codes": int((inventory["market"] == "SZ").sum()),
        "bj_codes": int((inventory["market"] == "BJ").sum()),
    }


def write_report(
    out_dir: Path,
    summary: Dict[str, object],
    overlap: pd.DataFrame,
    finance_coverage: pd.DataFrame,
    stock_basic: Dict[str, object],
) -> None:
    def bullets(items: Dict[str, object]) -> List[str]:
        return [f"- {key}: {value}" for key, value in items.items()]

    overlap_ok = overlap[overlap.get("status", "") == "ok"] if not overlap.empty else pd.DataFrame()
    mismatch_count = (
        int((overlap_ok["max_close_rel_diff"].fillna(0) > 0.0001).sum())
        if not overlap_ok.empty and "max_close_rel_diff" in overlap_ok.columns
        else 0
    )
    lines = [
        "# Value Momentum Data Audit",
        "",
        "## Summary",
        "",
        *bullets(summary),
        "",
        "## Price Splice Check",
        "",
        f"- common codes checked: {len(overlap)}",
        f"- readable overlap rows: {len(overlap_ok)}",
        f"- codes with close relative diff > 0.01%: {mismatch_count}",
        "",
        "Use `price_overlap_audit.csv` for per-code details. If many codes differ, the first backtest should normalize or choose one source instead of blindly concatenating.",
        "",
        "## Finance Field Coverage",
        "",
    ]
    if finance_coverage.empty:
        lines.append("No finance coverage data.")
    else:
        lines.append("```")
        lines.append(finance_coverage.to_string(index=False))
        lines.append("```")
    lines.extend(
        [
            "",
            "## Stock Basic",
            "",
            *bullets(stock_basic),
            "",
            "## First-Pass Recommendation",
            "",
            "- Use finance `ann_date` fields as the factor effective date.",
            "- Do not use PE/PB/PS/PCF in the first pass; they are not present in the audited price schema.",
            "- Treat `volume` as the first liquidity proxy because turnover amount is not present in the price files.",
            "- Before backtest, decide how to handle price-source mismatches found in the overlap audit.",
            "",
        ]
    )
    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def run_audit(config: AuditConfig) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = config.output_dir / f"value_momentum_data_audit_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_his_inventory = price_file_inventory(config.csv_his_dir)
    astock_inventory = price_file_inventory(config.astock_dir)
    finance_files = finance_inventory(config.finance_dir)

    csv_his_inventory.to_csv(out_dir / "csv_his_inventory.csv", index=False, encoding="utf-8-sig")
    astock_inventory.to_csv(out_dir / "astock_inventory.csv", index=False, encoding="utf-8-sig")
    finance_files.to_csv(out_dir / "finance_inventory.csv", index=False, encoding="utf-8-sig")

    csv_his_latest = latest_file_by_code(csv_his_inventory)
    astock_latest = latest_file_by_code(astock_inventory)
    overlap = audit_overlap(csv_his_latest, astock_latest, config.max_overlap_codes)
    overlap.to_csv(out_dir / "price_overlap_audit.csv", index=False, encoding="utf-8-sig")

    finance_file_audit, finance_coverage = audit_finance(finance_files)
    finance_file_audit.to_csv(out_dir / "finance_file_audit.csv", index=False, encoding="utf-8-sig")
    finance_coverage.to_csv(out_dir / "finance_coverage.csv", index=False, encoding="utf-8-sig")

    stock_basic = audit_stock_basic(config.finance_dir)
    pd.Series(stock_basic).to_csv(out_dir / "stock_basic_audit.csv", encoding="utf-8-sig")

    sample_his = next(iter(csv_his_latest.values()), None)
    sample_astock = next(iter(astock_latest.values()), None)
    his_cols, his_rows, his_min, his_max = schema_sample(sample_his)
    astock_cols, astock_rows, astock_min, astock_max = schema_sample(sample_astock)
    common_codes = sorted(set(csv_his_latest) & set(astock_latest))
    summary = {
        "csv_his_dir": str(config.csv_his_dir),
        "astock_dir": str(config.astock_dir),
        "finance_dir": str(config.finance_dir),
        "csv_his_codes": len(csv_his_latest),
        "astock_codes": len(astock_latest),
        "common_price_codes": len(common_codes),
        "finance_codes": int(finance_files["ts_code"].nunique()) if not finance_files.empty else 0,
        "price_finance_common_codes": len(set(astock_latest) & set(finance_files["ts_code"].tolist())),
        "csv_his_sample_columns": ",".join(his_cols),
        "csv_his_sample_rows": his_rows,
        "csv_his_sample_date_range": f"{his_min} to {his_max}",
        "astock_sample_columns": ",".join(astock_cols),
        "astock_sample_rows": astock_rows,
        "astock_sample_date_range": f"{astock_min} to {astock_max}",
    }
    pd.Series(summary).to_csv(out_dir / "summary.csv", encoding="utf-8-sig")
    pd.DataFrame(
        [
            summarize_inventory("csv_his", csv_his_inventory),
            summarize_inventory("astock", astock_inventory),
        ]
    ).to_csv(out_dir / "source_inventory_summary.csv", index=False, encoding="utf-8-sig")
    write_report(out_dir, summary, overlap, finance_coverage, stock_basic)
    return out_dir


def parse_args() -> AuditConfig:
    parser = argparse.ArgumentParser(description="Audit local data for value-momentum A-share research.")
    parser.add_argument("--csv-his-dir", default="/Users/water/abu/csv_his")
    parser.add_argument("--astock-dir", default="/Users/water/abu/data/csv/astock")
    parser.add_argument("--finance-dir", default="/Users/water/abu/tushare/finance")
    parser.add_argument("--output-dir", default="cy_quant/output")
    parser.add_argument("--max-overlap-codes", type=int, default=None)
    args = parser.parse_args()
    return AuditConfig(
        csv_his_dir=Path(args.csv_his_dir),
        astock_dir=Path(args.astock_dir),
        finance_dir=Path(args.finance_dir),
        output_dir=Path(args.output_dir),
        max_overlap_codes=args.max_overlap_codes,
    )


def main() -> None:
    out_dir = run_audit(parse_args())
    print(f"输出目录: {out_dir}")
    print(f"报告: {out_dir / 'README.md'}")


if __name__ == "__main__":
    main()
