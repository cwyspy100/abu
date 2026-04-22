"""
方向A前置条件回测：验证突破120日均线前，各项前置条件是否能筛选出更高质量的突破

前置条件：
1. MA接近度 (MA proximity): 突破前价格在MA120的3%范围内持续N天
2. 放量 (Volume surge): 突破日成交量 > 2x 过去20日均量
3. 多头排列 (Multi-MA bullish): MA10 > MA20 > MA60 > MA120
4. 创新高 (New high): 突破日最高价 >= 20日最高价

分组：
- 基础组: 所有突破（无筛选）
- A1组: MA接近度满足
- A2组: 放量满足
- A3组: 多头排列满足
- A4组: 创新高满足
- 优质组: 所有条件满足
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
    ma_proximity: bool           # MA接近度是否满足
    volume_surge: bool           # 放量是否满足
    multi_ma_bullish: bool       # 多头排列是否满足
    new_high: bool               # 创新高是否满足
    is_premium: bool             # 是否为优质突破（所有条件满足）
    final_gain: float            # 观察期最终累计涨幅 (%)
    success: bool                # 是否达标（最终涨幅 >= 成功阈值）


class PrerequisitesAnalyzer:
    """方向A前置条件回测分析器"""

    MA_PERIOD = 120

    def __init__(
        self,
        observe_days: int = 10,
        success_threshold: float = 20.0,  # 单位：%
        ma_proximity_days: int = 10,
        ma_proximity_threshold: float = 3.0,  # 单位：%
        volume_avg_days: int = 20,
        volume_ratio_threshold: float = 2.0,
        nh_lookback: int = 20,
    ):
        self.observe_days = observe_days
        self.success_threshold = success_threshold
        self.ma_proximity_days = ma_proximity_days
        self.ma_proximity_threshold = ma_proximity_threshold
        self.volume_avg_days = volume_avg_days
        self.volume_ratio_threshold = volume_ratio_threshold
        self.nh_lookback = nh_lookback

    def check_ma_proximity(self, df: pd.DataFrame, bt_idx: int) -> bool:
        """
        检查MA接近度：突破前N天内，价格一直在MA120的threshold%范围内
        :param df: 股票数据
        :param bt_idx: 突破日索引
        :return: 是否满足MA接近度条件
        """
        start_idx = bt_idx - self.ma_proximity_days
        if start_idx < 0:
            return False

        ma_col = f'ma{self.MA_PERIOD}'
        for i in range(start_idx, bt_idx):
            close = df.iloc[i]['close']
            ma = df.iloc[i][ma_col]
            if ma == 0:
                return False
            ratio = abs(close - ma) / ma * 100
            if ratio > self.ma_proximity_threshold:
                return False
        return True

    def check_volume_surge(self, df: pd.DataFrame, bt_idx: int) -> bool:
        """
        检查放量：突破日成交量 >= threshold x 过去N日平均成交量
        :param df: 股票数据
        :param bt_idx: 突破日索引
        :return: 是否满足放量条件
        """
        if 'volume' not in df.columns:
            return False

        start_idx = bt_idx - self.volume_avg_days
        if start_idx < 0:
            return False

        # 计算过去N日平均成交量（不包含突破日）
        avg_volume = df.iloc[start_idx:bt_idx]['volume'].mean()
        if avg_volume == 0:
            return False

        bt_volume = df.iloc[bt_idx]['volume']
        return bt_volume >= avg_volume * self.volume_ratio_threshold

    def check_multi_ma_bullish(self, df: pd.DataFrame, bt_idx: int) -> bool:
        """
        检查多头排列：MA10 > MA20 > MA60 > MA120
        :param df: 股票数据
        :param bt_idx: 突破日索引
        :return: 是否满足多头排列条件
        """
        # 确保有足够的MA数据
        required_periods = [10, 20, 60, self.MA_PERIOD]
        for period in required_periods:
            if bt_idx < period:
                return False

        ma10 = df.iloc[bt_idx]['ma10']
        ma20 = df.iloc[bt_idx]['ma20']
        ma60 = df.iloc[bt_idx]['ma60']
        ma120 = df.iloc[bt_idx][f'ma{self.MA_PERIOD}']

        # 检查是否都是正数且呈多头排列
        if ma10 <= 0 or ma20 <= 0 or ma60 <= 0 or ma120 <= 0:
            return False

        return ma10 > ma20 > ma60 > ma120

    def check_new_high(self, df: pd.DataFrame, bt_idx: int) -> bool:
        """
        检查创新高：突破日最高价 >= N日最高价
        :param df: 股票数据
        :param bt_idx: 突破日索引
        :return: 是否满足创新高条件
        """
        if 'high' not in df.columns:
            return False

        start_idx = bt_idx - self.nh_lookback
        if start_idx < 0:
            return False

        # 计算过去N日的最高价（不包含突破日）
        nh_high = df.iloc[start_idx:bt_idx]['high'].max()
        bt_high = df.iloc[bt_idx]['high']

        return bt_high >= nh_high

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

        # 计算各周期MA
        df['ma10'] = df['close'].rolling(window=10, min_periods=10).mean()
        df['ma20'] = df['close'].rolling(window=20, min_periods=20).mean()
        df['ma60'] = df['close'].rolling(window=60, min_periods=60).mean()
        df[f'ma{self.MA_PERIOD}'] = df['close'].rolling(window=self.MA_PERIOD, min_periods=self.MA_PERIOD).mean()

        # 填充MA缺失值
        df['ma10'] = df['ma10'].fillna(df['close'])
        df['ma20'] = df['ma20'].fillna(df['close'])
        df['ma60'] = df['ma60'].fillna(df['close'])
        df[f'ma{self.MA_PERIOD}'] = df[f'ma{self.MA_PERIOD}'].fillna(df['close'])

        # 找突破日（收盘价首次站上MA120）
        df['above_ma'] = df['close'] > df[f'ma{self.MA_PERIOD}']
        breakthrough_idx = None
        for i in range(self.MA_PERIOD, len(df)):
            if df.iloc[i]['above_ma'] and not df.iloc[i-1]['above_ma']:
                breakthrough_idx = i
                break

        if breakthrough_idx is None:
            return None

        bt_date = str(df.iloc[breakthrough_idx]['trade_date'])
        bt_price = df.iloc[breakthrough_idx]['close']

        # 检查各项前置条件
        ma_proximity = self.check_ma_proximity(df, breakthrough_idx)
        volume_surge = self.check_volume_surge(df, breakthrough_idx)
        multi_ma_bullish = self.check_multi_ma_bullish(df, breakthrough_idx)
        new_high = self.check_new_high(df, breakthrough_idx)
        is_premium = ma_proximity and volume_surge and multi_ma_bullish and new_high

        # 观察期数据
        end_idx = min(breakthrough_idx + self.observe_days, len(df) - 1)
        observe_df = df.iloc[breakthrough_idx: end_idx + 1].copy()

        if len(observe_df) < 2:
            return None

        # 计算最终涨幅（观察期最后一天）
        final_price = observe_df.iloc[-1]['close']
        final_gain = (final_price - bt_price) / bt_price * 100

        return BacktestResult(
            ts_code=os.path.basename(filepath).split('_')[0],
            breakthrough_date=bt_date,
            breakthrough_price=round(bt_price, 2),
            ma_proximity=ma_proximity,
            volume_surge=volume_surge,
            multi_ma_bullish=multi_ma_bullish,
            new_high=new_high,
            is_premium=is_premium,
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
                        'ma_proximity': result.ma_proximity,
                        'volume_surge': result.volume_surge,
                        'multi_ma_bullish': result.multi_ma_bullish,
                        'new_high': result.new_high,
                        'is_premium': result.is_premium,
                        'final_gain': result.final_gain,
                        'success': result.success,
                    })

        df = pd.DataFrame(results)
        return df

    def group_statistics(self, result_df: pd.DataFrame) -> dict:
        """
        按前置条件分组统计
        分组：
          基础组: 所有突破
          A1组: MA接近度满足
          A2组: 放量满足
          A3组: 多头排列满足
          A4组: 创新高满足
          优质组: 所有条件满足
        """
        if result_df.empty:
            return {}

        stats = {}

        # 基础组
        basic = result_df.copy()
        stats['基础组'] = {
            'count': len(basic),
            'avg_gain': round(basic['final_gain'].mean(), 2),
            'success_rate': round(basic['success'].mean() * 100, 2),
        }

        # A1组: MA接近度
        a1 = result_df[result_df['ma_proximity'] == True]
        stats['A1组'] = {
            'count': len(a1),
            'avg_gain': round(a1['final_gain'].mean(), 2) if len(a1) > 0 else 0,
            'success_rate': round(a1['success'].mean() * 100, 2) if len(a1) > 0 else 0,
        }

        # A2组: 放量
        a2 = result_df[result_df['volume_surge'] == True]
        stats['A2组'] = {
            'count': len(a2),
            'avg_gain': round(a2['final_gain'].mean(), 2) if len(a2) > 0 else 0,
            'success_rate': round(a2['success'].mean() * 100, 2) if len(a2) > 0 else 0,
        }

        # A3组: 多头排列
        a3 = result_df[result_df['multi_ma_bullish'] == True]
        stats['A3组'] = {
            'count': len(a3),
            'avg_gain': round(a3['final_gain'].mean(), 2) if len(a3) > 0 else 0,
            'success_rate': round(a3['success'].mean() * 100, 2) if len(a3) > 0 else 0,
        }

        # A4组: 创新高
        a4 = result_df[result_df['new_high'] == True]
        stats['A4组'] = {
            'count': len(a4),
            'avg_gain': round(a4['final_gain'].mean(), 2) if len(a4) > 0 else 0,
            'success_rate': round(a4['success'].mean() * 100, 2) if len(a4) > 0 else 0,
        }

        # 优质组: 所有条件满足
        premium = result_df[result_df['is_premium'] == True]
        stats['优质组'] = {
            'count': len(premium),
            'avg_gain': round(premium['final_gain'].mean(), 2) if len(premium) > 0 else 0,
            'success_rate': round(premium['success'].mean() * 100, 2) if len(premium) > 0 else 0,
        }

        return stats

    def save_results(self, result_df: pd.DataFrame, filename: str = None):
        """保存结果到CSV"""
        if result_df.empty:
            return
        if filename is None:
            from datetime import datetime
            today = datetime.now().strftime('%Y%m%d')
            filename = os.path.join('cy_quant', 'output', f'prerequisites_results_{today}.csv')
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"结果已保存至: {filename}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='方向A前置条件回测')
    parser.add_argument('--observe-days', type=int, default=10, help='观察期天数')
    parser.add_argument('--success-threshold', type=float, default=20.0, help='成功阈值（%%）')
    parser.add_argument('--stock-dir', type=str, default=None, help='股票数据目录')
    parser.add_argument('--prefixes', type=str, default='sh,sz', help='文件前缀，逗号分隔')
    args = parser.parse_args()

    prefixes = args.prefixes.split(',') if args.prefixes else ['sh', 'sz']

    analyzer = PrerequisitesAnalyzer(
        observe_days=args.observe_days,
        success_threshold=args.success_threshold,
    )

    print(f"开始方向A前置条件回测（观察期={args.observe_days}天，成功阈值={args.success_threshold}%%）...")
    result_df = analyzer.analyze_all(stock_dir=args.stock_dir, prefixes=prefixes)

    if result_df.empty:
        print("未找到有效数据")
        return

    print(f"\n共分析 {len(result_df)} 只股票突破120日均线")

    # 分组统计
    stats = analyzer.group_statistics(result_df)
    print("\n分组统计结果：")
    print(f"{'分组':<10} {'数量':>6} {'平均涨幅':>10} {'成功率':>10}")
    print("-" * 40)
    for group_name, data in stats.items():
        print(f"{group_name:<10} {data['count']:>6} {data['avg_gain']:>10.2f}% {data['success_rate']:>10.2f}%")

    # 保存
    analyzer.save_results(result_df)


if __name__ == '__main__':
    main()
