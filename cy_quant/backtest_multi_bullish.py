"""
均线多头发散策略回测
策略：
1. 突破120日均线，且120/60/20日均线向上斜率
2. 20日在60日上方，60日在120日上方
3. 每涨10%加仓一次
4. 20日均线穿过60日均线时减仓50%，再跌10%只留100股
"""

import pandas as pd
import numpy as np
import os
import glob
from dataclasses import dataclass, field
from typing import Optional, List, Dict


@dataclass
class TradeRecord:
    """交易记录"""
    ts_code: str
    entry_date: str           # 买入日期
    entry_price: float         # 买入价格
    shares: int                # 持股数量
    avg_cost: float            # 持仓成本

    # 持仓期间
    highest_price: float       # 持仓期间最高价
    last_price: float          # 当前/卖出价格
    final_gain: float          # 最终收益率

    # 状态标志
    added_count: int           # 加仓次数
    exited: bool              # 是否已退出
    exit_reason: str          # 退出原因


class MaMultiBullishAnalyzer:
    """均线多头发散策略分析器"""

    MA_PERIOD_20 = 20
    MA_PERIOD_60 = 60
    MA_PERIOD_120 = 120

    # 斜率判定：MA_current > MA_previous 视为向上
    SLOPE_POSITIVE = True

    def __init__(
        self,
        observe_days: int = 60,
        add_threshold: float = 10.0,    # 加仓阈值（%）
        exit_after_add: bool = True,      # 加仓后是否触发新减仓线
        min_samples: int = 10,
    ):
        self.observe_days = observe_days
        self.add_threshold = add_threshold  # 10%
        self.exit_after_add = exit_after_add
        self.min_samples = min_samples

    def calculate_ma(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算所有均线"""
        df = df.copy()

        # 计算MA20, MA60, MA120
        df['ma20'] = df['close'].rolling(window=self.MA_PERIOD_20, min_periods=self.MA_PERIOD_20).mean()
        df['ma60'] = df['close'].rolling(window=self.MA_PERIOD_60, min_periods=self.MA_PERIOD_60).mean()
        df['ma120'] = df['close'].rolling(window=self.MA_PERIOD_120, min_periods=self.MA_PERIOD_120).mean()

        # 填充前期数据（数据不足时用收盘价代替）
        df['ma20'] = df['ma20'].fillna(df['close'])
        df['ma60'] = df['ma60'].fillna(df['close'])
        df['ma120'] = df['ma120'].fillna(df['close'])

        # 计算斜率（前一天的MA作为比较）
        df['ma20_prev'] = df['ma20'].shift(1)
        df['ma60_prev'] = df['ma60'].shift(1)
        df['ma120_prev'] = df['ma120'].shift(1)

        # 斜率是否向上（今天 > 昨天）
        df['slope_20_up'] = df['ma20'] > df['ma20_prev']
        df['slope_60_up'] = df['ma60'] > df['ma60_prev']
        df['slope_120_up'] = df['ma120'] > df['ma120_prev']

        # 多头排列：20日 > 60日 > 120日
        df['multi_bullish'] = (df['ma20'] > df['ma60']) & (df['ma60'] > df['ma120'])

        # 突破120日均线（当天收盘价站上MA120）
        df['above_ma120'] = df['close'] > df['ma120']
        df['prev_above_ma120'] = df['above_ma120'].shift(1)

        return df

    def check_entry_conditions(self, row: pd.Series) -> bool:
        """检查买入条件"""
        return (
            row['above_ma120'] and
            row['prev_above_ma120'] == False and  # 首次突破
            row['slope_120_up'] and
            row['slope_60_up'] and
            row['slope_20_up'] and
            row['ma20'] > row['ma60'] and
            row['ma60'] > row['ma120']
        )

    def check_exit_conditions(self, df: pd.DataFrame, current_idx: int) -> tuple:
        """检查卖出条件：20日均线穿过60日均线"""
        if current_idx < 1:
            return False, ""

        current_row = df.iloc[current_idx]
        prev_row = df.iloc[current_idx - 1]

        # 20日均线穿过60日均线（向下穿越）
        # 之前：ma20 > ma60，现在 ma20 < ma60
        if prev_row['ma20'] > prev_row['ma60'] and current_row['ma20'] < current_row['ma60']:
            return True, "死叉(20穿过60)"

        return False, ""

    def analyze_file(self, filepath: str) -> Optional[TradeRecord]:
        """分析单个股票文件"""
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

        # 需要足够的数据计算MA120
        if len(df) < self.MA_PERIOD_120 + 10:
            return None

        # 计算均线
        df = self.calculate_ma(df)

        # 找突破日
        breakthrough_idx = None
        for i in range(self.MA_PERIOD_120, len(df) - 1):
            if self.check_entry_conditions(df.iloc[i]):
                breakthrough_idx = i
                break

        if breakthrough_idx is None:
            return None

        # ========== 交易逻辑 ==========
        entry_date = str(df.iloc[breakthrough_idx]['trade_date'])
        entry_price = df.iloc[breakthrough_idx]['close']
        shares = 100  # 初始持股100股
        avg_cost = entry_price

        highest_price = entry_price
        add_count = 0
        exited = False
        exit_reason = ""
        last_price = entry_price

        # 加仓线：每次比前一次高10%时加仓
        add_price = entry_price * (1 + self.add_threshold / 100)

        # 减仓线：20日穿过60日时减仓50%
        half_exit_done = False
        half_exit_price = 0

        # 第二次减仓线：再跌10%只留100股
        final_exit_done = False
        final_exit_price = 0

        # 观察期终点
        end_idx = min(breakthrough_idx + self.observe_days, len(df) - 1)

        for i in range(breakthrough_idx + 1, end_idx + 1):
            current_row = df.iloc[i]
            current_price = current_row['close']
            current_date = str(current_row['trade_date'])

            # 更新最高价
            if current_price > highest_price:
                highest_price = current_price

            # 检查是否需要加仓（每涨10%加仓一次）
            if not exited:
                while current_price >= add_price:
                    # 加仓100股
                    new_shares = shares + 100
                    avg_cost = (avg_cost * shares + current_price * 100) / new_shares
                    shares = new_shares
                    add_count += 1
                    # 更新加仓线
                    add_price = entry_price * (1 + (add_count + 1) * self.add_threshold / 100)

                # 检查是否触发死叉（20穿过60）
                if i > 0:
                    prev_row = df.iloc[i - 1]
                    curr_row = df.iloc[i]

                    # 首次死叉：减仓一半
                    if not half_exit_done and prev_row['ma20'] > prev_row['ma60'] and curr_row['ma20'] < curr_row['ma60']:
                        half_exit_done = True
                        half_exit_price = current_price
                        shares = shares // 2  # 减仓一半
                        exit_reason = "死叉减半"

                    # 第二次减仓：再跌10%
                    elif half_exit_done and not final_exit_done:
                        if current_price <= half_exit_price * 0.9:
                            # 只留100股
                            shares_to_sell = shares - 100
                            if shares_to_sell > 0:
                                shares = 100
                                final_exit_done = True
                                exit_reason = "再跌10%清仓"
                                exited = True

            last_price = current_price

        # 最终收益率计算（按成本计算）
        final_gain = (last_price - avg_cost) / avg_cost * 100

        return TradeRecord(
            ts_code=os.path.basename(filepath).split('_')[0],
            entry_date=entry_date,
            entry_price=round(entry_price, 2),
            shares=shares,
            avg_cost=round(avg_cost, 2),
            highest_price=round(highest_price, 2),
            last_price=round(last_price, 2),
            final_gain=round(final_gain, 2),
            added_count=add_count,
            exited=exited or final_exit_done,
            exit_reason=exit_reason if exit_reason else ("观察期末" if not exited else ""),
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
                        'entry_date': result.entry_date,
                        'entry_price': result.entry_price,
                        'shares': result.shares,
                        'avg_cost': result.avg_cost,
                        'highest_price': result.highest_price,
                        'last_price': result.last_price,
                        'final_gain': result.final_gain,
                        'added_count': result.added_count,
                        'exited': result.exited,
                        'exit_reason': result.exit_reason,
                    })

        return pd.DataFrame(results)

    def analyze_baseline(self, stock_dir: str = None, prefixes=None) -> pd.DataFrame:
        """基准组：只做突破120日均线，无均线条件"""
        if stock_dir is None:
            stock_dir = os.path.expanduser('~/abu/data/csv')
        if prefixes is None:
            prefixes = ['sh', 'sz']

        results = []
        for prefix in prefixes:
            pattern = os.path.join(stock_dir, f'{prefix}*')
            files = glob.glob(pattern)
            for f in files:
                try:
                    df = pd.read_csv(f, encoding='utf-8-sig')
                except Exception:
                    try:
                        df = pd.read_csv(f, encoding='gbk')
                    except Exception:
                        continue

                if df.empty:
                    continue

                if 'date' in df.columns:
                    df = df.rename(columns={'date': 'trade_date'})
                if 'trade_date' not in df.columns or 'close' not in df.columns:
                    continue

                df = df.sort_values('trade_date').reset_index(drop=True)
                df['trade_date'] = df['trade_date'].astype(str)

                df['ma120'] = df['close'].rolling(window=120, min_periods=120).mean()
                df['ma120'] = df['ma120'].fillna(df['close'])

                df['above_ma120'] = df['close'] > df['ma120']

                # 找突破日
                breakthrough_idx = None
                for i in range(120, len(df) - 1):
                    if df.iloc[i]['above_ma120'] and not df.iloc[i - 1]['above_ma120']:
                        breakthrough_idx = i
                        break

                if breakthrough_idx is None:
                    continue

                end_idx = min(breakthrough_idx + self.observe_days, len(df) - 1)
                if end_idx <= breakthrough_idx:
                    continue

                entry_price = df.iloc[breakthrough_idx]['close']
                final_price = df.iloc[end_idx]['close']
                final_gain = (final_price - entry_price) / entry_price * 100

                results.append({
                    'ts_code': os.path.basename(f).split('_')[0],
                    'entry_date': str(df.iloc[breakthrough_idx]['trade_date']),
                    'entry_price': round(entry_price, 2),
                    'final_price': round(final_price, 2),
                    'final_gain': round(final_gain, 2),
                })

        return pd.DataFrame(results)

    def group_statistics(self, result_df: pd.DataFrame) -> dict:
        """分组统计"""
        if result_df.empty:
            return {}

        stats = {
            'total_count': len(result_df),
            'avg_gain': result_df['final_gain'].mean(),
            'median_gain': result_df['final_gain'].median(),
            'win_rate': (result_df['final_gain'] > 0).mean(),
            'success_rate': (result_df['final_gain'] >= 20).mean(),  # 20%为成功
        }

        return stats

    def save_results(self, result_df: pd.DataFrame, filename: str = None):
        """保存结果到CSV"""
        if result_df.empty:
            return
        if filename is None:
            from datetime import datetime
            today = datetime.now().strftime('%Y%m%d')
            filename = os.path.join('cy_quant', 'output', f'multi_bullish_results_{today}.csv')
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"结果已保存至: {filename}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='均线多头发散策略回测')
    parser.add_argument('--observe-days', type=int, default=60, help='观察期天数')
    parser.add_argument('--add-threshold', type=float, default=10.0, help='加仓阈值（%%）')
    parser.add_argument('--stock-dir', type=str, default=None, help='股票数据目录')
    parser.add_argument('--prefixes', type=str, default='sh,sz', help='文件前缀，逗号分隔')
    args = parser.parse_args()

    prefixes = args.prefixes.split(',') if args.prefixes else ['sh', 'sz']

    analyzer = MaMultiBullishAnalyzer(
        observe_days=args.observe_days,
        add_threshold=args.add_threshold,
    )

    print("=" * 60)
    print("均线多头发散策略回测")
    print("观察期: {}天".format(args.observe_days))
    print("加仓阈值: 每涨{}%加仓一次".format(args.add_threshold))
    print("=" * 60)

    # ========== 策略组 ==========
    print(f"\n分析策略组（均线多头发散）...")
    strategy_df = analyzer.analyze_all(stock_dir=args.stock_dir, prefixes=prefixes)

    if not strategy_df.empty:
        strategy_stats = analyzer.group_statistics(strategy_df)
        print(f"\n策略组统计（{len(strategy_df)}只股票）：")
        print(f"  平均收益: {strategy_stats['avg_gain']:.2f}%")
        print(f"  中位收益: {strategy_stats['median_gain']:.2f}%")
        print(f"  盈利比例: {strategy_stats['win_rate']:.2%}")
        print(f"  成功比例(>=20%): {strategy_stats['success_rate']:.2%}")

        # 加仓统计
        add_stats = strategy_df['added_count'].value_counts().sort_index()
        print(f"\n加仓次数分布：")
        for count, num in add_stats.items():
            print(f"  加仓{count}次: {num}只")

        # 退出原因统计
        exit_reasons = strategy_df['exit_reason'].value_counts()
        print(f"\n退出原因：")
        for reason, num in exit_reasons.items():
            print(f"  {reason}: {num}只")
    else:
        print("策略组未找到有效数据")

    # ========== 基准组 ==========
    print(f"\n分析基准组（仅突破120日均线）...")
    baseline_df = analyzer.analyze_baseline(stock_dir=args.stock_dir, prefixes=prefixes)

    if not baseline_df.empty:
        baseline_stats = analyzer.group_statistics(baseline_df)
        print(f"\n基准组统计（{len(baseline_df)}只股票）：")
        print(f"  平均收益: {baseline_stats['avg_gain']:.2f}%")
        print(f"  中位收益: {baseline_stats['median_gain']:.2f}%")
        print(f"  盈利比例: {baseline_stats['win_rate']:.2%}")
        print(f"  成功比例(>=20%): {baseline_stats['success_rate']:.2%}")

    # ========== 对比 ==========
    if not strategy_df.empty and not baseline_df.empty:
        print(f"\n" + "=" * 60)
        print(f"策略组 vs 基准组 对比：")
        print(f"{'指标':<15} {'策略组':>12} {'基准组':>12} {'差异':>12}")
        print(f"-" * 60)
        print(f"{'样本数':<15} {len(strategy_df):>12} {len(baseline_df):>12}")
        print(f"{'平均收益':<15} {strategy_stats['avg_gain']:>11.2f}% {baseline_stats['avg_gain']:>11.2f}% {(strategy_stats['avg_gain'] - baseline_stats['avg_gain']):>+10.2f}%")
        print(f"{'盈利比例':<15} {strategy_stats['win_rate']:>11.2%} {baseline_stats['win_rate']:>11.2%} {(strategy_stats['win_rate'] - baseline_stats['win_rate']):>+10.2%}")
        print(f"{'成功比例':<15} {strategy_stats['success_rate']:>11.2%} {baseline_stats['success_rate']:>11.2%} {(strategy_stats['success_rate'] - baseline_stats['success_rate']):>+10.2%}")

    # 保存结果
    analyzer.save_results(strategy_df)

    print(f"\n" + "=" * 60)


if __name__ == '__main__':
    main()
