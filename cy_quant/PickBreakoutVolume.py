# -*- encoding:utf-8 -*-
"""
放量突破选股：收盘价 > 前 high_n 个交易日最高价，且当日成交量 > vol_mult × 前 vol_ma_n 日成交量均值。

参考 cy_quant/Analyze120MA.py 的本地 K 线文件扫描方式（~/abu/data/csv 下 sh*/sz*/hk*/us*）。

默认：high_n=20，vol_ma_n=5，vol_mult=1.5，均可参数化。
"""

from __future__ import print_function

import argparse
import os
from datetime import datetime

import numpy as np
import pandas as pd
import warnings

from cy_quant.Analyze120MA import Analyze120MA

warnings.filterwarnings("ignore")


class PickBreakoutVolume:
    """前 N 日最高价突破 + 放量 选股"""

    def __init__(
        self,
        prefixes=None,
        input_csv=None,
        high_n=20,
        vol_ma_n=5,
        vol_mult=1.5,
        csv_dir=None,
    ):
        """
        :param prefixes: 与 Analyze120MA 一致，如 ['sh','sz'] 或 ['us']
        :param input_csv: 可选，含 ts_code 列时只扫这些标的对应文件
        :param high_n: 回看最高价窗口（不含当日），默认 20
        :param vol_ma_n: 均量窗口（不含当日），默认 5
        :param vol_mult: 成交量倍数阈值，默认 1.5
        :param csv_dir: K 线目录，默认 ~/abu/data/csv
        """
        self.high_n = int(high_n)
        self.vol_ma_n = int(vol_ma_n)
        self.vol_mult = float(vol_mult)
        self._scanner = Analyze120MA(prefixes=prefixes, input_csv=input_csv)
        if csv_dir is not None:
            self._scanner.csv_dir = os.path.expanduser(csv_dir)

    def _min_bars(self):
        return max(self.high_n + 1, self.vol_ma_n + 1)

    @staticmethod
    def _ensure_columns(df):
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

    def analyze_stock(self, filepath, debug=False):
        """
        若最新一根 K 线满足条件则返回结果 dict，否则返回 None。
        """
        parse_result = self._scanner.parse_filename(filepath)
        if parse_result is None:
            if debug:
                print(f"[DEBUG] 跳过 {filepath}: 文件名无法解析")
            return None

        ts_code, _start, _end = parse_result
        stock_code = ts_code.split(".")[0] if "." in ts_code else ts_code
        if stock_code.startswith(("399", "000")):
            if debug:
                print(f"[DEBUG] {stock_code} 跳过指数/非个股")
            return None

        try:
            try:
                df = pd.read_csv(filepath, encoding="utf-8-sig")
            except Exception:
                try:
                    df = pd.read_csv(filepath, encoding="gbk")
                except Exception:
                    df = pd.read_csv(filepath, encoding="utf-8")
        except Exception as e:
            if debug:
                print(f"[DEBUG] {ts_code} 读文件失败: {e}")
            return None

        if df is None or df.empty:
            return None

        df = self._ensure_columns(df)
        need = {"trade_date", "close", "high", "volume"}
        if not need.issubset(set(df.columns)):
            if debug:
                print(f"[DEBUG] {ts_code} 缺少列: 需要 {need}, 实际 {list(df.columns)[:15]}...")
            return None

        df = df.sort_values("trade_date").reset_index(drop=True)
        nmin = self._min_bars()
        if len(df) < nmin:
            if debug:
                print(f"[DEBUG] {ts_code} 数据不足 {nmin} 根 K 线")
            return None

        # 前 high_n 日最高价（不含当日）
        hh_prev = df["high"].iloc[-(self.high_n + 1) : -1].max()
        close_last = float(df["close"].iloc[-1])
        if np.isnan(hh_prev) or hh_prev <= 0:
            return None
        cond_price = close_last > hh_prev

        # 前 vol_ma_n 日成交量均值（不含当日）
        vol_tail = df["volume"].iloc[-(self.vol_ma_n + 1) : -1]
        vol_ma = vol_tail.mean()
        vol_last = float(df["volume"].iloc[-1])
        if np.isnan(vol_ma) or vol_ma <= 0:
            return None
        cond_vol = vol_last > self.vol_mult * vol_ma

        if not (cond_price and cond_vol):
            return None

        last_date = df["trade_date"].iloc[-1]
        return {
            "ts_code": stock_code,
            "signal_date": last_date,
            "close": round(close_last, 4),
            "high_prev_n_max": round(float(hh_prev), 4),
            "high_n": self.high_n,
            "volume": int(vol_last) if vol_last == int(vol_last) else vol_last,
            "volume_ma_prev": round(float(vol_ma), 4),
            "vol_ma_n": self.vol_ma_n,
            "volume_ratio": round(vol_last / vol_ma, 4) if vol_ma else None,
            "vol_mult_threshold": self.vol_mult,
            "breakout_pct_vs_high": round((close_last / hh_prev - 1.0) * 100, 4),
        }

    def analyze_all(self):
        files = self._scanner.get_stock_files()
        if not files:
            print("未找到股票数据文件")
            return pd.DataFrame()

        rows = []
        for i, fp in enumerate(files):
            r = self.analyze_stock(fp)
            if r:
                rows.append(r)
            if (i + 1) % 200 == 0:
                print(f"已处理 {i + 1}/{len(files)} ...")

        if not rows:
            print("没有标的满足：收盘 > 前N日最高 且 成交量 > 倍数×均量")
            return pd.DataFrame()

        out = pd.DataFrame(rows)
        print(f"共命中 {len(out)} 只")
        return out

    def save_results(self, df, filename=None):
        if df is None or df.empty:
            print("无数据可保存")
            return
        if filename is None:
            today = datetime.now().strftime("%Y%m%d")
            pfx = self._scanner.prefixes[0] if self._scanner.prefixes else "pick"
            filename = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "output",
                f"breakout_vol_{pfx}_{today}.csv",
            )
        d = os.path.dirname(filename)
        if d:
            os.makedirs(d, exist_ok=True)
        df.to_csv(filename, index=False, encoding="utf-8-sig")
        print(f"已保存: {filename}")


def main():
    parser = argparse.ArgumentParser(description="放量突破选股（收盘>前N日最高 + 放量）")
    parser.add_argument(
        "--prefixes",
        nargs="+",
        default=["sh", "sz"],
        help="K 线文件前缀，如 sh sz 或 us hk",
    )
    parser.add_argument("--input-csv", default=None, help="含 ts_code 的 CSV，仅分析其中股票")
    parser.add_argument("--csv-dir", default=None, help="K 线目录，默认 ~/abu/data/csv")
    parser.add_argument("--high-n", type=int, default=20, help="前 N 日最高价窗口（不含当日），默认 20")
    parser.add_argument("--vol-ma-n", type=int, default=5, help="均量窗口天数（不含当日），默认 5")
    parser.add_argument("--vol-mult", type=float, default=1.5, help="成交量倍数阈值，默认 1.5")
    parser.add_argument("-o", "--output", default=None, help="输出 CSV 路径")
    args = parser.parse_args()

    picker = PickBreakoutVolume(
        prefixes=args.prefixes,
        input_csv=args.input_csv,
        high_n=args.high_n,
        vol_ma_n=args.vol_ma_n,
        vol_mult=args.vol_mult,
        csv_dir=args.csv_dir,
    )
    df = picker.analyze_all()
    if not df.empty:
        picker.save_results(df, args.output)
    return df


if __name__ == "__main__":
    main()
