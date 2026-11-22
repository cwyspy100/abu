"""下载可转债强赎相关数据（cb_call）到本地。"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import tushare as ts

DEFAULT_OUTPUT_DIR = "/Users/water/abu/data/cb"
DEFAULT_FIELDS = "ts_code,ann_date,call_type,is_call,call_date,notice_date"


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_token(token: Optional[str] = None) -> str:
    if token:
        return token.strip()
    path = os.path.join(_project_root(), "todolist", "config.json")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    tok = (cfg.get("token") or cfg.get("tushare_token") or "").strip()
    if not tok:
        raise ValueError("token 未配置")
    return tok


class Limiter:
    def __init__(self, cpm: int = 40) -> None:
        self.step = 60.0 / max(cpm, 1)
        self.last = 0.0

    def wait(self) -> None:
        now = time.time()
        if self.last > 0 and now - self.last < self.step:
            time.sleep(self.step - (now - self.last))
        self.last = time.time()


def run(
    token: Optional[str] = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    fields: str = DEFAULT_FIELDS,
    calls_per_minute: int = 40,
) -> str:
    tok = _load_token(token)
    ts.set_token(tok)
    pro = ts.pro_api()

    today = datetime.now()
    if end_date is None:
        end_date = today.strftime("%Y%m%d")
    if start_date is None:
        start_date = (today - timedelta(days=365 * 3)).strftime("%Y%m%d")

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"cb_call_{start_date}_{end_date}.csv")

    limiter = Limiter(cpm=calls_per_minute)

    # 按公告日期区间直接拉
    limiter.wait()
    df = pro.cb_call(start_date=start_date, end_date=end_date, fields=fields)
    if df is None:
        df = pd.DataFrame()

    if not df.empty:
        if "ann_date" in df.columns:
            df = df.sort_values(["ann_date", "ts_code"]).reset_index(drop=True)
        df = df.drop_duplicates()

    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"cb_call 已保存 {len(df)} 条 -> {out_path}")
    return out_path


def main() -> None:
    p = argparse.ArgumentParser(description="下载可转债强赎相关数据（cb_call）")
    p.add_argument("--token", default=None)
    p.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--start-date", default=None, help="YYYYMMDD")
    p.add_argument("--end-date", default=None, help="YYYYMMDD")
    p.add_argument("--fields", default=DEFAULT_FIELDS)
    p.add_argument("--calls-per-minute", type=int, default=40)
    a = p.parse_args()

    run(
        token=a.token,
        output_dir=a.output_dir,
        start_date=a.start_date,
        end_date=a.end_date,
        fields=a.fields,
        calls_per_minute=a.calls_per_minute,
    )


if __name__ == "__main__":
    main()
