"""
方向二回测：突破质量（爆发力）
验证假设：突破比例越大、成交量配合越好，后续上涨概率越高
"""

import pandas as pd
import numpy as np
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class BacktestResult:
    """回测结果容器"""
    ts_code: str
    breakthrough_date: str       # YYYYMMDD
    breakthrough_price: float
    ma120: float                # MA120 at breakthrough
    breakthrough_ratio: float   # (close - MA120) / MA120 * 100%
    volume_ratio: float         # volume / avg_volume
    final_gain: float           # observation period final gain
    success: bool               # final_gain >= threshold


class Direction2Analyzer:
    """方向二回测分析器：突破质量（爆发力）"""

    MA_PERIOD = 120
    BREAKTHROUGH_THRESHOLDS = [0, 1, 3, 5]
    BREAKTHROUGH_LABELS = ['E (<0%)', 'D (0%~1%)', 'C (1%~3%)', 'B (3%~5%)', 'A (>=5%)']

    def __init__(
        self,
        observe_days: int = 5,
        success_threshold: float = 20.0,  # 单位：%
        volume_avg_days: int = 20,
        ma_period: int = 120,
    ):
        self.observe_days = observe_days
        self.success_threshold = success_threshold
        self.volume_avg_days = volume_avg_days
        self.ma_period = ma_period

    def calculate_volume_ratio(self, df: pd.DataFrame, breakthrough_idx: int) -> float:
        """
        计算突破日的成交量比率
        volume on breakthrough day / avg volume of past N days
        """
        if breakthrough_idx < self.volume_avg_days:
            return 1.0

        start_idx = breakthrough_idx - self.volume_avg_days
        avg_volume = df.iloc[start_idx:breakthrough_idx]['volume'].mean()

        if avg_volume <= 0:
            return 1.0

        breakthrough_volume = df.iloc[breakthrough_idx]['volume']
        return breakthrough_volume / avg_volume

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

        # 确保有成交量列
        if 'volume' not in df.columns:
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

        bt_date = str(df.iloc[breakthrough_idx]['trade_date'])
        bt_price = df.iloc[breakthrough_idx]['close']
        ma120 = df.iloc[breakthrough_idx][f'ma{self.ma_period}']

        # 计算突破比例
        breakthrough_ratio = (bt_price - ma120) / ma120 * 100

        # 计算成交量比率
        volume_ratio = self.calculate_volume_ratio(df, breakthrough_idx)

        # 观察期数据
        end_idx = min(breakthrough_idx + self.observe_days, len(df) - 1)
        observe_df = df.iloc[breakthrough_idx: end_idx + 1].copy()

        if len(observe_df) < 2:
            return None

        # 最终涨幅（观察期最后一天）
        final_price = observe_df.iloc[-1]['close']
        final_gain = (final_price - bt_price) / bt_price * 100

        return BacktestResult(
            ts_code=os.path.basename(filepath).split('_')[0],
            breakthrough_date=bt_date,
            breakthrough_price=round(bt_price, 2),
            ma120=round(ma120, 2),
            breakthrough_ratio=round(breakthrough_ratio, 4),
            volume_ratio=round(volume_ratio, 4),
            final_gain=round(final_gain, 2),
            success=final_gain >= self.success_threshold,
        )

    def analyze_all(self, stock_dir: str = None, prefixes=None) -> pd.DataFrame:
        """
        遍历目录下所有股票文件进行回测
        :param stock_dir: 股票数据目录，默认 ~/abu/data/csv
        :param prefixes: 文件前缀列表，默认 ['sh', 'sz']
        """
        import glob

        if stock_dir is None:
            stock_dir = os.path.expanduser('~/abu/data/csv')
        if prefixes is None:
            prefixes = ['sh', 'sz']

        results = []
        for prefix in prefixes:
            pattern = os.path.join(stock_dir, f'{prefix}*')
            files = glob.glob(pattern)
            for f in files:
                result = self.analyze_file(f)
                if result:
                    results.append({
                        'ts_code': result.ts_code,
                        'breakthrough_date': result.breakthrough_date,
                        'breakthrough_price': result.breakthrough_price,
                        'ma120': result.ma120,
                        'breakthrough_ratio': result.breakthrough_ratio,
                        'volume_ratio': result.volume_ratio,
                        'final_gain': result.final_gain,
                        'success': result.success,
                    })

        df = pd.DataFrame(results)
        return df

    def classify_breakthrough(self, ratio: float) -> str:
        """
        将突破比例分类到对应分组
        分组：
          A: >=5%
          B: 3%~5%
          C: 1%~3%
          D: 0%~1%
          E: <0%
        """
        if ratio < self.BREAKTHROUGH_THRESHOLDS[0]:
            return self.BREAKTHROUGH_LABELS[0]  # E (<0%)
        for i, threshold in enumerate(self.BREAKTHROUGH_THRESHOLDS[1:], start=1):
            if ratio < threshold:
                return self.BREAKTHROUGH_LABELS[i]
        return self.BREAKTHROUGH_LABELS[-1]  # A (>=5%)

    def group_by_breakthrough(self, result_df: pd.DataFrame) -> pd.DataFrame:
        """
        按突破比例分组统计
        """
        if result_df.empty:
            return pd.DataFrame()

        result_df = result_df.copy()
        result_df['group'] = result_df['breakthrough_ratio'].apply(self.classify_breakthrough)

        grouped = result_df.groupby('group').agg({
            'ts_code': 'count',
            'final_gain': 'mean',
            'success': 'mean',
        }).rename(columns={
            'ts_code': 'count',
            'final_gain': 'avg_final_gain',
            'success': 'success_rate',
        }).round(4)

        # 按分组顺序排序
        grouped = grouped.reindex(self.BREAKTHROUGH_LABELS)
        grouped = grouped.dropna(how='all')

        return grouped

    def save_results(self, result_df: pd.DataFrame, filename: str = None):
        """保存结果到CSV"""
        if result_df.empty:
            return
        if filename is None:
            from datetime import datetime
            today = datetime.now().strftime('%Y%m%d')
            filename = os.path.join('cy_quant', 'output', f'direction2_results_{today}.csv')
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"结果已保存至: {filename}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='方向二回测：突破质量')
    parser.add_argument('--observe-days', type=int, default=5)
    parser.add_argument('--success-threshold', type=float, default=20.0)
    parser.add_argument('--volume-avg-days', type=int, default=20)
    parser.add_argument('--stock-dir', type=str, default=None)
    parser.add_argument('--prefixes', type=str, default='sh,sz')
    args = parser.parse_args()

    prefixes = args.prefixes.split(',') if args.prefixes else ['sh', 'sz']

    analyzer = Direction2Analyzer(
        observe_days=args.observe_days,
        success_threshold=args.success_threshold,
        volume_avg_days=args.volume_avg_days,
    )

    print(f"开始回测（观察期={args.observe_days}天，成功阈值={args.success_threshold}%%）...")
    result_df = analyzer.analyze_all(stock_dir=args.stock_dir, prefixes=prefixes)

    if result_df.empty:
        print("未找到有效数据")
        return

    print(f"\n共分析 {len(result_df)} 只股票突破120日均线")

    # 分组统计
    grouped = analyzer.group_by_breakthrough(result_df)
    print("\n分组统计结果（按突破比例）：")
    print(grouped.to_string())

    # 保存
    analyzer.save_results(result_df)


if __name__ == '__main__':
    main()