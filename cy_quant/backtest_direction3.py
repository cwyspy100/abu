"""
方向三回测：蓄力形态
验证假设：突破前的蓄力形态越充分（振幅越小、波动率收缩越明显），爆发力越强
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
    breakthrough_date: str           # YYYYMMDD
    breakthrough_price: float        # 突破日收盘价
    consolidation_amplitude: float   # (max(high) - min(low)) / avg_price * 100%
    volatility_shrink_ratio: float   # pre-breakout volatility / early consolidation volatility
    final_gain: float                # 观察期最终涨幅
    success: bool                   # final_gain >= threshold


class Direction3Analyzer:
    """方向三回测分析器：蓄力形态"""

    MA_PERIOD = 120
    CONSOLIDATION_THRESHOLDS = [5, 10, 15, 20]
    CONSOLIDATION_LABELS = ['A (<5%)', 'B (5%~10%)', 'C (10%~15%)', 'D (15%~20%)', 'E (>20%)']

    def __init__(
        self,
        observe_days: int = 5,
        consolidation_days: int = 20,
        success_threshold: float = 20.0,
        vol_avg_days: int = 20,
        ma_period: int = 120,
    ):
        self.observe_days = observe_days
        self.consolidation_days = consolidation_days
        self.success_threshold = success_threshold
        self.vol_avg_days = vol_avg_days
        self.ma_period = ma_period

    def calculate_consolidation_amplitude(self, df: pd.DataFrame, start_idx: int, end_idx: int) -> float:
        """
        计算蓄力振幅
        amplitude = (max(high) - min(low)) / avg_price * 100%
        """
        if start_idx >= end_idx:
            return 0.0

        period_df = df.iloc[start_idx:end_idx + 1]
        max_high = period_df['high'].max()
        min_low = period_df['low'].min()
        avg_price = period_df['close'].mean()

        if avg_price <= 0:
            return 0.0

        amplitude = (max_high - min_low) / avg_price * 100
        return amplitude

    def calculate_volatility_shrink_ratio(self, df: pd.DataFrame, consolidation_start: int, consolidation_end: int) -> float:
        """
        计算波动率收缩比
        volatility_shrink_ratio = late_volatility / early_volatility
        late_volatility: 蓄力后半段的波动率
        early_volatility: 蓄力前半段的波动率
        """
        if consolidation_start >= consolidation_end:
            return 1.0

        period_df = df.iloc[consolidation_start:consolidation_end + 1]
        mid_idx = consolidation_start + (consolidation_end - consolidation_start) // 2

        # 前半段波动率
        early_df = df.iloc[consolidation_start:mid_idx + 1]
        early_vol = early_df['close'].std() / early_df['close'].mean() if len(early_df) > 1 else 0.0

        # 后半段波动率
        late_df = df.iloc[mid_idx + 1:consolidation_end + 1]
        late_vol = late_df['close'].std() / late_df['close'].mean() if len(late_df) > 1 else 0.0

        if early_vol <= 0:
            return 1.0

        return late_vol / early_vol

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

        # 确保有high/low列
        if 'high' not in df.columns or 'low' not in df.columns:
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

        # 确保有足够的蓄力分析数据
        if breakthrough_idx < self.consolidation_days:
            return None

        bt_date = str(df.iloc[breakthrough_idx]['trade_date'])
        bt_price = df.iloc[breakthrough_idx]['close']

        # 蓄力分析区间：突破前的N个交易日
        consolidation_end = breakthrough_idx - 1
        consolidation_start = max(0, consolidation_end - self.consolidation_days + 1)

        # 计算蓄力振幅
        consolidation_amplitude = self.calculate_consolidation_amplitude(df, consolidation_start, consolidation_end)

        # 计算波动率收缩比
        volatility_shrink_ratio = self.calculate_volatility_shrink_ratio(df, consolidation_start, consolidation_end)

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
            consolidation_amplitude=round(consolidation_amplitude, 2),
            volatility_shrink_ratio=round(volatility_shrink_ratio, 4),
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
                        'consolidation_amplitude': result.consolidation_amplitude,
                        'volatility_shrink_ratio': result.volatility_shrink_ratio,
                        'final_gain': result.final_gain,
                        'success': result.success,
                    })

        df = pd.DataFrame(results)
        return df

    def classify_consolidation(self, amplitude: float) -> str:
        """
        将蓄力振幅分类到对应分组
        分组：
          A: <5%
          B: 5%~10%
          C: 10%~15%
          D: 15%~20%
          E: >20%
        """
        for i, threshold in enumerate(self.CONSOLIDATION_THRESHOLDS):
            if amplitude < threshold:
                return self.CONSOLIDATION_LABELS[i]
        return self.CONSOLIDATION_LABELS[-1]

    def group_by_consolidation(self, result_df: pd.DataFrame) -> pd.DataFrame:
        """
        按蓄力振幅分组统计
        """
        if result_df.empty:
            return pd.DataFrame()

        result_df = result_df.copy()
        result_df['group'] = result_df['consolidation_amplitude'].apply(self.classify_consolidation)

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
        grouped = grouped.reindex(self.CONSOLIDATION_LABELS)
        grouped = grouped.dropna(how='all')

        return grouped

    def save_results(self, result_df: pd.DataFrame, filename: str = None):
        """保存结果到CSV"""
        if result_df.empty:
            return
        if filename is None:
            from datetime import datetime
            today = datetime.now().strftime('%Y%m%d')
            filename = os.path.join('cy_quant', 'output', f'direction3_results_{today}.csv')
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"结果已保存至: {filename}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='方向三回测：蓄力形态')
    parser.add_argument('--observe-days', type=int, default=5)
    parser.add_argument('--consolidation-days', type=int, default=20)
    parser.add_argument('--success-threshold', type=float, default=20.0)
    parser.add_argument('--stock-dir', type=str, default=None)
    parser.add_argument('--prefixes', type=str, default='sh,sz')
    args = parser.parse_args()

    prefixes = args.prefixes.split(',') if args.prefixes else ['sh', 'sz']

    analyzer = Direction3Analyzer(
        observe_days=args.observe_days,
        consolidation_days=args.consolidation_days,
        success_threshold=args.success_threshold,
    )

    print(f"开始回测（观察期={args.observe_days}天，蓄力分析期={args.consolidation_days}天，成功阈值={args.success_threshold}%%）...")
    result_df = analyzer.analyze_all(stock_dir=args.stock_dir, prefixes=prefixes)

    if result_df.empty:
        print("未找到有效数据")
        return

    print(f"\n共分析 {len(result_df)} 只股票突破120日均线")

    # 分组统计
    grouped = analyzer.group_by_consolidation(result_df)
    print("\n分组统计结果（按蓄力振幅）：")
    print(grouped.to_string())

    # 保存
    analyzer.save_results(result_df)


if __name__ == '__main__':
    main()
