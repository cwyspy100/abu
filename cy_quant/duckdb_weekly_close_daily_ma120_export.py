#!/usr/bin/env python3
"""Export weekly-close crosses of daily MA120 whose runs exceed 500%."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd


QUERY = """
with stock_bars as (
    select b.date, b.symbol, s.name as stock_name,
           b.qfq_high as high, b.qfq_low as low, b.qfq_close as close
    from tushare_qfq_bars b
    join security_master s on s.asset = b.asset and s.symbol = b.symbol
    where b.asset = 'a_share_qfq'
      and s.exchange in ('SSE', 'SZSE')
      and s.market in ('主板', '创业板', '科创板')
      and b.qfq_high > 0 and b.qfq_low > 0 and b.qfq_close > 0
      __AS_OF_FILTER__
), with_daily_ma as (
    select *, avg(close) over (
        partition by symbol order by date rows between 119 preceding and current row
    ) as ma120,
    count(close) over (
        partition by symbol order by date rows between 119 preceding and current row
    ) as ma120_days
    from stock_bars
), weekly_close as (
    select date, symbol, stock_name, close, ma120, ma120_days
    from with_daily_ma
    qualify row_number() over (
        partition by symbol, date_trunc('week', date) order by date desc
    ) = 1
), weekly_with_previous as (
    select *, lag(close) over (partition by symbol order by date) as prev_close,
           lag(ma120) over (partition by symbol order by date) as prev_ma120,
           lag(ma120_days) over (partition by symbol order by date) as prev_ma120_days
    from weekly_close
), first_cross as (
    select symbol, stock_name, date as cross_date
    from weekly_with_previous
    where ma120_days = 120 and prev_ma120_days = 120
      and close > ma120 and prev_close <= prev_ma120
    qualify row_number() over (partition by symbol order by date) = 1
), enriched as (
    select c.symbol, c.stock_name, c.cross_date,
           low_window.lowest_price, low_window.start_date, low_window.pre_cross_days,
           run_window.highest_price, run_window.end_date, run_window.run_end_date
    from first_cross c
    cross join lateral (
        select min(low) as lowest_price, arg_min(date, low) as start_date, count(*) as pre_cross_days
        from (
            select low, date from stock_bars p
            where p.symbol = c.symbol and p.date < c.cross_date
            order by p.date desc limit 120
        )
    ) low_window
    cross join lateral (
        select max(high) as highest_price,
               arg_min(date, struct_pack(negative_high := -high, occurrence_date := date)) as end_date,
               max(date) as run_end_date
        from stock_bars q
        where q.symbol = c.symbol and q.date >= c.cross_date
          and q.date <= coalesce(
              (select max(w.date) from weekly_with_previous w
               where w.symbol = c.symbol and w.date >= c.cross_date
                 and w.date < coalesce(
                     (select min(f.date) from weekly_with_previous f
                      where f.symbol = c.symbol and f.date > c.cross_date and f.close <= f.ma120),
                     date '9999-12-31'
                 )),
              c.cross_date
          )
    ) run_window
)
select symbol, stock_name, cross_date, lowest_price, start_date,
       highest_price, end_date,
       round((highest_price / lowest_price - 1) * 100, 2) as gain_pct,
       date_diff('day', start_date, end_date) as duration_days,
       round(date_diff('day', start_date, end_date) / 7.0, 2) as duration_weeks,
       run_end_date
from enriched
where pre_cross_days = 120 and lowest_price is not null and highest_price is not null
  and (highest_price / lowest_price - 1) * 100 > 500
order by gain_pct desc, symbol
"""


def scan_market_db(database_path: str, complete_through: str = None) -> pd.DataFrame:
    """Scan only data through a caller-declared last complete trading date."""
    query = QUERY.replace("__AS_OF_FILTER__", "and b.date <= ?" if complete_through else "")
    connection = duckdb.connect(database_path, read_only=True)
    try:
        return connection.execute(query, [complete_through] if complete_through else []).fetchdf()
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export weekly-close/daily-MA120 runs over 500%")
    parser.add_argument("--database", default="/Users/water/abu/data/market.duckdb")
    parser.add_argument("--output", default="cy_quant/output/duckdb_weekly_close_daily_ma120_over500pct.csv")
    parser.add_argument("--complete-through", help="last date known to belong to a complete trading week, e.g. 2026-08-07")
    args = parser.parse_args()
    result = scan_market_db(args.database, args.complete_through)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False, encoding="utf-8-sig")
    print(f"exported {len(result)} records to {output}")


if __name__ == "__main__":
    main()
