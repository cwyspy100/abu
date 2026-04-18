"""
全市场上市股票列表拉取工具（Tushare stock_basic）

使用方式与 QualityMomentumPickStock.py 一致：从 todolist/config.json 读取 token。

接口：查询当前所有正常上市交易的股票列表
  pro.stock_basic(
      exchange='',
      list_status='L',
      fields='ts_code,symbol,name,area,industry,list_date',
  )

限速：默认每分钟最多 40 次 API 调用（请求间隔 >= 60/40 秒），分页拉取时在每次请求前等待。

保存：合并后的 DataFrame 写入项目 todolist 目录下 CSV（UTF-8-BOM，便于 Excel 打开）。
"""

import argparse
import json
import os
import time
from datetime import datetime
from typing import List, Optional

import pandas as pd
import tushare as ts


DEFAULT_FIELDS = "ts_code,symbol,name,area,industry,list_date"
DEFAULT_PAGE_SIZE = 5000
DEFAULT_CALLS_PER_MINUTE = 40


def _project_root() -> str:
    """项目根目录（cy_quant 的上一级，即 abu-master）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class MinuteRateLimiter:
    """简单令牌桶：两次调用之间至少间隔 60/calls_per_minute 秒。"""

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
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    tok = (cfg.get("token") or "").strip()
    if not tok:
        raise ValueError("未提供 token，且 todolist/config.json 中无有效 token")
    return tok


def fetch_all_stock_basic(
    pro,
    exchange: str = "",
    list_status: str = "L",
    fields: str = DEFAULT_FIELDS,
    page_size: int = DEFAULT_PAGE_SIZE,
    calls_per_minute: int = DEFAULT_CALLS_PER_MINUTE,
) -> pd.DataFrame:
    """
    分页拉取 stock_basic，合并为一张表。
    每次请求前按每分钟 calls_per_minute 次限速。
    """
    limiter = MinuteRateLimiter(calls_per_minute=calls_per_minute)
    chunks: List[pd.DataFrame] = []
    offset = 0

    while True:
        limiter.wait()
        df = pro.stock_basic(
            exchange=exchange,
            list_status=list_status,
            fields=fields,
            offset=offset,
            limit=page_size,
        )
        if df is None or df.empty:
            break
        chunks.append(df)
        n = len(df)
        if n < page_size:
            break
        offset += page_size

    if not chunks:
        return pd.DataFrame()

    out = pd.concat(chunks, ignore_index=True)
    # 去重（分页边界若重复）
    if "ts_code" in out.columns:
        out = out.drop_duplicates(subset=["ts_code"], keep="first")
    return out


def default_output_path(base_dir: Optional[str] = None) -> str:
    if base_dir is None:
        base_dir = os.path.join(_project_root(), "todolist")
    os.makedirs(base_dir, exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    return os.path.join(base_dir, f"stock_basic_list_{day}.csv")


def run(
    token: Optional[str] = None,
    output_path: Optional[str] = None,
    exchange: str = "",
    list_status: str = "L",
    fields: str = DEFAULT_FIELDS,
    calls_per_minute: int = DEFAULT_CALLS_PER_MINUTE,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> pd.DataFrame:
    tok = _load_token(token)
    ts.set_token(tok)
    pro = ts.pro_api()

    print(
        f"拉取 stock_basic（exchange={exchange!r}, list_status={list_status!r}），"
        f"限速 {calls_per_minute} 次/分钟..."
    )
    df = fetch_all_stock_basic(
        pro,
        exchange=exchange,
        list_status=list_status,
        fields=fields,
        page_size=page_size,
        calls_per_minute=calls_per_minute,
    )

    if df.empty:
        print("未获取到任何数据。")
        return df

    out = output_path or default_output_path()
    out_dir = os.path.dirname(os.path.abspath(out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"已保存 {len(df)} 条记录 -> {out}")
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Tushare 全市场上市股票列表拉取并保存")
    parser.add_argument("--token", default=None, help="Tushare token（默认读 todolist/config.json）")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="输出 CSV 路径（默认 项目 todolist/stock_basic_list_YYYYMMDD.csv）",
    )
    parser.add_argument("--exchange", default="", help="交易所，空为全部")
    parser.add_argument("--list-status", default="L", dest="list_status", help="上市状态，L=上市")
    parser.add_argument(
        "--fields",
        default=DEFAULT_FIELDS,
        help="stock_basic fields 字段列表",
    )
    parser.add_argument(
        "--calls-per-minute",
        type=int,
        default=DEFAULT_CALLS_PER_MINUTE,
        help="每分钟最多 API 次数（默认 40）",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help="单次分页条数（默认 5000）",
    )
    args = parser.parse_args()

    run(
        token=args.token,
        output_path=args.output,
        exchange=args.exchange,
        list_status=args.list_status,
        fields=args.fields,
        calls_per_minute=args.calls_per_minute,
        page_size=args.page_size,
    )


if __name__ == "__main__":
    main()
