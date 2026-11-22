"""
分析周线 120 均线突破
扫描 ~/abu/data/csv/ 下 K 线文件，利用日 K 中的 date_week（周几：0=周一…4=周五）
聚合为周 K，再筛选站上 120 周均线的标的。

周线聚合规则：
  - 用 date_week 识别周边界（周几数值回落视为新的一周）
  - 每周取最后一个交易日收盘作为周收盘（通常为周五；节假日则取当周最后交易日）

命令行（默认 A 股 sh+sz；传入 us / hk 则只扫对应前缀）::

  python cy_quant/Analyze120WMA.py              # A 股 sh、sz
  python cy_quant/Analyze120WMA.py cn           # 同上
  python cy_quant/Analyze120WMA.py us           # 美股
  python cy_quant/Analyze120WMA.py hk           # 港股
  python cy_quant/Analyze120WMA.py hk --min-price 0.5
"""

import glob
import os
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


class Analyze120WMA:
    """周线 120 均线分析器：日 K 聚合为周 K 后，逻辑与 Analyze120MA 日线版对齐。"""

    MA_WINDOW = 120
    MIN_WEEKLY_BARS = 120

    def __init__(
        self,
        prefixes=None,
        min_price=None,
        growth_weights=None,
        input_csv=None,
        nh_lookback=8,
        min_weeks=4,
    ):
        """
        :param prefixes: 文件前缀列表，默认 ['sh', 'sz']
        :param min_price: 突破周起始价下限，None 表示不过滤
        :param growth_weights: 突破后 4/8/12/20 周涨幅权重，默认 [0.2, 0.3, 0.3, 0.2]
        :param input_csv: 仅分析该 CSV 中 ts_code 列的标的
        :param nh_lookback: 周线创新高统计窗口（周数），默认 8
        :param min_weeks: 突破后至少持续周数，默认 4
        """
        self.csv_dir = os.path.expanduser("~/abu/data/csv")
        self.results = []
        if prefixes is None:
            prefixes = ["sh", "sz"]
        self.prefixes = prefixes if isinstance(prefixes, list) else [prefixes]
        self.min_price = min_price
        if growth_weights is None:
            growth_weights = [0.2, 0.3, 0.3, 0.2]
        self.growth_weights = growth_weights
        self.input_csv = input_csv
        self.input_df = None
        self.nh_lookback = int(nh_lookback) if nh_lookback is not None else 8
        self.min_weeks = int(min_weeks) if min_weeks is not None else 4

    # ------------------------------------------------------------------ #
    # 文件扫描（与 Analyze120MA 保持一致）
    # ------------------------------------------------------------------ #
    def load_input_csv(self):
        if self.input_csv is None or not os.path.exists(self.input_csv):
            return None
        try:
            for enc in ("utf-8-sig", "gbk", "utf-8"):
                try:
                    df = pd.read_csv(self.input_csv, encoding=enc)
                    break
                except Exception:
                    df = None
            if df is None or df.empty:
                return None
            print(f"成功加载输入CSV文件: {self.input_csv}，共 {len(df)} 条记录")
            return df
        except Exception as e:
            print(f"加载输入CSV文件失败: {e}")
            return None

    def get_stock_files(self):
        if self.input_csv:
            self.input_df = self.load_input_csv()
            if self.input_df is None or self.input_df.empty:
                print("警告：输入CSV文件为空或加载失败，将分析所有股票")
                self.input_df = None

        if self.input_df is not None and "ts_code" in self.input_df.columns:
            stock_codes = self.input_df["ts_code"].unique().tolist()
            valid_files = []
            for ts_code in stock_codes:
                if "." in ts_code:
                    code, market = ts_code.split(".")
                    if market == "SH":
                        file_prefix = f"sh{code}"
                    elif market == "SZ":
                        file_prefix = f"sz{code}"
                    else:
                        file_prefix = f"{code}_{market.lower()}"
                else:
                    file_prefix = ts_code
                for pattern in (
                    os.path.join(self.csv_dir, f"{file_prefix}_*.csv"),
                    os.path.join(self.csv_dir, f"{file_prefix}_*"),
                ):
                    for f in glob.glob(pattern):
                        name_without_ext = os.path.basename(f).replace(".csv", "")
                        parts = name_without_ext.split("_")
                        if len(parts) >= 3 and name_without_ext.startswith(file_prefix):
                            if f not in valid_files:
                                valid_files.append(f)
            print(f"从输入CSV中找到 {len(valid_files)} 个股票数据文件")
            return valid_files

        all_files = []
        patterns = []
        for prefix in self.prefixes:
            patterns.append(os.path.join(self.csv_dir, f"{prefix}*.csv"))
            patterns.append(os.path.join(self.csv_dir, f"{prefix}*"))
        for pattern in patterns:
            for f in glob.glob(pattern):
                if f not in all_files:
                    all_files.append(f)

        valid_files = []
        for f in all_files:
            name_without_ext = os.path.basename(f).replace(".csv", "")
            parts = name_without_ext.split("_")
            if len(parts) >= 3 and any(
                name_without_ext.startswith(prefix) for prefix in self.prefixes
            ):
                valid_files.append(f)
        print(f"找到 {len(valid_files)} 个股票数据文件")
        return valid_files

    def parse_filename(self, filepath):
        filename = os.path.basename(filepath)
        if filename.endswith(".csv"):
            filename = filename[:-4]
        parts = filename.split("_")
        if len(parts) < 3:
            return None
        code_part = parts[0]
        prefix_to_exchange = {"sh": "SH", "sz": "SZ", "hk": "HK", "us": "US"}
        if len(code_part) < 2:
            return None
        head2 = code_part[:2].lower()
        if head2 not in prefix_to_exchange:
            return None
        exchange = prefix_to_exchange[head2]
        symbol = code_part[2:]
        if not symbol:
            return None
        ts_code = f"{symbol}.{exchange}"
        return ts_code, parts[1], parts[2]

    # ------------------------------------------------------------------ #
    # 日 K -> 周 K（基于 date_week）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalize_daily_df(df):
        """
        规范化日 K：统一 trade_date / close / date_week。
        date_week：0=周一 … 4=周五（与 abupy K 线约定一致）。
        """
        if "date" in df.columns and "trade_date" not in df.columns:
            df = df.rename(columns={"date": "trade_date"})
        if "trade_date" not in df.columns or "close" not in df.columns:
            return None
        out = df.copy()
        out["trade_date"] = (
            out["trade_date"].astype(str).str.replace(r"[^\d]", "", regex=True).str[:8]
        )
        out = out[out["trade_date"].str.len() == 8]
        out["close"] = pd.to_numeric(out["close"], errors="coerce")
        for col in ("open", "high", "low", "volume"):
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")

        if "date_week" not in out.columns:
            # 兜底：无 date_week 时用日历推算（0=周一）
            dt = pd.to_datetime(out["trade_date"], format="%Y%m%d", errors="coerce")
            out["date_week"] = dt.dt.dayofweek
        else:
            out["date_week"] = pd.to_numeric(out["date_week"], errors="coerce")

        out = out.dropna(subset=["trade_date", "close", "date_week"])
        if out.empty:
            return None
        out["date_week"] = out["date_week"].astype(int)
        return out.sort_values("trade_date").reset_index(drop=True)

    @staticmethod
    def _assign_week_id_by_date_week(date_week_series):
        """
        用 date_week 识别周边界：当周几数值相对前一日回落（如 4→0）视为新的一周。
        返回与输入等长的 week_id（从 0 递增）。
        """
        week_ids = []
        week_id = 0
        prev = None
        for dw in date_week_series.tolist():
            if prev is not None and dw < prev:
                week_id += 1
            week_ids.append(week_id)
            prev = dw
        return week_ids

    def daily_to_weekly(self, df):
        """
        日 K 聚合为周 K：
        - 用 date_week 划分自然交易周
        - 每周取最后一个交易日作为周收盘（优先周五；节假日则取当周最后一根）
        - open=当周首日开盘，high/low=当周最高/最低
        """
        daily = self._normalize_daily_df(df)
        if daily is None or daily.empty:
            return None

        daily = daily.copy()
        daily["week_id"] = self._assign_week_id_by_date_week(daily["date_week"])

        rows = []
        for _, g in daily.groupby("week_id", sort=True):
            g = g.sort_values("trade_date")
            last = g.iloc[-1]
            row = {
                "trade_date": str(last["trade_date"]),
                "close": float(last["close"]),
                "date_week": int(last["date_week"]),
                "week_bars": int(len(g)),
            }
            if "open" in g.columns and pd.notna(g.iloc[0]["open"]):
                row["open"] = float(g.iloc[0]["open"])
            else:
                row["open"] = float(g.iloc[0]["close"])
            if "high" in g.columns:
                row["high"] = float(g["high"].max())
            else:
                row["high"] = float(g["close"].max())
            if "low" in g.columns:
                row["low"] = float(g["low"].min())
            else:
                row["low"] = float(g["close"].min())
            if "volume" in g.columns:
                row["volume"] = float(g["volume"].sum())
            rows.append(row)

        if not rows:
            return None
        weekly = pd.DataFrame(rows)
        return weekly.sort_values("trade_date").reset_index(drop=True)

    def calculate_120wma(self, df_weekly):
        """计算周线 120 均线，并附带 4/8/12/20 周均线。"""
        df = df_weekly.copy().sort_values("trade_date")
        w = self.MA_WINDOW
        df["ma120"] = df["close"].rolling(window=w, min_periods=w).mean()
        df["ma120"] = df["ma120"].fillna(df["close"])
        for n in (4, 8, 12, 20):
            df[f"ma{n}"] = df["close"].rolling(window=n, min_periods=n).mean()
        return df

    def find_last_breakthrough(self, df):
        """
        找出最后一次站上 120 周均线的区间。
        要求：最近一周收盘必须在 120 周均线上方。
        """
        if df is None or df.empty or "ma120" not in df.columns:
            return None
        df = df.sort_values("trade_date").reset_index(drop=True)
        if len(df) < self.MIN_WEEKLY_BARS:
            return None

        df["above_ma120"] = df["close"] > df["ma120"]
        if not df.iloc[-1]["above_ma120"]:
            return None

        start_idx = None
        for i in range(len(df) - 2, -1, -1):
            if not df.iloc[i]["above_ma120"]:
                start_idx = i + 1
                break
        if start_idx is None:
            start_idx = 0

        start_date = str(df.iloc[start_idx]["trade_date"])
        start_price = float(df.iloc[start_idx]["close"])
        current_price = float(df.iloc[-1]["close"])
        growth_rate = (
            (current_price - start_price) / start_price * 100 if start_price > 0 else 0
        )
        weeks = len(df) - 1 - start_idx + 1
        return start_date, start_price, current_price, growth_rate, weeks

    def calculate_growth_at_weeks(
        self, df, breakthrough_date, breakthrough_price, weeks_list=None
    ):
        if weeks_list is None:
            weeks_list = [4, 8, 12, 20]
        df_sorted = df.sort_values("trade_date").reset_index(drop=True)
        df_sorted["trade_date"] = df_sorted["trade_date"].astype(str)
        breakthrough_idx = None
        for idx, row in df_sorted.iterrows():
            if row["trade_date"] == breakthrough_date:
                breakthrough_idx = idx
                break
        if breakthrough_idx is None:
            return {}

        result = {}
        for weeks in weeks_list:
            target_idx = breakthrough_idx + weeks - 1
            key = f"growth_{weeks}w"
            if target_idx < len(df_sorted):
                target_price = float(df_sorted.iloc[target_idx]["close"])
                growth = (
                    (target_price - breakthrough_price) / breakthrough_price * 100
                    if breakthrough_price > 0
                    else 0
                )
                result[key] = round(growth, 2)
            else:
                result[key] = 0.0
        return result

    def calculate_up_down_stats(self, df, breakthrough_date):
        df_sorted = df.sort_values("trade_date").reset_index(drop=True)
        df_sorted["trade_date"] = df_sorted["trade_date"].astype(str)
        breakthrough_idx = None
        for idx, row in df_sorted.iterrows():
            if row["trade_date"] == breakthrough_date:
                breakthrough_idx = idx
                break
        if breakthrough_idx is None or breakthrough_idx >= len(df_sorted) - 1:
            return {
                "up_weeks": 0,
                "down_weeks": 0,
                "up_down_ratio": 0.0,
                "up_rate_sum": 0.0,
                "down_rate_sum": 0.0,
                "rate_sum": 0.0,
            }

        up_weeks = down_weeks = 0
        up_rate_sum = down_rate_sum = 0.0
        for i in range(breakthrough_idx + 1, len(df_sorted)):
            prev_close = float(df_sorted.iloc[i - 1]["close"])
            curr_close = float(df_sorted.iloc[i]["close"])
            if prev_close <= 0:
                continue
            daily_rate = (curr_close - prev_close) / prev_close * 100
            if daily_rate > 0:
                up_weeks += 1
                up_rate_sum += daily_rate
            elif daily_rate < 0:
                down_weeks += 1
                down_rate_sum += abs(daily_rate)

        total = up_weeks + down_weeks
        if total > 0:
            up_down_ratio = up_weeks / down_weeks if down_weeks > 0 else float("inf")
        else:
            up_down_ratio = 0.0

        return {
            "up_weeks": up_weeks,
            "down_weeks": down_weeks,
            "up_down_ratio": round(up_down_ratio, 2)
            if up_down_ratio != float("inf")
            else 9999.99,
            "up_rate_sum": round(up_rate_sum, 2),
            "down_rate_sum": round(down_rate_sum, 2),
            "rate_sum": round(up_rate_sum + down_rate_sum, 2),
        }

    def calculate_nh_break_events(self, df, breakthrough_date, lookback_n=None):
        n = int(lookback_n) if lookback_n is not None else self.nh_lookback
        if n < 1:
            return {"nh_break_events": 0, "nh_lookback_n": n}

        df_sorted = df.sort_values("trade_date").reset_index(drop=True)
        df_sorted["trade_date"] = df_sorted["trade_date"].astype(str)
        bt_key = self._trade_date_key(breakthrough_date)
        if "high" in df_sorted.columns:
            high_s = pd.to_numeric(df_sorted["high"], errors="coerce")
        else:
            high_s = pd.to_numeric(df_sorted["close"], errors="coerce")

        breakthrough_idx = None
        for idx, row in df_sorted.iterrows():
            if self._trade_date_key(row["trade_date"]) == bt_key:
                breakthrough_idx = idx
                break
        if breakthrough_idx is None:
            return {"nh_break_events": 0, "nh_lookback_n": n}

        high = high_s.values
        count = 0
        for i in range(max(breakthrough_idx, n), len(df_sorted)):
            window = high[i - n : i]
            if window.size < n:
                continue
            ref_max = np.nanmax(window)
            hi = high[i]
            if np.isnan(hi) or np.isnan(ref_max):
                continue
            if hi > ref_max:
                count += 1
        return {"nh_break_events": int(count), "nh_lookback_n": n}

    @staticmethod
    def _trade_date_key(val):
        s = str(val).strip()
        if "." in s and s.replace(".", "").isdigit():
            s = s.split(".", 1)[0]
        digits = "".join(c for c in s if c.isdigit())
        return digits[:8] if len(digits) >= 8 else digits

    def calculate_recent_weeks_growth(self, df, current_price, n_weeks=4):
        if df is None or len(df) < n_weeks:
            return None
        price_nw_ago = float(df.iloc[-n_weeks]["close"])
        if price_nw_ago <= 0:
            return None
        return round((current_price - price_nw_ago) / price_nw_ago * 100, 2)

    # ------------------------------------------------------------------ #
    # 单股分析
    # ------------------------------------------------------------------ #
    def _analyze_stock_core(self, filepath, debug=False):
        try:
            parse_result = self.parse_filename(filepath)
            if parse_result is None:
                reason = "文件名不符合约定格式，无法解析股票代码"
                if debug:
                    print(f"[DEBUG] 跳过 {filepath}: {reason}")
                return None, reason

            ts_code, start_date, end_date = parse_result
            stock_code = ts_code.split(".")[0] if "." in ts_code else ts_code
            if stock_code.startswith(("399", "000")):
                reason = f"代码 {stock_code} 以 399/000 开头，按非股票处理"
                if debug:
                    print(f"[DEBUG] {stock_code} 未入选: {reason}")
                return None, reason

            for enc in ("utf-8-sig", "gbk", "utf-8"):
                try:
                    df_daily = pd.read_csv(filepath, encoding=enc)
                    break
                except Exception:
                    df_daily = None
            if df_daily is None or df_daily.empty:
                reason = "CSV 文件为空或读取失败"
                if debug:
                    print(f"[DEBUG] {stock_code} 未入选: {reason}")
                return None, reason

            df_weekly = self.daily_to_weekly(df_daily)
            if df_weekly is None or len(df_weekly) < self.MIN_WEEKLY_BARS:
                reason = f"周线数据不足 {self.MIN_WEEKLY_BARS} 周"
                if debug:
                    print(f"[DEBUG] {stock_code} 未入选: {reason}")
                return None, reason

            df_with_ma = self.calculate_120wma(df_weekly)
            breakthrough_info = self.find_last_breakthrough(df_with_ma)
            if breakthrough_info is None:
                reason = "最近一周未站上 MA120 或有效周线不足"
                if debug:
                    print(f"[DEBUG] {stock_code} 未入选: {reason}")
                return None, reason

            (
                start_date_breakthrough,
                start_price,
                current_price,
                growth_rate,
                weeks_diff,
            ) = breakthrough_info

            if weeks_diff < self.min_weeks:
                reason = f"突破后持续周数不足 {self.min_weeks} 周（当前 {weeks_diff} 周）"
                if debug:
                    print(f"[DEBUG] {stock_code} 未入选: {reason}")
                return None, reason

            if current_price < 5 or current_price > 2000:
                reason = f"当前价不在范围 [5, 2000]（当前 {current_price:.2f}）"
                if debug:
                    print(f"[DEBUG] {stock_code} 未入选: {reason}")
                return None, reason

            if self.min_price is not None and start_price < self.min_price:
                reason = (
                    f"突破起始价低于最小阈值 min_price={self.min_price}"
                    f"（当前 {start_price:.2f}）"
                )
                if debug:
                    print(f"[DEBUG] {stock_code} 未入选: {reason}")
                return None, reason

            df_sorted = df_with_ma.sort_values("trade_date").reset_index(drop=True)
            df_sorted["trade_date"] = df_sorted["trade_date"].astype(str)

            current_year = datetime.now().year
            year_start_str = f"{current_year}0101"
            last_trade_date = str(df_sorted.iloc[-1]["trade_date"])
            last_trade_price = float(df_sorted.iloc[-1]["close"])
            year_start_price = None
            year_to_date_growth = None
            if last_trade_date >= year_start_str:
                year_rows = df_sorted[df_sorted["trade_date"] >= year_start_str]
                if not year_rows.empty:
                    year_start_price = float(year_rows.iloc[0]["close"])
                    if year_start_price > 0:
                        year_to_date_growth = (
                            (last_trade_price - year_start_price) / year_start_price * 100
                        )

            breakthrough_date_str = str(start_date_breakthrough)
            growth_at_weeks = self.calculate_growth_at_weeks(
                df_sorted, breakthrough_date_str, start_price
            )

            last_ma120 = float(df_sorted.iloc[-1]["ma120"])
            result = {
                "ts_code": stock_code,
                "start_date": start_date,
                "end_date": end_date,
                "breakthrough_date": start_date_breakthrough,
                "start_price": round(start_price, 2),
                "current_price": round(current_price, 2),
                "ma120": round(last_ma120, 4),
                "growth_rate": round(growth_rate, 2),
                "ret_from_break_pct": round(growth_rate, 2),
                "weeks": weeks_diff,
                "weekly_bars": len(df_sorted),
                "last_week_date": last_trade_date,
            }

            if year_start_price is not None:
                result["year_start_price"] = round(year_start_price, 2)
                result["year_to_date_growth"] = round(year_to_date_growth, 2)
            else:
                result["year_start_price"] = 0
                result["year_to_date_growth"] = 0

            result.update(growth_at_weeks)

            score = 0.0
            if len(self.growth_weights) >= 4:
                score = (
                    growth_at_weeks.get("growth_4w", 0.0) * self.growth_weights[0]
                    + growth_at_weeks.get("growth_8w", 0.0) * self.growth_weights[1]
                    + growth_at_weeks.get("growth_12w", 0.0) * self.growth_weights[2]
                    + growth_at_weeks.get("growth_20w", 0.0) * self.growth_weights[3]
                )
            result["score"] = round(score, 2)
            result.update(self.calculate_up_down_stats(df_sorted, breakthrough_date_str))
            result.update(
                self.calculate_nh_break_events(df_sorted, breakthrough_date_str)
            )
            recent_growth = self.calculate_recent_weeks_growth(
                df_sorted, current_price, n_weeks=4
            )
            result["recent_4w_growth"] = (
                recent_growth if recent_growth is not None else 0.0
            )

            if debug:
                print(
                    f"[DEBUG] {stock_code} 入选，周线突破日 {start_date_breakthrough}，"
                    f"累计涨幅 {growth_rate:.2f}%"
                )
            return result, None

        except Exception as e:
            reason = f"分析异常: {e}"
            if debug:
                print(f"[DEBUG] 分析文件 {filepath} 出错: {e}")
            return None, reason

    @staticmethod
    def _stock_input_to_file_prefix(raw: str):
        s = str(raw).strip()
        if not s:
            return None
        if len(s) >= 2 and s[:2].lower() in ("sh", "sz", "hk", "us"):
            return s[:2].lower() + s[2:]
        if "." in s:
            code, market = s.split(".", 1)
            market = market.upper()
            prefix_map = {"SH": "sh", "SZ": "sz", "HK": "hk", "US": "us"}
            if market not in prefix_map:
                return None
            return f"{prefix_map[market]}{code}"
        if s.startswith("6"):
            return f"sh{s}"
        if s.startswith(("0", "3")):
            return f"sz{s}"
        return None

    def debug_analyze_by_stock_code(self, stock_code, exclude_list=None):
        if not stock_code:
            print("[DEBUG] stock_code 不能为空")
            return None
        raw = str(stock_code).strip()
        file_prefix = self._stock_input_to_file_prefix(raw)
        if file_prefix is None:
            print(f"[DEBUG] 无法解析股票代码: {raw}")
            return None
        patterns = [
            os.path.join(self.csv_dir, f"{file_prefix}_*.csv"),
            os.path.join(self.csv_dir, f"{file_prefix}_*"),
        ]
        matched_files = []
        for pattern in patterns:
            for f in glob.glob(pattern):
                if f not in matched_files:
                    matched_files.append(f)
        if not matched_files:
            print(f"[DEBUG] 未找到股票文件: {file_prefix}_*")
            return None
        matched_files = sorted(
            matched_files, key=lambda x: os.path.basename(x), reverse=True
        )
        filepath = matched_files[0]
        print(f"[DEBUG] 开始调试 {stock_code}，使用文件: {filepath}")
        result, reason = self._analyze_stock_core(filepath, debug=True)
        if result is None:
            print(f"[DEBUG] 结论: {stock_code} 未入选，原因: {reason}")
            return None
        print(f"[DEBUG] 结论: {stock_code} 已入选")
        return result

    def analyze_stock(self, filepath):
        result, _ = self._analyze_stock_core(filepath, debug=False)
        return result

    def analyze_all(self):
        print("=" * 60)
        if self.input_csv:
            print(f"开始分析周线120均线突破（从CSV: {self.input_csv}）")
        else:
            print("开始分析周线120均线突破（分析所有股票）")
        print("=" * 60)

        stock_files = self.get_stock_files()
        if not stock_files:
            print("未找到股票数据文件！")
            return pd.DataFrame()

        results = []
        for i, filepath in enumerate(stock_files):
            result = self.analyze_stock(filepath)
            if result:
                results.append(result)
            if (i + 1) % 100 == 0:
                print(f"已处理 {i + 1}/{len(stock_files)} 个文件...")

        if not results:
            print("未找到任何站上周线120均线的股票")
            if self.input_df is not None:
                return self.input_df.copy()
            return pd.DataFrame()

        ma_result_df = pd.DataFrame(results)
        ma_result_df = self._normalize_export_dtypes(ma_result_df)

        if self.input_df is not None:
            input_df_copy = self.input_df.copy()
            if "ts_code" in input_df_copy.columns:
                input_df_copy["ts_code"] = input_df_copy["ts_code"].apply(
                    lambda x: x.split(".")[0] if "." in str(x) else x
                )
            result_df = pd.merge(
                input_df_copy, ma_result_df, on="ts_code", how="left", suffixes=("", "_wma")
            )
            wma_columns = [
                "breakthrough_date",
                "start_price",
                "current_price",
                "ma120",
                "growth_rate",
                "ret_from_break_pct",
                "weeks",
                "weekly_bars",
                "last_week_date",
                "year_start_price",
                "year_to_date_growth",
                "growth_4w",
                "growth_8w",
                "growth_12w",
                "growth_20w",
                "score",
                "up_weeks",
                "down_weeks",
                "up_down_ratio",
                "up_rate_sum",
                "down_rate_sum",
                "rate_sum",
                "recent_4w_growth",
                "nh_break_events",
                "nh_lookback_n",
            ]
            for col in wma_columns:
                if f"{col}_wma" in result_df.columns:
                    result_df[col] = result_df[f"{col}_wma"]
                    result_df = result_df.drop(columns=[f"{col}_wma"])
                elif col not in result_df.columns:
                    result_df[col] = np.nan
            numeric_cols = [
                c
                for c in wma_columns
                if c
                not in ("breakthrough_date", "last_week_date", "nh_lookback_n")
            ]
            for col in numeric_cols:
                if col in result_df.columns:
                    result_df[col] = result_df[col].fillna(0)
            result_df = self._normalize_export_dtypes(result_df)
            print(
                f"\n分析完成！共 {len(ma_result_df)} 只站上周线120均线，"
                f"已追加到原始数据（共 {len(result_df)} 条）"
            )
        else:
            result_df = ma_result_df.copy()
            if "breakthrough_date" in result_df.columns:
                result_df = result_df.sort_values(
                    "breakthrough_date", ascending=False, na_position="last"
                )
            print(f"\n分析完成！共找到 {len(result_df)} 只站上周线120均线")

        print("=" * 60)
        return result_df

    @staticmethod
    def _series_to_int_ymd(series):
        s = series.astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
        s = s.str.replace(r"[^\d]", "", regex=True).str[:8]
        num = pd.to_numeric(s, errors="coerce")
        return num.astype("Int64")

    def _normalize_export_dtypes(self, df):
        if df is None or df.empty:
            return df
        out = df.copy()
        for c in ("start_date", "end_date", "breakthrough_date", "last_week_date"):
            if c in out.columns:
                out[c] = self._series_to_int_ymd(out[c])
        numeric_cols = [
            "start_price",
            "current_price",
            "ma120",
            "growth_rate",
            "ret_from_break_pct",
            "year_start_price",
            "year_to_date_growth",
            "growth_4w",
            "growth_8w",
            "growth_12w",
            "growth_20w",
            "score",
            "up_down_ratio",
            "up_rate_sum",
            "down_rate_sum",
            "rate_sum",
            "recent_4w_growth",
            "nh_break_events",
            "nh_lookback_n",
            "weekly_bars",
        ]
        for c in numeric_cols:
            if c in out.columns:
                out[c] = pd.to_numeric(out[c], errors="coerce")
        for c in ("weeks", "up_weeks", "down_weeks", "nh_break_events", "nh_lookback_n"):
            if c in out.columns:
                out[c] = pd.to_numeric(out[c], errors="coerce").astype("Int64")
        return out

    def save_results(self, result_df, filename=None):
        if result_df.empty:
            print("没有数据可保存")
            return
        result_df = self._normalize_export_dtypes(result_df)
        if filename is None:
            today = datetime.now().strftime("%Y%m%d")
            if self.input_csv:
                base_name = os.path.splitext(os.path.basename(self.input_csv))[0]
                filename = f"{base_name}_with_120wma_{today}.csv"
            else:
                prefix = self.prefixes[0] if self.prefixes else ""
                filename = (
                    f"{prefix}_120wma_breakthrough_{today}.csv"
                    if prefix
                    else f"120wma_breakthrough_{today}.csv"
                )
        result_df.to_csv(filename, index=False, encoding="utf-8-sig")
        print(f"\n结果已保存至: {filename}")
        print("\n前20条结果:")
        print(result_df.head(20).to_string(index=False))


def main(
    prefixes=None,
    min_price=1.0,
    growth_weights=None,
    input_csv=None,
    nh_lookback=8,
    min_weeks=4,
):
    if isinstance(prefixes, str):
        key = prefixes.strip().lower()
        if key == "cn":
            prefixes = ["sh", "sz"]
        elif key in ("us", "hk"):
            prefixes = [key]
        else:
            raise ValueError("prefixes 字符串仅支持 cn / us / hk")

    analyzer = Analyze120WMA(
        prefixes=prefixes,
        min_price=min_price,
        growth_weights=growth_weights,
        input_csv=input_csv,
        nh_lookback=nh_lookback,
        min_weeks=min_weeks,
    )
    result_df = analyzer.analyze_all()
    if not result_df.empty:
        analyzer.save_results(result_df)
    return result_df


if __name__ == "__main__":
    import argparse
    import time

    ap = argparse.ArgumentParser(description="周线 120 均线突破扫描（默认 A 股，可选 us / hk）")
    ap.add_argument(
        "market",
        nargs="?",
        default="us",
        choices=("cn", "us", "hk"),
        help="市场：cn=A 股 sh+sz，us=美股，hk=港股（默认 cn）",
    )
    ap.add_argument("--min-price", type=float, default=1.0, help="过滤突破起始价低于该值的标的")
    ap.add_argument(
        "--nh-lookback",
        type=int,
        default=8,
        dest="nh_lookback",
        help="周线新高统计窗口（周数）",
    )
    ap.add_argument(
        "--min-weeks",
        type=int,
        default=4,
        help="突破后至少持续周数，默认 4",
    )
    ap.add_argument(
        "--input-csv",
        default=None,
        dest="input_csv",
        help="仅分析该表 ts_code 列中的股票",
    )
    args = ap.parse_args()

    start = time.time()
    result = main(
        prefixes=args.market,
        min_price=args.min_price,
        input_csv=args.input_csv,
        nh_lookback=args.nh_lookback,
        min_weeks=args.min_weeks,
    )
    print("\n处理完成，耗时 %.2f 秒" % (time.time() - start,))
