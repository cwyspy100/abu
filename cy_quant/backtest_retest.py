"""
回踩幅度回测：验证突破120日均线后，小幅回踩的股票是否继续上涨
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
    breakthrough_date: str       # 突破日 YYYYMMDD
    breakthrough_price: float    # 突破日收盘价
    max_drawdown: float          # 观察期内最大回踩幅度 (%)
    max_gain: float             # 观察期内最大涨幅 (%)
    success: bool                # 是否达标（最大涨幅 >= 成功阈值）
    final_gain: float            # 观察期最后一天累计涨幅 (%)


class RetestAnalyzer:
    """回踩幅度回测分析器"""

    def __init__(
        self,
        observe_days: int = 20,
        success_threshold: float = 20.0,  # 单位：%
    ):
        self.observe_days = observe_days
        self.success_threshold = success_threshold

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

        # 计算120日均线
        df['ma120'] = df['close'].rolling(window=120, min_periods=120).mean()
        df['ma120'] = df['ma120'].fillna(df['close'])

        # 找突破日（收盘价首次站上120日均线）
        df['above_ma120'] = df['close'] > df['ma120']
        breakthrough_idx = None
        for i in range(120, len(df)):
            if df.iloc[i]['above_ma120'] and not df.iloc[i-1]['above_ma120']:
                breakthrough_idx = i
                break

        if breakthrough_idx is None:
            return None

        bt_date = str(df.iloc[breakthrough_idx]['trade_date'])
        bt_price = df.iloc[breakthrough_idx]['close']

        # 观察期数据
        end_idx = min(breakthrough_idx + self.observe_days, len(df) - 1)
        observe_df = df.iloc[breakthrough_idx: end_idx + 1].copy()

        if len(observe_df) < 2:
            return None

        # 计算最大回踩幅度
        max_drawdown = 0.0
        for i in range(1, len(observe_df)):
            low = observe_df.iloc[i]['low'] if 'low' in observe_df.columns else observe_df.iloc[i]['close']
            drawdown = (bt_price - low) / bt_price * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        # 计算最大涨幅
        max_gain = 0.0
        for i in range(1, len(observe_df)):
            price = observe_df.iloc[i]['close']
            gain = (price - bt_price) / bt_price * 100
            if gain > max_gain:
                max_gain = gain

        # 最终涨幅（观察期最后一天）
        final_price = observe_df.iloc[-1]['close']
        final_gain = (final_price - bt_price) / bt_price * 100

        return BacktestResult(
            ts_code=os.path.basename(filepath).split('_')[0],
            breakthrough_date=bt_date,
            breakthrough_price=round(bt_price, 2),
            max_drawdown=round(max_drawdown, 2),
            max_gain=round(max_gain, 2),
            success=max_gain >= self.success_threshold,
            final_gain=round(final_gain, 2),
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
            pattern = os.path.join(stock_dir, f'{prefix}*.csv')
            files = glob.glob(pattern)
            for f in files:
                result = self.analyze_file(f)
                if result:
                    results.append({
                        'ts_code': result.ts_code,
                        'breakthrough_date': result.breakthrough_date,
                        'breakthrough_price': result.breakthrough_price,
                        'max_drawdown': result.max_drawdown,
                        'max_gain': result.max_gain,
                        'success': result.success,
                        'final_gain': result.final_gain,
                    })

        df = pd.DataFrame(results)
        return df

    def group_by_drawdown(self, result_df: pd.DataFrame) -> dict:
        """
        按回踩幅度分组统计
        分组：
          A: 0%（未回踩）
          B: 0% < <= 3%
          C: 3% < <= 5%
          D: 5% < <= 10%
          E: > 10%
        """
        if result_df.empty:
            return {}

        def classify(drawdown):
            if drawdown == 0:
                return 'A (0%)'
            elif drawdown <= 3:
                return 'B (0%~3%)'
            elif drawdown <= 5:
                return 'C (3%~5%)'
            elif drawdown <= 10:
                return 'D (5%~10%)'
            else:
                return 'E (>10%)'

        result_df = result_df.copy()
        result_df['group'] = result_df['max_drawdown'].apply(classify)

        grouped = result_df.groupby('group').agg(
            count=('ts_code', 'count'),
            avg_max_gain=('max_gain', 'mean'),
            avg_final_gain=('final_gain', 'mean'),
            success_rate=('success', 'mean'),
        ).round(2)

        return grouped.sort_index()

    def save_results(self, result_df: pd.DataFrame, filename: str = None):
        """保存结果到CSV"""
        if result_df.empty:
            return
        if filename is None:
            from datetime import datetime
            today = datetime.now().strftime('%Y%m%d')
            filename = os.path.join('cy_quant', 'output', f'retest_results_{today}.csv')
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"结果已保存至: {filename}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='回踩幅度回测')
    parser.add_argument('--observe-days', type=int, default=20, help='观察期天数')
    parser.add_argument('--success-threshold', type=float, default=20.0, help='成功阈值（%%）')
    parser.add_argument('--stock-dir', type=str, default=None, help='股票数据目录')
    parser.add_argument('--prefixes', type=str, default='sh,sz', help='文件前缀，逗号分隔')
    args = parser.parse_args()

    prefixes = args.prefixes.split(',') if args.prefixes else ['sh', 'sz']

    analyzer = RetestAnalyzer(
        observe_days=args.observe_days,
        success_threshold=args.success_threshold,
    )

    print(f"开始回测（观察期={args.observe_days}天，成功阈值={args.success_threshold}%%）...")
    result_df = analyzer.analyze_all(stock_dir=args.stock_dir, prefixes=prefixes)

    if result_df.empty:
        print("未找到有效数据")
        return

    print(f"\n共分析 {len(result_df)} 只股票突破120日均线")

    # 分组统计
    grouped = analyzer.group_by_drawdown(result_df)
    print("\n分组统计结果：")
    print(grouped.to_string())

    # 保存
    analyzer.save_results(result_df)


if __name__ == '__main__':
    main()