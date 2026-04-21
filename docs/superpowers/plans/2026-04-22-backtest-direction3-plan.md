# 方向三实施计划：蓄力形态（盘整程度）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现方向三回测，验证「突破前盘整越充分，爆发力越强」的假设

**Architecture:** 独立文件 `backtest_direction3.py`，复用 `RetestAnalyzer` 的文件读取逻辑，计算盘整期振幅并分组统计

**Tech Stack:** Python 3, pandas, numpy

---

## 文件结构

```
cy_quant/
├── backtest_retest.py           # 已存在：方向一
├── backtest_direction3.py      # 新建：方向三
└── tests/
    └── test_backtest_direction3.py  # 新建：单元测试
```

---

## 回测参数默认值

| 参数 | 默认值 |
|------|--------|
| observe_days | 5 |
| consolidation_days | 20 |
| success_threshold | 20.0 |
| vol_avg_days | 20 |
| ma_period | 120 |

---

## 分组定义

| 组别 | 盘整振幅 | 说明 |
|------|----------|------|
| A组 | <5% | 超级横盘（极度收缩） |
| B组 | 5%~10% | 小幅波动 |
| C组 | 10%~15% | 中等波动 |
| D组 | 15%~20% | 较大波动 |
| E组 | >20% | 剧烈波动（盘整不充分） |

---

## 任务清单

### Task 1: 创建 `backtest_direction3.py`

**Files:**
- Create: `cy_quant/backtest_direction3.py`
- Test: `tests/cy_quant/test_backtest_direction3.py`

- [ ] **Step 1: 编写 `backtest_direction3.py`**

```python
"""
方向三回测：蓄力形态（盘整程度）
验证假设：突破前盘整越充分，爆发力越强
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
    breakthrough_date: str           # 突破日 YYYYMMDD
    breakthrough_price: float        # 突破日收盘价
    consolidation_amplitude: float   # 盘整振幅 (%)
    volatility_shrink_ratio: float   # 波动率收缩比
    final_gain: float                # 观察期末涨幅 (%)
    success: bool                    # 是否达标（观察期末涨幅 >= 成功阈值）


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

    def calculate_consolidation_amplitude(
        self, df: pd.DataFrame, start_idx: int, end_idx: int
    ) -> float:
        """
        计算盘整振幅
        (max(high) - min(low)) / avg_price * 100%
        """
        if start_idx >= end_idx:
            return 0.0

        period_df = df.iloc[start_idx:end_idx + 1]
        high_max = period_df['high'].max()
        low_min = period_df['low'].min()
        avg_price = period_df['close'].mean()

        if avg_price <= 0:
            return 0.0

        amplitude = (high_max - low_min) / avg_price * 100
        return round(amplitude, 2)

    def calculate_volatility_shrink_ratio(
        self, df: pd.DataFrame, consolidation_start: int, consolidation_end: int
    ) -> float:
        """
        计算波动率收缩比
        突破前波动率 / 盘整初期波动率
        """
        if consolidation_start >= consolidation_end:
            return 1.0

        # 盘整初期（前10天）波动率
        early_df = df.iloc[consolidation_start:consolidation_start + 10]
        early_volatility = early_df['close'].std() / early_df['close'].mean()

        # 突破前（后10天）波动率
        late_df = df.iloc[consolidation_end - 10:consolidation_end]
        late_volatility = late_df['close'].std() / late_df['close'].mean()

        if early_volatility <= 0:
            return 1.0

        return round(late_volatility / early_volatility, 2)

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

        # 计算MA
        df[f'ma{self.ma_period}'] = df['close'].rolling(
            window=self.ma_period, min_periods=self.ma_period
        ).mean()
        df[f'ma{self.ma_period}'] = df[f'ma{self.ma_period}'].fillna(df['close'])

        # 找突破日
        df['above_ma'] = df['close'] > df[f'ma{self.ma_period}']
        breakthrough_idx = None
        for i in range(self.ma_period, len(df)):
            if df.iloc[i]['above_ma'] and not df.iloc[i - 1]['above_ma']:
                breakthrough_idx = i
                break

        if breakthrough_idx is None:
            return None

        # 需要足够的盘整期数据
        if breakthrough_idx < self.consolidation_days:
            return None

        bt_date = str(df.iloc[breakthrough_idx]['trade_date'])
        bt_price = df.iloc[breakthrough_idx]['close']

        # 盘整期
        consolidation_start = breakthrough_idx - self.consolidation_days
        consolidation_end = breakthrough_idx

        # 盘整振幅
        amplitude = self.calculate_consolidation_amplitude(
            df, consolidation_start, consolidation_end
        )

        # 波动率收缩比
        shrink_ratio = self.calculate_volatility_shrink_ratio(
            df, consolidation_start, consolidation_end
        )

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
            consolidation_amplitude=amplitude,
            volatility_shrink_ratio=shrink_ratio,
            final_gain=round(final_gain, 2),
            success=final_gain >= self.success_threshold,
        )

    def analyze_all(self, stock_dir: str = None, prefixes=None) -> pd.DataFrame:
        """遍历目录下所有股票文件进行回测"""
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

        return pd.DataFrame(results)

    def classify_consolidation(self, amplitude: float) -> str:
        """按盘整振幅分类"""
        if amplitude < self.CONSOLIDATION_THRESHOLDS[0]:
            return self.CONSOLIDATION_LABELS[0]
        for threshold, label in zip(self.CONSOLIDATION_THRESHOLDS[1:], self.CONSOLIDATION_LABELS[1:]):
            if amplitude <= threshold:
                return label
        return self.CONSOLIDATION_LABELS[-1]

    def group_by_consolidation(self, result_df: pd.DataFrame) -> dict:
        """按盘整振幅分组统计"""
        if result_df.empty:
            return {}

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
        }).round(2)

        return grouped.sort_index()

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
    parser.add_argument('--observe-days', type=int, default=5, help='观察期天数')
    parser.add_argument('--consolidation-days', type=int, default=20, help='盘整期天数')
    parser.add_argument('--success-threshold', type=float, default=20.0, help='成功阈值（%%）')
    parser.add_argument('--stock-dir', type=str, default=None, help='股票数据目录')
    parser.add_argument('--prefixes', type=str, default='sh,sz', help='文件前缀，逗号分隔')
    args = parser.parse_args()

    prefixes = args.prefixes.split(',') if args.prefixes else ['sh', 'sz']

    analyzer = Direction3Analyzer(
        observe_days=args.observe_days,
        consolidation_days=args.consolidation_days,
        success_threshold=args.success_threshold,
    )

    print(f"开始回测（观察期={args.observe_days}天，盘整期={args.consolidation_days}天，成功阈值={args.success_threshold}%%）...")
    result_df = analyzer.analyze_all(stock_dir=args.stock_dir, prefixes=prefixes)

    if result_df.empty:
        print("未找到有效数据")
        return

    print(f"\n共分析 {len(result_df)} 只股票突破120日均线")

    # 分组统计
    grouped = analyzer.group_by_consolidation(result_df)
    print("\n分组统计结果：")
    print(grouped.to_string())

    analyzer.save_results(result_df)


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 运行测试验证代码可执行**

```bash
python -c "from cy_quant.backtest_direction3 import Direction3Analyzer; print('OK')"
```
Expected: OK

---

### Task 2: 创建单元测试

**Files:**
- Create: `tests/cy_quant/test_backtest_direction3.py`

- [ ] **Step 1: 编写测试文件**

```python
"""
方向三回测单元测试
"""
import pytest
import pandas as pd
from cy_quant.backtest_direction3 import Direction3Analyzer, BacktestResult


class TestDirection3Analyzer:
    """Direction3Analyzer 单元测试"""

    def test_classify_consolidation(self):
        """测试盘整振幅分类"""
        analyzer = Direction3Analyzer()
        assert analyzer.classify_consolidation(4.0) == 'A (<5%)'
        assert analyzer.classify_consolidation(5.0) == 'A (<5%)'
        assert analyzer.classify_consolidation(7.0) == 'B (5%~10%)'
        assert analyzer.classify_consolidation(12.0) == 'C (10%~15%)'
        assert analyzer.classify_consolidation(17.0) == 'D (15%~20%)'
        assert analyzer.classify_consolidation(25.0) == 'E (>20%)'

    def test_group_by_consolidation_empty(self):
        """测试空DataFrame分组"""
        analyzer = Direction3Analyzer()
        result = analyzer.group_by_consolidation(pd.DataFrame())
        assert result.empty
```

- [ ] **Step 2: 运行测试**

```bash
pytest tests/cy_quant/test_backtest_direction3.py -v
```

---

### Task 3: 运行完整回测

- [ ] **Step 1: 执行回测**

```bash
python -m cy_quant.backtest_direction3 --observe-days 5 --consolidation-days 20 --success-threshold 20.0
```

- [ ] **Step 2: 检查输出**

验证输出文件 `cy_quant/output/direction3_results_YYYYMMDD.csv` 是否生成，并检查分组统计结果。

---

### Task 4: 提交代码

- [ ] **Step 1: 提交**

```bash
git add cy_quant/backtest_direction3.py tests/cy_quant/test_backtest_direction3.py
git commit -m "feat: 实现方向三回测（蓄力形态）"
```

---

## 自检清单

- [ ] Spec覆盖：盘整振幅计算、波动率收缩比、分组统计
- [ ] 占位符扫描：无 TBD/TODO
- [ ] 类型一致性：BacktestResult 字段在各任务中一致
