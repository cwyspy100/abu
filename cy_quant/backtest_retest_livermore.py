"""
利弗莫尔标准回测：验证突破120日均线后，是否守住P0和MA120
核心规则：
1. 不能跌破 P0（突破日收盘价）
2. 不能跌破 120日均线
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
    breakthrough_date: str       # 突破日 YYYYMMDD
    breakthrough_price: float    # 突破日收盘价 P0
    ma120_at_breakthrough: float # 突破日MA120值

    # 守住指标
    held_p0: bool                # 是否始终守住P0
    held_ma120: bool             # 是否始终守住MA120
    held_p0_days: int            # 守住P0的天数
    held_ma120_days: int         # 守住MA120的天数

    # 跌破指标
    min_deviation_p0: float     # 观察期内相对P0的最大跌幅 (%)
    min_deviation_ma: float     # 观察期内相对MA120的最大跌幅 (%)
    broke_p0_count: int          # 跌破P0的次数
    broke_ma_count: int         # 跌破MA120的次数

    # 涨幅指标
    max_gain: float             # 观察期内最大涨幅 (%)
    final_gain: float           # 观察期最后一天累计涨幅 (%)

    # 成功标准
    success: bool               # 是否达标（final_gain >= 成功阈值）


class LivermoreAnalyzer:
    """利弗莫尔标准回测分析器"""

    MA_PERIOD = 120

    # 分组标签
    GROUPS = ['A', 'B', 'C', 'D', 'E']
    GROUP_LABELS = ['A(守P0+守MA)', 'B(守P0+破MA)', 'C(<3%)', 'D(3~10%)', 'E(>10%)']

    def __init__(
        self,
        observe_days: int = 10,
        success_threshold: float = 20.0,
        ma_period: int = 120,
    ):
        self.observe_days = observe_days
        self.success_threshold = success_threshold
        self.ma_period = ma_period

    def analyze_file(self, filepath: str) -> Optional[BacktestResult]:
        """
        分析单个股票文件
        """
        try:
            df = pd.read_csv(filepath, encoding='utf-8-sig')
        except Exception:
            try:
                df = pd.read_csv(filepath, encoding='gbk')
            except Exception:
                return None

        if df.empty:
            return None

        if 'date' in df.columns:
            df = df.rename(columns={'date': 'trade_date'})
        if 'trade_date' not in df.columns or 'close' not in df.columns:
            return None

        df = df.sort_values('trade_date').reset_index(drop=True)
        df['trade_date'] = df['trade_date'].astype(str)

        # 计算MA120
        df[f'ma{self.ma_period}'] = df['close'].rolling(
            window=self.ma_period, min_periods=self.ma_period
        ).mean()
        df[f'ma{self.ma_period}'] = df[f'ma{self.ma_period}'].fillna(df['close'])

        # 找突破日（收盘价首次站上MA）
        df['above_ma'] = df['close'] > df[f'ma{self.ma_period}']
        breakthrough_idx = None
        for i in range(self.ma_period, len(df)):
            if df.iloc[i]['above_ma'] and not df.iloc[i - 1]['above_ma']:
                breakthrough_idx = i
                break

        if breakthrough_idx is None:
            return None

        bt_date = str(df.iloc[breakthrough_idx]['trade_date'])
        bt_price = df.iloc[breakthrough_idx]['close']
        bt_ma = df.iloc[breakthrough_idx][f'ma{self.ma_period}']

        # 观察期数据
        end_idx = min(breakthrough_idx + self.observe_days, len(df) - 1)
        if end_idx <= breakthrough_idx:
            return None

        observe_df = df.iloc[breakthrough_idx:end_idx + 1].copy()

        # ========== 守住指标计算 ==========

        # 守住P0的天数（收盘价 >= P0）
        held_p0_days = 0
        held_ma120_days = 0
        broke_p0_count = 0
        broke_ma_count = 0
        min_deviation_p0 = 0.0  # 相对于P0的最大跌幅
        min_deviation_ma = 0.0  # 相对于MA120的最大跌幅

        for i in range(1, len(observe_df)):
            close = observe_df.iloc[i]['close']
            ma = observe_df.iloc[i][f'ma{self.ma_period}']

            # 检查是否跌破P0
            if close >= bt_price:
                held_p0_days += 1
            else:
                broke_p0_count += 1
                deviation = (bt_price - close) / bt_price * 100
                if deviation > abs(min_deviation_p0):
                    min_deviation_p0 = -deviation  # 负数表示跌破

            # 检查是否跌破MA120
            if close >= ma:
                held_ma120_days += 1
            else:
                broke_ma_count += 1
                deviation = (ma - close) / ma * 100
                if deviation > abs(min_deviation_ma):
                    min_deviation_ma = -deviation

        # 是否始终守住
        held_p0 = (broke_p0_count == 0)
        held_ma120 = (broke_ma_count == 0)

        # 计算最大涨幅
        max_gain = 0.0
        for i in range(1, len(observe_df)):
            price = observe_df.iloc[i]['close']
            gain = (price - bt_price) / bt_price * 100
            if gain > max_gain:
                max_gain = gain

        # 最终涨幅
        final_price = observe_df.iloc[-1]['close']
        final_gain = (final_price - bt_price) / bt_price * 100

        return BacktestResult(
            ts_code=os.path.basename(filepath).split('_')[0],
            breakthrough_date=bt_date,
            breakthrough_price=round(bt_price, 2),
            ma120_at_breakthrough=round(bt_ma, 2),
            held_p0=held_p0,
            held_ma120=held_ma120,
            held_p0_days=held_p0_days,
            held_ma120_days=held_ma120_days,
            min_deviation_p0=round(min_deviation_p0, 2),
            min_deviation_ma=round(min_deviation_ma, 2),
            broke_p0_count=broke_p0_count,
            broke_ma_count=broke_ma_count,
            max_gain=round(max_gain, 2),
            final_gain=round(final_gain, 2),
            success=final_gain >= self.success_threshold,
        )

    def analyze_all(self, stock_dir: str = None, prefixes=None) -> pd.DataFrame:
        """遍历目录下所有股票文件进行回测"""
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
                        'ma120_at_breakthrough': result.ma120_at_breakthrough,
                        'held_p0': result.held_p0,
                        'held_ma120': result.held_ma120,
                        'held_p0_days': result.held_p0_days,
                        'held_ma120_days': result.held_ma120_days,
                        'min_deviation_p0': result.min_deviation_p0,
                        'min_deviation_ma': result.min_deviation_ma,
                        'broke_p0_count': result.broke_p0_count,
                        'broke_ma_count': result.broke_ma_count,
                        'max_gain': result.max_gain,
                        'final_gain': result.final_gain,
                        'success': result.success,
                    })

        return pd.DataFrame(results)

    def classify_group(self, row: pd.Series) -> str:
        """
        利弗莫尔分组：
        A组：始终守住P0 + 守住MA（完全符合利弗莫尔）
        B组：守住P0但曾<MA
        C组：跌破P0但<3%
        D组：跌破P0 3%~10%
        E组：跌破P0 >10%
        """
        held_p0 = row['held_p0']
        held_ma120 = row['held_ma120']
        deviation = row['min_deviation_p0']  # 负数表示跌破

        if held_p0 and held_ma120:
            return 'A(守P0+守MA)'
        elif held_p0 and not held_ma120:
            return 'B(守P0+破MA)'
        elif deviation >= -3:
            return 'C(<3%)'
        elif deviation >= -10:
            return 'D(3~10%)'
        else:
            return 'E(>10%)'

    def group_statistics(self, result_df: pd.DataFrame) -> dict:
        """分组统计"""
        if result_df.empty:
            return {}

        result_df = result_df.copy()
        result_df['group'] = result_df.apply(self.classify_group, axis=1)

        grouped = result_df.groupby('group').agg({
            'ts_code': 'count',
            'final_gain': 'mean',
            'max_gain': 'mean',
            'success': 'mean',
            'held_p0_days': 'mean',
            'held_ma120_days': 'mean',
        }).rename(columns={
            'ts_code': 'count',
            'final_gain': 'avg_final_gain',
            'max_gain': 'avg_max_gain',
            'success': 'success_rate',
            'held_p0_days': 'avg_held_p0_days',
            'held_ma120_days': 'avg_held_ma120_days',
        }).round(2)

        return grouped.sort_index()

    def save_results(self, result_df: pd.DataFrame, filename: str = None):
        """保存结果到CSV"""
        if result_df.empty:
            return
        if filename is None:
            from datetime import datetime
            today = datetime.now().strftime('%Y%m%d')
            filename = os.path.join('cy_quant', 'output', f'livermore_results_{today}.csv')
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"结果已保存至: {filename}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='利弗莫尔标准回测')
    parser.add_argument('--observe-days', type=int, default=10, help='观察期天数')
    parser.add_argument('--success-threshold', type=float, default=20.0, help='成功阈值（%%）')
    parser.add_argument('--stock-dir', type=str, default=None, help='股票数据目录')
    parser.add_argument('--prefixes', type=str, default='sh,sz', help='文件前缀，逗号分隔')
    args = parser.parse_args()

    prefixes = args.prefixes.split(',') if args.prefixes else ['sh', 'sz']

    analyzer = LivermoreAnalyzer(
        observe_days=args.observe_days,
        success_threshold=args.success_threshold,
    )

    print(f"开始回测（观察期={args.observe_days}天，成功阈值={args.success_threshold}%%）...")
    print("利弗莫尔标准：不能跌破P0（突破价），不能跌破MA120")
    result_df = analyzer.analyze_all(stock_dir=args.stock_dir, prefixes=prefixes)

    if result_df.empty:
        print("未找到有效数据")
        return

    print(f"\n共分析 {len(result_df)} 只股票突破120日均线")

    # 分组统计
    grouped = analyzer.group_statistics(result_df)
    print("\n利弗莫尔分组统计结果：")
    print(grouped.to_string())

    # 额外分析：守住P0 vs 未守住P0
    held_p0_df = result_df[result_df['held_p0'] == True]
    broke_p0_df = result_df[result_df['held_p0'] == False]

    print(f"\n守住P0 vs 跌破P0：")
    print(f"守住P0：{len(held_p0_df)}只，成功率{held_p0_df['success'].mean():.2%}，平均涨幅{held_p0_df['final_gain'].mean():.2f}%")
    print(f"跌破P0：{len(broke_p0_df)}只，成功率{broke_p0_df['success'].mean():.2%}，平均涨幅{broke_p0_df['final_gain'].mean():.2f}%")

    # 额外分析：守住MA vs 未守住MA
    held_ma_df = result_df[result_df['held_ma120'] == True]
    broke_ma_df = result_df[result_df['held_ma120'] == False]

    print(f"\n守住MA120 vs 跌破MA120：")
    print(f"守住MA120：{len(held_ma_df)}只，成功率{held_ma_df['success'].mean():.2%}，平均涨幅{held_ma_df['final_gain'].mean():.2f}%")
    print(f"跌破MA120：{len(broke_ma_df)}只，成功率{broke_ma_df['success'].mean():.2%}，平均涨幅{broke_ma_df['final_gain'].mean():.2f}%")

    analyzer.save_results(result_df)


if __name__ == '__main__':
    main()
