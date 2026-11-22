"""可转债卖出规则研究：止损 + 130/150 分段止盈。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime

import pandas as pd

from cy_quant.cb.cb_diversification_walkforward_compare import run_mode
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_real_call_filter_backtest import apply_real_call_filter, build_real_call_intervals


def _summarize(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "periods": 0,
            "ann_return": float("nan"),
            "total_return": float("nan"),
            "max_drawdown": float("nan"),
            "win_rate": float("nan"),
        }
    eq = (1.0 + df["ret"]).cumprod()
    total = float(eq.iloc[-1] - 1.0)
    ann = float((1.0 + total) ** ((252.0 / 20.0) / len(df)) - 1.0)
    mdd = float((eq / eq.cummax() - 1.0).min())
    wr = float((df["ret"] > 0).mean())
    return {
        "periods": len(df),
        "ann_return": ann,
        "total_return": total,
        "max_drawdown": mdd,
        "win_rate": wr,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="可转债卖出规则研究")
    p.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20210527_20260527.csv")
    p.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    p.add_argument("--cb-call", default="/Users/water/abu/data/cb/cb_call_20210527_20260527.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    p.add_argument("--top-n", type=int, default=25)
    p.add_argument("--min-amount-wan", type=float, default=2000)
    p.add_argument("--cost-bps", type=float, default=40)
    p.add_argument("--hold-days", type=int, default=20)
    p.add_argument("--take-half-price", type=float, default=130.0)
    p.add_argument("--take-full-price", type=float, default=150.0)
    args = p.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_exit_rule_research_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    panel = build_combo_factors(build_panel(args.cb_daily, args.cb_basic))
    panel["score"] = panel["combo_dl_trend"]
    panel = apply_real_call_filter(panel, build_real_call_intervals(args.cb_call))

    stop_loss_grid = [None, 0.05, 0.08, 0.10, 0.12]
    rows = []
    for stop_loss_pct in stop_loss_grid:
        perf = run_mode(
            panel=panel,
            mode="balanced_premium",
            top_n=args.top_n,
            min_amount_wan=args.min_amount_wan,
            cost_bps=args.cost_bps,
            hold_days=args.hold_days,
            stop_loss_pct=stop_loss_pct,
            take_half_price=args.take_half_price,
            take_full_price=args.take_full_price,
        )
        stats = _summarize(perf)
        stats["strategy"] = "balanced_premium"
        stats["top_n"] = args.top_n
        stats["min_amount_wan"] = args.min_amount_wan
        stats["cost_bps"] = args.cost_bps
        stats["hold_days"] = args.hold_days
        stats["stop_loss_pct"] = stop_loss_pct if stop_loss_pct is not None else "none"
        stats["take_half_price"] = args.take_half_price
        stats["take_full_price"] = args.take_full_price
        rows.append(stats)

        label = "none" if stop_loss_pct is None else f"{int(stop_loss_pct * 100):02d}pct"
        perf.to_csv(os.path.join(out_dir, f"period_returns_stop_{label}.csv"), index=False, encoding="utf-8-sig")

    summary = pd.DataFrame(rows)
    summary = summary[
        [
            "strategy",
            "top_n",
            "min_amount_wan",
            "cost_bps",
            "hold_days",
            "stop_loss_pct",
            "take_half_price",
            "take_full_price",
            "periods",
            "ann_return",
            "total_return",
            "max_drawdown",
            "win_rate",
        ]
    ]
    summary.to_csv(os.path.join(out_dir, "exit_rule_summary.csv"), index=False, encoding="utf-8-sig")

    with open(os.path.join(out_dir, "research_note.txt"), "w", encoding="utf-8") as f:
        f.write("strategy=balanced_premium\n")
        f.write("score=combo_dl_trend\n")
        f.write("call_filter=real_call_filter\n")
        f.write("take_half_price=130\n")
        f.write("take_full_price=150\n")
        f.write("stop_loss_grid=none,0.05,0.08,0.10,0.12\n")

    print(f"卖出规则研究完成 -> {out_dir}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
