# 方向A前置条件回测实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现方向A前置条件回测，验证突破前置条件是否能提前筛选出更优质的股票

**Architecture:** 独立文件 `backtest_prerequisites.py`，在方向二的基础上增加前置条件筛选逻辑，对比各组样本数和成功率

**Tech Stack:** Python 3, pandas, numpy

---

## 文件结构

```
cy_quant/
├── backtest_retest.py           # 已存在：方向一
├── backtest_direction2.py       # 已存在：方向二
├── backtest_direction3.py      # 已存在：方向三
├── backtest_direction4.py       # 已存在：方向四
├── backtest_prerequisites.py   # 新建：方向A前置条件回测
└── output/
```

---

## 回测参数默认值

| 参数 | 默认值 |
|------|--------|
| observe_days | 10 |
| success_threshold | 20.0 |
| ma_proximity_days | 10 |
| ma_proximity_threshold | 3.0 |
| volume_avg_days | 20 |
| volume_ratio_threshold | 2.0 |
| nh_lookback | 20 |

---

## 分组定义

| 组别 | 条件 | 说明 |
|------|------|------|
| 基础组 | 只有突破120日均线 | 无前置条件 |
| A1组 | 突破 + MA接近度 | 突破前10天价格在均线附近<3% |
| A2组 | 突破 + 放量 | 突破当天成交量>均量2倍 |
| A3组 | 突破 + 多头排列 | 20日>60日>120日 |
| A4组 | 突破 + 创20日新高 | 突破当天创20日新高 |
| 优质组 | 突破 + 全部满足 | A1+A2+A3+A4全部满足 |

---

## 任务清单

### Task 1: 创建 `backtest_prerequisites.py`

**Files:**
- Create: `cy_quant/backtest_prerequisites.py`

- [ ] **Step 1: 编写 `backtest_prerequisites.py`**

```python
"""
方向A前置条件回测：验证突破前置条件是否能提前筛选优质股票
对比基础组 vs 各前置条件组 vs 优质组的样本数和成功率
"""

import pandas as pd
import numpy as np
import os
import glob
from dataclasses import dataclass, field
from typing import Optional, Literal


@dataclass
class BacktestResult:
    """回测结果容器"""
    ts_code: str
    breakthrough_date: str           # 突破日 YYYYMMDD
    breakthrough_price: float        # 突破日收盘价

    # 前置条件指标
    ma_proximity: bool              # MA接近度（突破前10天价格在均线附近<3%）
    volume_surge: bool              # 放量（成交量>均量2倍）
    multi_ma_bullish: bool          # 多头排列（20日>60日>120日）
    new_high: bool                  # 创新高（创20日新高）

    # 综合指标
    is_premium: bool               # 是否为优质突破（全部满足）

    # 涨幅指标
    final_gain: float               # 观察期末涨幅 (%)
    success: bool                   # 是否达标


class PrerequisitesAnalyzer:
    """方向A前置条件分析器"""

    MA_PERIOD = 120
    MA10_PERIOD = 10
    MA20_PERIOD = 20
    MA60_PERIOD = 60

    # 前置条件默认值
    MA_PROXIMITY_DAYS = 10
    MA_PROXIMITY_THRESHOLD = 3.0  # %
    VOLUME_AVG_DAYS = 20
    VOLUME_RATIO_THRESHOLD = 2.0
    NH_LOOKBACK = 20

    def __init__(
        self,
        observe_days: int = 10,
        success_threshold: float = 20.0,
        ma_proximity_days: int = 10,
        ma_proximity_threshold: float = 3.0,
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

    def check_ma_proximity(self, df: pd.DataFrame, breakthrough_idx: int) -> bool:
        """
        检查MA接近度：突破前N天价格在均线附近（偏离<阈值%）
        """
        if breakthrough_idx < self.ma_proximity_days:
            return False

        start_idx = breakthrough_idx - self.ma_proximity_days
        period_df = df.iloc[start_idx:breakthrough_idx]

        for _, row in period_df.iterrows():
            ma_value = row.get(f'ma{self.MA_PERIOD}', row['close'])
            if ma_value <= 0:
                continue
            deviation = abs(row['close'] - ma_value) / ma_value * 100
            if deviation > self.ma_proximity_threshold:
                return False
        return True

    def check_volume_surge(self, df: pd.DataFrame, breakthrough_idx: int) -> bool:
        """
        检查放量：突破当天成交量 > 过去N日平均成交量 * 倍数
        """
        if breakthrough_idx < self.volume_avg_days:
            return False

        avg_volume = df.iloc[breakthrough_idx - self.volume_avg_days:breakthrough_idx]['volume'].mean()
        if avg_volume <= 0:
            return False

        today_volume = df.iloc[breakthrough_idx]['volume']
        return today_volume >= avg_volume * self.volume_ratio_threshold

    def check_multi_ma_bullish(self, df: pd.DataFrame, breakthrough_idx: int) -> bool:
        """
        检查多头排列：20日 > 60日 > 120日
        """
        if breakthrough_idx < self.MA60_PERIOD:
            return False

        ma10 = df.iloc[breakthrough_idx].get(f'ma{self.MA10_PERIOD}', 0)
        ma20 = df.iloc[breakthrough_idx].get(f'ma{self.MA20_PERIOD}', 0)
        ma60 = df.iloc[breakthrough_idx].get(f'ma{self.MA60_PERIOD}', 0)
        ma120 = df.iloc[breakthrough_idx].get(f'ma{self.MA_PERIOD}', 0)

        if ma120 <= 0:
            return False

        return ma10 > ma20 > ma60 > ma120

    def check_new_high(self, df: pd.DataFrame, breakthrough_idx: int) -> bool:
        """
        检查创新高：突破当天同时创N日新高
        """
        if breakthrough_idx < self.nh_lookback:
            return False

        today_high = df.iloc[breakthrough_idx]['high']
        lookback_high = df.iloc[breakthrough_idx - self.nh_lookback:breakthrough_idx]['high'].max()

        return today_high >= lookback_high

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

        # 计算各周期MA
        for period in [10, 20, 60, self.MA_PERIOD]:
            df[f'ma{period}'] = df['close'].rolling(window=period, min_periods=period).mean()
            df[f'ma{period}'] = df[f'ma{period}'].fillna(df['close'])

        # 找突破日
        df['above_ma'] = df['close'] > df[f'ma{self.MA_PERIOD}']
        breakthrough_idx = None
        for i in range(self.MA_PERIOD, len(df)):
            if df.iloc[i]['above_ma'] and not df.iloc[i - 1]['above_ma']:
                breakthrough_idx = i
                break

        if breakthrough_idx is None:
            return None

        bt_date = str(df.iloc[breakthrough_idx]['trade_date'])
        bt_price = df.iloc[breakthrough_idx]['close']

        # 检查前置条件
        ma_proximity = self.check_ma_proximity(df, breakthrough_idx)
        volume_surge = self.check_volume_surge(df, breakthrough_idx)
        multi_ma_bullish = self.check_multi_ma_bullish(df, breakthrough_idx)
        new_high = self.check_new_high(df, breakthrough_idx)

        is_premium = ma_proximity and volume_surge and multi_ma_bullish and new_high

        # 观察期数据
        end_idx = min(breakthrough_idx + self.observe_days, len(df) - 1)
        if end_idx <= breakthrough_idx:
            return None

        observe_df = df.iloc[breakthrough_idx:end_idx + 1].copy()
        if len(observe_df) < 2:
            return None

        # 最终涨幅
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
                        'ma_proximity': result.ma_proximity,
                        'volume_surge': result.volume_surge,
                        'multi_ma_bullish': result.multi_ma_bullish,
                        'new_high': result.new_high,
                        'is_premium': result.is_premium,
                        'final_gain': result.final_gain,
                        'success': result.success,
                    })

        return pd.DataFrame(results)

    def group_statistics(self, result_df: pd.DataFrame) -> dict:
        """分组统计"""
        if result_df.empty:
            return {}

        stats = {}

        # 基础组
        basic_df = result_df
        stats['基础组'] = {
            'count': len(basic_df),
            'avg_final_gain': basic_df['final_gain'].mean(),
            'success_rate': basic_df['success'].mean(),
        }

        # A1组: MA接近度
        a1_df = result_df[result_df['ma_proximity'] == True]
        stats['A1组(MA接近度)'] = {
            'count': len(a1_df),
            'avg_final_gain': a1_df['final_gain'].mean() if len(a1_df) > 0 else 0,
            'success_rate': a1_df['success'].mean() if len(a1_df) > 0 else 0,
        }

        # A2组: 放量
        a2_df = result_df[result_df['volume_surge'] == True]
        stats['A2组(放量)'] = {
            'count': len(a2_df),
            'avg_final_gain': a2_df['final_gain'].mean() if len(a2_df) > 0 else 0,
            'success_rate': a2_df['success'].mean() if len(a2_df) > 0 else 0,
        }

        # A3组: 多头排列
        a3_df = result_df[result_df['multi_ma_bullish'] == True]
        stats['A3组(多头排列)'] = {
            'count': len(a3_df),
            'avg_final_gain': a3_df['final_gain'].mean() if len(a3_df) > 0 else 0,
            'success_rate': a3_df['success'].mean() if len(a3_df) > 0 else 0,
        }

        # A4组: 创新高
        a4_df = result_df[result_df['new_high'] == True]
        stats['A4组(创新高)'] = {
            'count': len(a4_df),
            'avg_final_gain': a4_df['final_gain'].mean() if len(a4_df) > 0 else 0,
            'success_rate': a4_df['success'].mean() if len(a4_df) > 0 else 0,
        }

        # 优质组
        premium_df = result_df[result_df['is_premium'] == True]
        stats['优质组(全部)'] = {
            'count': len(premium_df),
            'avg_final_gain': premium_df['final_gain'].mean() if len(premium_df) > 0 else 0,
            'success_rate': premium_df['success'].mean() if len(premium_df) > 0 else 0,
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
    parser.add_argument('--ma-proximity-days', type=int, default=10, help='MA接近度统计天数')
    parser.add_argument('--ma-proximity-threshold', type=float, default=3.0, help='MA接近度偏离阈值（%%）')
    parser.add_argument('--volume-avg-days', type=int, default=20, help='成交量平均天数')
    parser.add_argument('--volume-ratio-threshold', type=float, default=2.0, help='放量倍数阈值')
    parser.add_argument('--nh-lookback', type=int, default=20, help='创新高统计天数')
    parser.add_argument('--stock-dir', type=str, default=None, help='股票数据目录')
    parser.add_argument('--prefixes', type=str, default='sh,sz', help='文件前缀，逗号分隔')
    args = parser.parse_args()

    prefixes = args.prefixes.split(',') if args.prefixes else ['sh', 'sz']

    analyzer = PrerequisitesAnalyzer(
        observe_days=args.observe_days,
        success_threshold=args.success_threshold,
        ma_proximity_days=args.ma_proximity_days,
        ma_proximity_threshold=args.ma_proximity_threshold,
        volume_avg_days=args.volume_avg_days,
        volume_ratio_threshold=args.volume_ratio_threshold,
        nh_lookback=args.nh_lookback,
    )

    print(f"开始回测（观察期={args.observe_days}天，成功阈值={args.success_threshold}%%）...")
    print(f"前置条件：MA接近度{args.ma_proximity_days}天<{args.ma_proximity_threshold}%%，放量>{args.volume_ratio_threshold}倍，创{nh_lookback}日新高")

    result_df = analyzer.analyze_all(stock_dir=args.stock_dir, prefixes=prefixes)

    if result_df.empty:
        print("未找到有效数据")
        return

    print(f"\n共分析 {len(result_df)} 只股票突破120日均线")

    # 分组统计
    stats = analyzer.group_statistics(result_df)
    print("\n分组统计结果：")
    print(f"{'组别':<20} {'样本数':>8} {'avg_final_gain':>15} {'success_rate':>12}")
    print("-" * 60)
    for name, s in stats.items():
        print(f"{name:<20} {s['count']:>8} {s['avg_final_gain']:>14.2f}% {s['success_rate']:>11.2%}")

    # 筛选效果
    basic_count = stats['基础组']['count']
    premium_count = stats['优质组(全部)']['count']
    basic_rate = stats['基础组']['success_rate']
    premium_rate = stats['优质组(全部)']['success_rate']

    print(f"\n筛选效果：")
    print(f"基础组 {basic_count} 只 -> 优质组 {premium_count} 只（缩减 {basic_count - premium_count} 只，保留 {premium_count/basic_count*100:.1f}%）")
    print(f"成功率：基础组 {basic_rate:.2%} -> 优质组 {premium_rate:.2%}（提升 {(premium_rate - basic_rate):.2%}）")

    analyzer.save_results(result_df)


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 运行测试验证代码可执行**

```bash
python -c "from cy_quant.backtest_prerequisites import PrerequisitesAnalyzer; print('OK')"
```
Expected: OK

- [ ] **Step 3: 运行完整回测**

```bash
python -m cy_quant.backtest_prerequisites --observe-days 10 --success-threshold 20.0
```

- [ ] **Step 4: 提交**

```bash
git add cy_quant/backtest_prerequisites.py && git commit -m "feat: 实现方向A前置条件回测"
```

---

## 自检清单

- [ ] Spec覆盖：4个前置条件（MA接近度、放量、多头排列、创新高）、6个分组统计
- [ ] 占位符扫描：无 TBD/TODO
- [ ] 参数默认值：observe_days=10, ma_proximity_days=10, volume_ratio_threshold=2.0, nh_lookback=20
