"""
方向四回测：相对强弱
验证假设：优先选择近期走势强于大盘的股票
"""

import pandas as pd
import numpy as np
import os
import glob
from dataclasses import dataclass
from typing import Optional


@dataclass
class BacktestResult:
    """回测结果容器"""
    ts_code: str
    breakthrough_date: str       # YYYYMMDD
    breakthrough_price: float   # 突破日收盘价
    stock_gain: float           # 个股观察期涨幅
    benchmark_gain: float       # 基准同期涨幅
    rs_diff: float              # 相对强弱差值 (stock_gain - benchmark_gain)
    final_gain: float           # 观察期最终涨幅
    success: bool               # final_gain >= threshold


class Direction4Analyzer:
    """方向四回测分析器：相对强弱"""

    MA_PERIOD = 120
    RS_DIFF_THRESHOLDS = [-5, 0, 5, 10]
    RS_DIFF_LABELS = ['E (<-5%)', 'D (-5%~0%)', 'C (0%~5%)', 'B (5%~10%)', 'A (>10%)']

    def __init__(
        self,
        observe_days: int = 5,
        rs_period: int = 20,
        success_threshold: float = 20.0,
        ma_period: int = 120,
        benchmark: str = 'hs300',
    ):
        self.observe_days = observe_days
        self.rs_period = rs_period
        self.success_threshold = success_threshold
        self.ma_period = ma_period
        self.benchmark = benchmark
        self.benchmark_df = None

    def _find_benchmark_file(self, stock_dir: str) -> Optional[str]:
        """
        查找基准指数文件
        :param stock_dir: 数据目录
        :return: 基准文件路径或None
        """
        # 优先在astock子目录查找
        astock_dir = os.path.join(stock_dir, 'astock')
        if not os.path.isdir(astock_dir):
            astock_dir = stock_dir

        if self.benchmark == 'hs300':
            # 查找hs300文件
            patterns = [
                os.path.join(stock_dir, 'hs300*.csv'),
                os.path.join(stock_dir, 'hs300_*'),
                os.path.join(astock_dir, 'hs300*.csv'),
                os.path.join(astock_dir, 'hs300_*'),
            ]
            for pattern in patterns:
                files = glob.glob(pattern)
                if files:
                    return files[0]

        # 默认使用SSE指数 (sh000001)
        sse_patterns = [
            os.path.join(astock_dir, 'sh000001*'),
            os.path.join(stock_dir, 'sseindex*.csv'),
            os.path.join(stock_dir, 'sseindex_*'),
        ]
        for pattern in sse_patterns:
            files = glob.glob(pattern)
            if files:
                return files[0]

        return None

    def _load_benchmark_data(self, stock_dir: str = None) -> Optional[pd.DataFrame]:
        """
        加载基准指数数据
        :param stock_dir: 数据目录
        """
        if stock_dir is None:
            stock_dir = os.path.expanduser('~/abu/data/csv')

        benchmark_file = self._find_benchmark_file(stock_dir)
        if not benchmark_file:
            print(f"警告: 未找到基准指数文件 ({self.benchmark})")
            return None

        try:
            df = pd.read_csv(benchmark_file, encoding='utf-8-sig')
        except Exception:
            try:
                df = pd.read_csv(benchmark_file, encoding='gbk')
            except Exception:
                print(f"警告: 无法读取基准指数文件 {benchmark_file}")
                return None

        if df.empty:
            return None

        # 重命名列
        if 'date' in df.columns:
            df = df.rename(columns={'date': 'trade_date'})
        if 'trade_date' not in df.columns or 'close' not in df.columns:
            return None

        # 排序
        df = df.sort_values('trade_date').reset_index(drop=True)
        df['trade_date'] = df['trade_date'].astype(str)

        self.benchmark_df = df
        return df

    def get_benchmark_gain(self, breakthrough_date: str, observe_days: int) -> float:
        """
        获取基准指数同期涨幅
        :param breakthrough_date: 突破日 (YYYYMMDD)
        :param observe_days: 观察期天数
        :return: 基准涨幅 (%)
        """
        if self.benchmark_df is None or self.benchmark_df.empty:
            return 0.0

        # 找到突破日在基准数据中的位置
        try:
            bt_idx = self.benchmark_df[self.benchmark_df['trade_date'] == breakthrough_date].index
            if len(bt_idx) == 0:
                # 尝试找最近的日期
                self.benchmark_df['trade_date_int'] = self.benchmark_df['trade_date'].astype(str).astype(int)
                target_int = int(breakthrough_date)
                closest_idx = (self.benchmark_df['trade_date_int'] - target_int).abs().idxmin()
                bt_idx = [closest_idx]

            bt_idx = bt_idx[0]
            bt_price = self.benchmark_df.iloc[bt_idx]['close']

            # 获取观察期最后一天
            end_idx = min(bt_idx + observe_days, len(self.benchmark_df) - 1)
            final_price = self.benchmark_df.iloc[end_idx]['close']

            if bt_price <= 0:
                return 0.0

            benchmark_gain = (final_price - bt_price) / bt_price * 100
            return round(benchmark_gain, 2)
        except Exception:
            return 0.0

    def calculate_rs_diff(self, df: pd.DataFrame, breakthrough_idx: int) -> float:
        """
        计算相对强弱差值
        RS_diff = stock_gain(period) - benchmark_gain(period)
        使用突破前rs_period天的涨幅与基准同期涨幅对比
        """
        if self.benchmark_df is None or self.benchmark_df.empty:
            return 0.0

        # 获取个股突破前rs_period天的涨幅
        start_idx = max(0, breakthrough_idx - self.rs_period)
        stock_start_price = df.iloc[start_idx]['close']
        stock_bt_price = df.iloc[breakthrough_idx]['close']

        if stock_start_price <= 0:
            return 0.0

        stock_gain = (stock_bt_price - stock_start_price) / stock_start_price * 100

        # 获取基准同期涨幅
        bt_date = str(df.iloc[breakthrough_idx]['trade_date'])
        benchmark_gain = self.get_benchmark_gain(bt_date, self.rs_period)

        rs_diff = stock_gain - benchmark_gain
        return round(rs_diff, 2)

    def analyze_file(self, filepath: str) -> Optional[BacktestResult]:
        """
        分析单个股票文件
        :param filepath: 股票CSV文件路径
        :return: BacktestResult 或 None
        """
        # 读取CSV
        try:
            df = pd.read_csv(filepath, encoding='utf-8-sig')
        except Exception:
            try:
                df = pd.read_csv(filepath, encoding='gbk')
            except Exception:
                return None

        if df.empty:
            return None

        # 重命名列
        if 'date' in df.columns:
            df = df.rename(columns={'date': 'trade_date'})
        if 'trade_date' not in df.columns or 'close' not in df.columns:
            return None

        # 排序
        df = df.sort_values('trade_date').reset_index(drop=True)
        df['trade_date'] = df['trade_date'].astype(str)

        # 计算MA
        df[f'ma{self.ma_period}'] = df['close'].rolling(window=self.ma_period, min_periods=self.ma_period).mean()
        df[f'ma{self.ma_period}'] = df[f'ma{self.ma_period}'].fillna(df['close'])

        # 找突破日（收盘价首次站上MA）
        df['above_ma'] = df['close'] > df[f'ma{self.ma_period}']
        breakthrough_idx = None
        for i in range(self.ma_period, len(df)):
            if df.iloc[i]['above_ma'] and not df.iloc[i-1]['above_ma']:
                breakthrough_idx = i
                break

        if breakthrough_idx is None:
            return None

        # 确保有足够的RS分析数据
        if breakthrough_idx < self.rs_period:
            return None

        bt_date = str(df.iloc[breakthrough_idx]['trade_date'])
        bt_price = df.iloc[breakthrough_idx]['close']

        # 计算相对强弱差值
        rs_diff = self.calculate_rs_diff(df, breakthrough_idx)

        # 观察期数据
        end_idx = min(breakthrough_idx + self.observe_days, len(df) - 1)
        observe_df = df.iloc[breakthrough_idx: end_idx + 1].copy()

        if len(observe_df) < 2:
            return None

        # 计算个股观察期涨幅
        final_price = observe_df.iloc[-1]['close']
        stock_gain = (final_price - bt_price) / bt_price * 100

        # 计算基准同期涨幅
        benchmark_gain = self.get_benchmark_gain(bt_date, self.observe_days)

        # 最终涨幅
        final_gain = stock_gain

        return BacktestResult(
            ts_code=os.path.basename(filepath).split('_')[0],
            breakthrough_date=bt_date,
            breakthrough_price=round(bt_price, 2),
            stock_gain=round(stock_gain, 2),
            benchmark_gain=round(benchmark_gain, 2),
            rs_diff=round(rs_diff, 2),
            final_gain=round(final_gain, 2),
            success=final_gain >= self.success_threshold,
        )

    def analyze_all(self, stock_dir: str = None, prefixes=None) -> pd.DataFrame:
        """
        遍历目录下所有股票文件进行回测
        :param stock_dir: 股票数据目录，默认 ~/abu/data/csv
        :param prefixes: 文件前缀列表，默认 ['sh', 'sz']
        """
        if stock_dir is None:
            stock_dir = os.path.expanduser('~/abu/data/csv')
        if prefixes is None:
            prefixes = ['sh', 'sz']

        # 先加载基准数据
        self._load_benchmark_data(stock_dir)

        results = []
        for prefix in prefixes:
            pattern = os.path.join(stock_dir, f'{prefix}*')
            files = glob.glob(pattern)
            for f in files:
                # 跳过目录和索引文件
                if os.path.isdir(f):
                    continue
                # 跳过指数文件
                basename = os.path.basename(f)
                if basename.startswith('sh000') or basename.startswith('sz000'):
                    continue
                result = self.analyze_file(f)
                if result:
                    results.append({
                        'ts_code': result.ts_code,
                        'breakthrough_date': result.breakthrough_date,
                        'breakthrough_price': result.breakthrough_price,
                        'stock_gain': result.stock_gain,
                        'benchmark_gain': result.benchmark_gain,
                        'rs_diff': result.rs_diff,
                        'final_gain': result.final_gain,
                        'success': result.success,
                    })

        df = pd.DataFrame(results)
        return df

    def classify_rs(self, rs_diff: float) -> str:
        """
        将相对强弱差值分类到对应分组
        分组：
          A: >10%
          B: 5%~10%
          C: 0%~5%
          D: -5%~0%
          E: <=-5%
        """
        thresholds = self.RS_DIFF_THRESHOLDS
        if rs_diff > thresholds[3]:  # > 10
            return self.RS_DIFF_LABELS[4]  # A (>10%)
        elif rs_diff > thresholds[2]:  # > 5
            return self.RS_DIFF_LABELS[3]  # B (5%~10%)
        elif rs_diff > thresholds[1]:  # > 0
            return self.RS_DIFF_LABELS[2]  # C (0%~5%)
        elif rs_diff > thresholds[0]:  # > -5
            return self.RS_DIFF_LABELS[1]  # D (-5%~0%)
        else:
            return self.RS_DIFF_LABELS[0]  # E (<=-5%)

    def group_by_rs(self, result_df: pd.DataFrame) -> pd.DataFrame:
        """
        按相对强弱差值分组统计
        """
        if result_df.empty:
            return pd.DataFrame()

        result_df = result_df.copy()
        result_df['group'] = result_df['rs_diff'].apply(self.classify_rs)

        grouped = result_df.groupby('group', sort=True).agg({
            'ts_code': 'count',
            'stock_gain': 'mean',
            'benchmark_gain': 'mean',
            'rs_diff': 'mean',
            'final_gain': 'mean',
            'success': 'mean',
        }).rename(columns={
            'ts_code': 'count',
            'stock_gain': 'avg_stock_gain',
            'benchmark_gain': 'avg_benchmark_gain',
            'rs_diff': 'avg_rs_diff',
            'final_gain': 'avg_final_gain',
            'success': 'success_rate',
        }).round(2)

        return grouped

    def save_results(self, result_df: pd.DataFrame, filename: str = None):
        """保存结果到CSV"""
        if result_df.empty:
            return
        if filename is None:
            from datetime import datetime
            today = datetime.now().strftime('%Y%m%d')
            filename = os.path.join('cy_quant', 'output', f'direction4_results_{today}.csv')
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"结果已保存至: {filename}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='方向四回测：相对强弱')
    parser.add_argument('--observe-days', type=int, default=5)
    parser.add_argument('--rs-period', type=int, default=20)
    parser.add_argument('--success-threshold', type=float, default=20.0)
    parser.add_argument('--benchmark', type=str, default='hs300', choices=['hs300', 'sse'])
    parser.add_argument('--stock-dir', type=str, default=None)
    parser.add_argument('--prefixes', type=str, default='sh,sz')
    args = parser.parse_args()

    prefixes = args.prefixes.split(',') if args.prefixes else ['sh', 'sz']

    analyzer = Direction4Analyzer(
        observe_days=args.observe_days,
        rs_period=args.rs_period,
        success_threshold=args.success_threshold,
        benchmark=args.benchmark,
    )

    print(f"开始回测（观察期={args.observe_days}天，RS周期={args.rs_period}天，成功阈值={args.success_threshold}%%，基准={args.benchmark}）...")
    result_df = analyzer.analyze_all(stock_dir=args.stock_dir, prefixes=prefixes)

    if result_df.empty:
        print("未找到有效数据")
        return

    print(f"\n共分析 {len(result_df)} 只股票突破120日均线")

    # 分组统计
    grouped = analyzer.group_by_rs(result_df)
    print("\n分组统计结果（按相对强弱差值）：")
    print(grouped.to_string())

    # 保存
    analyzer.save_results(result_df)


if __name__ == '__main__':
    main()
