"""
60 日均线上穿 120 日均线（金叉）筛选
仿 Analyze120MA：扫描 ~/abu/data/csv/ 下本地 K 线，筛出最近一次出现 ma60 上穿 ma120 且当前仍保持 ma60>ma120 的股票，并保存 CSV。

判定（最近一根发生上穿的 K 线）：
- 当日 ma60 > ma120
- 前一日 ma60 <= ma120（或前一日 ma60 为 NaN 视为未在上方）
最新交易日须仍满足 ma60 > ma120。
"""

import pandas as pd
import numpy as np
import os
import glob
from datetime import datetime
import warnings

warnings.filterwarnings('ignore')


class Analyze60Cross120MA:
    """60 日上穿 120 日均线筛选器"""

    def __init__(self, prefixes=None, min_price=None, min_days_since_cross=5, input_csv=None):
        self.csv_dir = os.path.expanduser('~/abu/data/csv')
        self.results = []
        if prefixes is None:
            prefixes = ['sh', 'sz']
        self.prefixes = prefixes if isinstance(prefixes, list) else [prefixes]
        self.min_price = min_price
        self.min_days_since_cross = min_days_since_cross
        self.input_csv = input_csv
        self.input_df = None

    def load_input_csv(self):
        if self.input_csv is None or not os.path.exists(self.input_csv):
            return None
        try:
            try:
                df = pd.read_csv(self.input_csv, encoding='utf-8-sig')
            except Exception:
                try:
                    df = pd.read_csv(self.input_csv, encoding='gbk')
                except Exception:
                    df = pd.read_csv(self.input_csv, encoding='utf-8')
            if df.empty:
                return None
            print(f"成功加载输入CSV: {self.input_csv}，共 {len(df)} 条")
            return df
        except Exception as e:
            print(f"加载输入CSV失败: {e}")
            return None

    def get_stock_files(self):
        if self.input_csv:
            self.input_df = self.load_input_csv()
            if self.input_df is None or self.input_df.empty:
                print("警告：输入CSV无效，将分析全部匹配文件")
                self.input_df = None

        if self.input_df is not None and 'ts_code' in self.input_df.columns:
            valid_files = []
            for ts_code in self.input_df['ts_code'].unique().tolist():
                if '.' in str(ts_code):
                    code, market = str(ts_code).split('.')
                    if market == 'SH':
                        file_prefix = f"sh{code}"
                    elif market == 'SZ':
                        file_prefix = f"sz{code}"
                    else:
                        file_prefix = f"{code}_{market.lower()}"
                else:
                    file_prefix = str(ts_code)
                for pattern in [
                    os.path.join(self.csv_dir, f'{file_prefix}_*.csv'),
                    os.path.join(self.csv_dir, f'{file_prefix}_*'),
                ]:
                    for f in glob.glob(pattern):
                        name_without_ext = os.path.basename(f).replace('.csv', '')
                        parts = name_without_ext.split('_')
                        if len(parts) >= 3 and name_without_ext.startswith(file_prefix):
                            if f not in valid_files:
                                valid_files.append(f)
            print(f"从输入CSV匹配到 {len(valid_files)} 个数据文件")
            return valid_files

        all_files = []
        for prefix in self.prefixes:
            for pattern in [
                os.path.join(self.csv_dir, f'{prefix}*.csv'),
                os.path.join(self.csv_dir, f'{prefix}*'),
            ]:
                for f in glob.glob(pattern):
                    if f not in all_files:
                        all_files.append(f)
        valid_files = []
        for f in all_files:
            name_without_ext = os.path.basename(f).replace('.csv', '')
            parts = name_without_ext.split('_')
            if len(parts) >= 3 and any(name_without_ext.startswith(p) for p in self.prefixes):
                valid_files.append(f)
        print(f"找到 {len(valid_files)} 个股票数据文件")
        return valid_files

    def parse_filename(self, filepath):
        filename = os.path.basename(filepath)
        if filename.endswith('.csv'):
            filename = filename[:-4]
        parts = filename.split('_')
        if len(parts) < 3:
            return None
        code_part = parts[0]
        start_date = parts[1]
        end_date = parts[2]
        prefix_to_exchange = {'sh': 'SH', 'sz': 'SZ', 'hk': 'HK', 'us': 'US'}
        matched_prefix = None
        for prefix in self.prefixes:
            if code_part.startswith(prefix):
                matched_prefix = prefix
                break
        if matched_prefix and matched_prefix in prefix_to_exchange:
            exchange = prefix_to_exchange[matched_prefix]
            ts_code = f"{code_part[len(matched_prefix):]}.{exchange}"
            return ts_code, start_date, end_date
        return None

    def calculate_ma(self, df):
        df = df.copy().sort_values('trade_date')
        df['ma60'] = df['close'].rolling(window=60, min_periods=60).mean()
        df['ma120'] = df['close'].rolling(window=120, min_periods=120).mean()
        return df

    def find_last_cross(self, df):
        """
        最近一次 ma60 从下方向上穿越 ma120。
        返回 (cross_idx, cross_date, price_at_cross, last_close, days_since) 或 None
        """
        if df is None or df.empty or len(df) < 120:
            return None
        df = df.sort_values('trade_date').reset_index(drop=True)
        if 'ma60' not in df.columns or 'ma120' not in df.columns:
            return None
        above = df['ma60'] > df['ma120']
        if not above.iloc[-1]:
            return None
        prev_above = above.shift(1)
        prev_above = prev_above.fillna(False)
        cross = above & (~prev_above)
        cross_idx_list = df.index[cross.fillna(False)].tolist()
        if not cross_idx_list:
            return None
        cross_idx = cross_idx_list[-1]
        days_since = len(df) - 1 - cross_idx + 1
        if days_since < self.min_days_since_cross:
            return None
        cross_date = str(df.iloc[cross_idx]['trade_date'])
        price_cross = float(df.iloc[cross_idx]['close'])
        last_close = float(df.iloc[-1]['close'])
        last_date = str(df.iloc[-1]['trade_date'])
        return cross_idx, cross_date, price_cross, last_close, last_date, days_since

    @staticmethod
    def _series_to_int_ymd(series):
        s = series.astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        s = s.str.replace(r'[^\d]', '', regex=True).str[:8]
        num = pd.to_numeric(s, errors='coerce')
        return num.astype('Int64')

    def _normalize_export_dtypes(self, df):
        if df is None or df.empty:
            return df
        out = df.copy()
        for c in ('start_date', 'end_date', 'cross_date', 'last_trade_date'):
            if c in out.columns:
                out[c] = self._series_to_int_ymd(out[c])
        for c in ('start_price', 'current_price', 'growth_rate', 'ma60_last', 'ma120_last'):
            if c in out.columns:
                out[c] = pd.to_numeric(out[c], errors='coerce')
        if 'days_since_cross' in out.columns:
            out['days_since_cross'] = pd.to_numeric(out['days_since_cross'], errors='coerce').astype('Int64')
        return out

    def analyze_stock(self, filepath):
        try:
            parsed = self.parse_filename(filepath)
            if parsed is None:
                return None
            ts_code, start_date, end_date = parsed
            stock_code = ts_code.split('.')[0] if '.' in ts_code else ts_code

            try:
                df = pd.read_csv(filepath, encoding='utf-8-sig')
            except Exception:
                try:
                    df = pd.read_csv(filepath, encoding='gbk')
                except Exception:
                    df = pd.read_csv(filepath, encoding='utf-8')
            if df.empty:
                return None
            if 'date' in df.columns:
                df = df.rename(columns={'date': 'trade_date'})
            if 'trade_date' not in df.columns or 'close' not in df.columns:
                return None

            df_ma = self.calculate_ma(df)
            cross_info = self.find_last_cross(df_ma)
            if cross_info is None:
                return None
            _, cross_date, price_cross, last_close, last_date, days_since = cross_info

            if last_close < 5 or last_close > 10000:
                return None
            if self.min_price is not None and price_cross < self.min_price:
                return None

            growth_rate = (last_close - price_cross) / price_cross * 100 if price_cross > 0 else 0.0
            last_row = df_ma.iloc[-1]

            return {
                'ts_code': stock_code,
                'start_date': start_date,
                'end_date': end_date,
                'cross_date': cross_date,
                'last_trade_date': last_date,
                'start_price': round(price_cross, 4),
                'current_price': round(last_close, 4),
                'growth_rate': round(growth_rate, 2),
                'days_since_cross': int(days_since),
                'ma60_last': round(float(last_row['ma60']), 4),
                'ma120_last': round(float(last_row['ma120']), 4),
            }
        except Exception as e:
            print(f"分析文件 {filepath} 出错: {e}")
            return None

    def analyze_all(self):
        print("=" * 60)
        print("60日均线上穿120日均线 筛选")
        print("=" * 60)
        files = self.get_stock_files()
        if not files:
            print("未找到数据文件")
            return pd.DataFrame()

        results = []
        for i, fp in enumerate(files):
            r = self.analyze_stock(fp)
            if r:
                results.append(r)
            if (i + 1) % 100 == 0:
                print(f"已处理 {i + 1}/{len(files)} ...")

        if not results:
            print("未找到满足条件的股票")
            if self.input_df is not None:
                return self.input_df.copy()
            return pd.DataFrame()

        out = pd.DataFrame(results)
        out = self._normalize_export_dtypes(out)
        if 'cross_date' in out.columns:
            out = out.sort_values('cross_date', ascending=False, na_position='last')
        print(f"\n共筛选出 {len(out)} 只股票")
        print("=" * 60)
        return out

    def save_results(self, result_df, filename=None):
        if result_df.empty:
            print("无数据可保存")
            return
        result_df = self._normalize_export_dtypes(result_df)
        if filename is None:
            today = datetime.now().strftime('%Y%m%d')
            prefix = self.prefixes[0] if self.prefixes else 'all'
            filename = f'{prefix}_60ma_cross_120ma_{today}.csv'
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"\n结果已保存: {filename}")
        print(result_df.head(20).to_string(index=False))


def main(prefixes=None, min_price=1.0, min_days_since_cross=5, input_csv=None):
    analyzer = Analyze60Cross120MA(
        prefixes=prefixes,
        min_price=min_price,
        min_days_since_cross=min_days_since_cross,
        input_csv=input_csv,
    )
    result_df = analyzer.analyze_all()
    if not result_df.empty:
        analyzer.save_results(result_df)
    return result_df


if __name__ == '__main__':
    import argparse
    import time

    parser = argparse.ArgumentParser(description='60日均线上穿120日均线筛选')
    parser.add_argument('--prefix', nargs='*', default=['sh', 'sz'], help='文件前缀，如 sh sz')
    parser.add_argument('--input-csv', default=None, help='仅分析列表中的 ts_code')
    parser.add_argument('--min-price', type=float, default=1.0, help='金叉日收盘价下限过滤')
    parser.add_argument('--min-days', type=int, default=5, help='金叉距今日最少交易日数')
    args = parser.parse_args()

    t0 = time.time()
    main(
        prefixes=args.prefix,
        min_price=args.min_price,
        min_days_since_cross=args.min_days,
        input_csv=args.input_csv,
    )
    print(f"\n耗时 {time.time() - t0:.2f} 秒")
