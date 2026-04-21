# 方向四实施计划：相对强弱

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现方向四回测，验证「优先选择近期走势强于大盘的股票」的假设

**Architecture:** 独立文件 `backtest_direction4.py`，加载大盘指数数据，计算个股相对大盘的强弱差值并分组统计

**Tech Stack:** Python 3, pandas, numpy

---

## 文件结构

```
cy_quant/
├── backtest_retest.py           # 已存在：方向一
├── backtest_direction4.py       # 新建：方向四
└── tests/
    └── test_backtest_direction4.py  # 新建：单元测试
```

---

## 回测参数默认值

| 参数 | 默认值 |
|------|--------|
| observe_days | 5 |
| rs_period | 20 |
| success_threshold | 20.0 |
| ma_period | 120 |
| benchmark | 'hs300' |

---

## 分组定义

| 组别 | 相对强弱差值 | 说明 |
|------|-------------|------|
| A组 | >10% | 远超大盘 |
| B组 | 5%~10% | 强于大盘 |
| C组 | 0%~5% | 略微领先 |
| D组 | -5%~0% | 略微落后 |
| E组 | <-5% | 弱于大盘 |

---

## 大盘数据文件命名

| 基准 | 文件命名规则 |
|------|--------------|
| 沪深300 | `hs300_YYYYMMDD_YYYYMMDD.csv` |
| 上证指数 | `sseindex_YYYYMMDD_YYYYMMDD.csv` |

---

## 任务清单

### Task 1: 创建 `backtest_direction4.py`

**Files:**
- Create: `cy_quant/backtest_direction4.py`
- Test: `tests/cy_quant/test_backtest_direction4.py`

- [ ] **Step 1: 编写 `backtest_direction4.py`**

```python
"""
方向四回测：相对强弱
验证假设：优先选择近期走势强于大盘的股票
"""

import pandas as pd
import numpy as np
import os
import glob
from dataclasses import dataclass
from typing import Optional, Literal


@dataclass
class BacktestResult:
    """回测结果容器"""
    ts_code: str
    breakthrough_date: str       # 突破日 YYYYMMDD
    breakthrough_price: float    # 突破日收盘价
    stock_gain: float           # 个股观察期涨幅 (%)
    benchmark_gain: float       # 大盘同期涨幅 (%)
    rs_diff: float              # 相对强弱差值 (%)
    final_gain: float           # 观察期末涨幅 (%)
    success: bool               # 是否达标（观察期末涨幅 >= 成功阈值）


class Direction4Analyzer:
    """方向四回测分析器：相对强弱"""

    MA_PERIOD = 120
    RS_THRESHOLDS = [-5, 0, 5, 10]
    RS_LABELS = ['E (<-5%)', 'D (-5%~0%)', 'C (0%~5%)', 'B (5%~10%)', 'A (>10%)']

    def __init__(
        self,
        observe_days: int = 5,
        rs_period: int = 20,
        success_threshold: float = 20.0,
        ma_period: int = 120,
        benchmark: Literal['hs300', 'sse'] = 'hs300',
    ):
        self.observe_days = observe_days
        self.rs_period = rs_period
        self.success_threshold = success_threshold
        self.ma_period = ma_period
        self.benchmark = benchmark
        self.benchmark_df = None
        self._load_benchmark_data()

    def _load_benchmark_data(self):
        """加载大盘指数数据"""
        csv_dir = os.path.expanduser('~/abu/data/csv')

        if self.benchmark == 'hs300':
            patterns = [
                os.path.join(csv_dir, 'hs300*.csv'),
                os.path.join(csv_dir, 'hs300_*')
            ]
        else:
            patterns = [
                os.path.join(csv_dir, 'sseindex*.csv'),
                os.path.join(csv_dir, 'sseindex_*')
            ]

        for pattern in patterns:
            files = glob.glob(pattern)
            for f in files:
                try:
                    df = pd.read_csv(f, encoding='utf-8-sig')
                except Exception:
                    try:
                        df = pd.read_csv(f, encoding='gbk')
                    except Exception:
                        continue

                if 'date' in df.columns:
                    df = df.rename(columns={'date': 'trade_date'})
                if 'trade_date' not in df.columns or 'close' not in df.columns:
                    continue

                df = df.sort_values('trade_date').reset_index(drop=True)
                df['trade_date'] = df['trade_date'].astype(str)
                self.benchmark_df = df
                print(f"成功加载{self.benchmark}数据: {f}")
                return

        print(f"警告：未找到{self.benchmark}数据文件，相对强弱分析将不可用")

    def get_benchmark_gain(self, breakthrough_date: str, observe_days: int) -> float:
        """
        获取大盘同期涨幅
        """
        if self.benchmark_df is None or self.benchmark_df.empty:
            return 0.0

        df = self.benchmark_df.copy()
        df['trade_date'] = df['trade_date'].astype(str)

        # 找到突破日在大盘数据中的位置
        breakthrough_idx = None
        for idx, row in df.iterrows():
            if row['trade_date'] == breakthrough_date:
                breakthrough_idx = idx
                break

        if breakthrough_idx is None:
            return 0.0

        # 观察期终点
        end_idx = breakthrough_idx + observe_days - 1
        if end_idx >= len(df):
            end_idx = len(df) - 1

        if breakthrough_idx >= len(df) or end_idx <= breakthrough_idx:
            return 0.0

        start_price = df.iloc[breakthrough_idx]['close']
        end_price = df.iloc[end_idx]['close']

        if start_price <= 0:
            return 0.0

        return (end_price - start_price) / start_price * 100

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

        bt_date = str(df.iloc[breakthrough_idx]['trade_date'])
        bt_price = df.iloc[breakthrough_idx]['close']

        # 观察期数据
        end_idx = min(breakthrough_idx + self.observe_days, len(df) - 1)
        if end_idx <= breakthrough_idx:
            return None

        observe_df = df.iloc[breakthrough_idx:end_idx + 1].copy()
        if len(observe_df) < 2:
            return None

        # 个股涨幅
        final_price = observe_df.iloc[-1]['close']
        stock_gain = (final_price - bt_price) / bt_price * 100

        # 大盘涨幅
        benchmark_gain = self.get_benchmark_gain(bt_date, self.observe_days)

        # 相对强弱差值
        rs_diff = round(stock_gain - benchmark_gain, 2)

        return BacktestResult(
            ts_code=os.path.basename(filepath).split('_')[0],
            breakthrough_date=bt_date,
            breakthrough_price=round(bt_price, 2),
            stock_gain=round(stock_gain, 2),
            benchmark_gain=round(benchmark_gain, 2),
            rs_diff=rs_diff,
            final_gain=round(stock_gain, 2),
            success=stock_gain >= self.success_threshold,
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
                        'stock_gain': result.stock_gain,
                        'benchmark_gain': result.benchmark_gain,
                        'rs_diff': result.rs_diff,
                        'final_gain': result.final_gain,
                        'success': result.success,
                    })

        return pd.DataFrame(results)

    def classify_rs(self, rs_diff: float) -> str:
        """按相对强弱差值分类"""
        if rs_diff < self.RS_THRESHOLDS[0]:
            return self.RS_LABELS[0]
        for threshold, label in zip(self.RS_THRESHOLDS[1:], self.RS_LABELS[1:]):
            if rs_diff <= threshold:
                return label
        return self.RS_LABELS[-1]

    def group_by_rs(self, result_df: pd.DataFrame) -> dict:
        """按相对强弱分组统计"""
        if result_df.empty:
            return {}

        result_df = result_df.copy()
        result_df['group'] = result_df['rs_diff'].apply(self.classify_rs)

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
            filename = os.path.join('cy_quant', 'output', f'direction4_results_{today}.csv')
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"结果已保存至: {filename}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='方向四回测：相对强弱')
    parser.add_argument('--observe-days', type=int, default=5, help='观察期天数')
    parser.add_argument('--rs-period', type=int, default=20, help='相对强弱统计周期')
    parser.add_argument('--success-threshold', type=float, default=20.0, help='成功阈值（%%）')
    parser.add_argument('--benchmark', type=str, default='hs300', choices=['hs300', 'sse'], help='基准指数')
    parser.add_argument('--stock-dir', type=str, default=None, help='股票数据目录')
    parser.add_argument('--prefixes', type=str, default='sh,sz', help='文件前缀，逗号分隔')
    args = parser.parse_args()

    prefixes = args.prefixes.split(',') if args.prefixes else ['sh', 'sz']

    analyzer = Direction4Analyzer(
        observe_days=args.observe_days,
        rs_period=args.rs_period,
        success_threshold=args.success_threshold,
        benchmark=args.benchmark,
    )

    print(f"开始回测（观察期={args.observe_days}天，成功阈值={args.success_threshold}%%，基准={args.benchmark}）...")
    result_df = analyzer.analyze_all(stock_dir=args.stock_dir, prefixes=prefixes)

    if result_df.empty:
        print("未找到有效数据")
        return

    print(f"\n共分析 {len(result_df)} 只股票突破120日均线")

    # 分组统计
    grouped = analyzer.group_by_rs(result_df)
    print("\n分组统计结果：")
    print(grouped.to_string())

    analyzer.save_results(result_df)


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 运行测试验证代码可执行**

```bash
python -c "from cy_quant.backtest_direction4 import Direction4Analyzer; print('OK')"
```
Expected: OK

---

### Task 2: 创建单元测试

**Files:**
- Create: `tests/cy_quant/test_backtest_direction4.py`

- [ ] **Step 1: 编写测试文件**

```python
"""
方向四回测单元测试
"""
import pytest
import pandas as pd
from cy_quant.backtest_direction4 import Direction4Analyzer, BacktestResult


class TestDirection4Analyzer:
    """Direction4Analyzer 单元测试"""

    def test_classify_rs(self):
        """测试相对强弱分类"""
        analyzer = Direction4Analyzer()
        assert analyzer.classify_rs(15.0) == 'A (>10%)'
        assert analyzer.classify_rs(10.0) == 'A (>10%)'
        assert analyzer.classify_rs(7.0) == 'B (5%~10%)'
        assert analyzer.classify_rs(3.0) == 'C (0%~5%)'
        assert analyzer.classify_rs(0.0) == 'C (0%~5%)'
        assert analyzer.classify_rs(-3.0) == 'D (-5%~0%)'
        assert analyzer.classify_rs(-10.0) == 'E (<-5%)'

    def test_group_by_rs_empty(self):
        """测试空DataFrame分组"""
        analyzer = Direction4Analyzer()
        result = analyzer.group_by_rs(pd.DataFrame())
        assert result.empty

    def test_benchmark_default(self):
        """测试默认基准是hs300"""
        analyzer = Direction4Analyzer()
        assert analyzer.benchmark == 'hs300'
```

- [ ] **Step 2: 运行测试**

```bash
pytest tests/cy_quant/test_backtest_direction4.py -v
```

---

### Task 3: 运行完整回测

- [ ] **Step 1: 执行回测**

```bash
python -m cy_quant.backtest_direction4 --observe-days 5 --success-threshold 20.0 --benchmark hs300
```

- [ ] **Step 2: 检查输出**

验证输出文件 `cy_quant/output/direction4_results_YYYYMMDD.csv` 是否生成，并检查分组统计结果。

---

### Task 4: 提交代码

- [ ] **Step 1: 提交**

```bash
git add cy_quant/backtest_direction4.py tests/cy_quant/test_backtest_direction4.py
git commit -m "feat: 实现方向四回测（相对强弱）"
```

---

## 自检清单

- [ ] Spec覆盖：相对强弱差值计算、大盘数据加载、分组统计
- [ ] 占位符扫描：无 TBD/TODO
- [ ] 类型一致性：BacktestResult 字段在各任务中一致
- [ ] 大盘数据文件命名：hs300_*.csv, sseindex_*.csv
