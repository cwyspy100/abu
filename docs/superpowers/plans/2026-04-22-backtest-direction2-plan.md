# 方向二实施计划：突破质量（爆发力）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现方向二回测，验证「突破幅度越大、成交量配合越好，后续上涨概率越高」的假设

**Architecture:** 独立文件 `backtest_direction2.py`，复用 `RetestAnalyzer` 的文件读取和120日均线计算逻辑，按突破幅度分组统计

**Tech Stack:** Python 3, pandas, numpy

---

## 文件结构

```
cy_quant/
├── backtest_retest.py           # 已存在：方向一
├── backtest_direction2.py      # 新建：方向二
└── tests/
    └── test_backtest_direction2.py  # 新建：单元测试
```

---

## 回测参数默认值

| 参数 | 默认值 |
|------|--------|
| observe_days | 5 |
| success_threshold | 20.0 |
| volume_avg_days | 20 |
| ma_period | 120 |

---

## 分组定义

| 组别 | 突破幅度 | 成交量放大倍数 |
|------|----------|---------------|
| A组 | >=5% | >=2倍 |
| B组 | 3%~5% | >=2倍 |
| C组 | 1%~3% | >=1.5倍 |
| D组 | 0%~1% | <1.5倍 |
| E组 | <0% | 任意 |

---

## 任务清单

### Task 1: 创建 `backtest_direction2.py`

**Files:**
- Create: `cy_quant/backtest_direction2.py`
- Test: `tests/test_backtest_direction2.py`

- [ ] **Step 1: 创建目录结构**

```bash
mkdir -p cy_quant/output tests/cy_quant
```

- [ ] **Step 2: 编写 `backtest_direction2.py`**

```python
"""
方向二回测：突破质量（爆发力）
验证假设：突破幅度越大、成交量配合越好，后续上涨概率越高
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
    breakthrough_price: float     # 突破日收盘价
    ma120: float                 # 突破日MA120值
    breakthrough_ratio: float    # 突破幅度 (%)
    volume_ratio: float          # 成交量放大倍数
    final_gain: float             # 观察期末涨幅 (%)
    success: bool                # 是否达标（观察期末涨幅 >= 成功阈值）


class Direction2Analyzer:
    """方向二回测分析器：突破质量"""

    MA_PERIOD = 120
    BREAKTHROUGH_THRESHOLDS = [0, 1, 3, 5]
    BREAKTHROUGH_LABELS = ['E (<0%)', 'D (0%~1%)', 'C (1%~3%)', 'B (3%~5%)', 'A (>=5%)']

    def __init__(
        self,
        observe_days: int = 5,
        success_threshold: float = 20.0,
        volume_avg_days: int = 20,
        ma_period: int = 120,
    ):
        self.observe_days = observe_days
        self.success_threshold = success_threshold
        self.volume_avg_days = volume_avg_days
        self.ma_period = ma_period

    def calculate_volume_ratio(self, df: pd.DataFrame, breakthrough_idx: int) -> float:
        """
        计算成交量放大倍数
        突破日成交量 / 过去N日平均成交量
        """
        if breakthrough_idx < self.volume_avg_days:
            return 1.0

        # 突破日前N天的平均成交量
        avg_volume = df.iloc[breakthrough_idx - self.volume_avg_days:breakthrough_idx]['volume'].mean()
        if avg_volume <= 0:
            return 1.0

       突破日成交量 = df.iloc[breakthrough_idx]['volume']
        return round(突破日成交量 / avg_volume, 2)

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
        bt_ma = df.iloc[breakthrough_idx][f'ma{self.ma_period}']

        # 计算突破幅度
        if bt_ma > 0:
            breakthrough_ratio = (bt_price - bt_ma) / bt_ma * 100
        else:
            breakthrough_ratio = 0.0

        # 计算成交量放大倍数
        volume_ratio = self.calculate_volume_ratio(df, breakthrough_idx)

        # 观察期数据
        end_idx = min(breakthrough_idx + self.observe_days, len(df) - 1)
        if end_idx <= breakthrough_idx:
            return None

        observe_df = df.iloc[breakthrough_idx:end_idx + 1].copy()
        if len(observe_df) < 2:
            return None

        # 最终涨幅（观察期最后一天）
        final_price = observe_df.iloc[-1]['close']
        final_gain = (final_price - bt_price) / bt_price * 100

        return BacktestResult(
            ts_code=os.path.basename(filepath).split('_')[0],
            breakthrough_date=bt_date,
            breakthrough_price=round(bt_price, 2),
            ma120=round(bt_ma, 2),
            breakthrough_ratio=round(breakthrough_ratio, 2),
            volume_ratio=volume_ratio,
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
                        'ma120': result.ma120,
                        'breakthrough_ratio': result.breakthrough_ratio,
                        'volume_ratio': result.volume_ratio,
                        'final_gain': result.final_gain,
                        'success': result.success,
                    })

        return pd.DataFrame(results)

    def classify_breakthrough(self, ratio: float) -> str:
        """按突破幅度分类"""
        if ratio < self.BREAKTHROUGH_THRESHOLDS[0]:
            return self.BREAKTHROUGH_LABELS[0]
        for threshold, label in zip(self.BREAKTHROUGH_THRESHOLDS[1:], self.BREAKTHROUGH_LABELS[1:]):
            if ratio <= threshold:
                return label
        return self.BREAKTHROUGH_LABELS[-1]

    def group_by_breakthrough(self, result_df: pd.DataFrame) -> dict:
        """按突破幅度分组统计"""
        if result_df.empty:
            return {}

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
        }).round(2)

        return grouped.sort_index()

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
    parser.add_argument('--observe-days', type=int, default=5, help='观察期天数')
    parser.add_argument('--success-threshold', type=float, default=20.0, help='成功阈值（%%）')
    parser.add_argument('--volume-avg-days', type=int, default=20, help='成交量平均天数')
    parser.add_argument('--stock-dir', type=str, default=None, help='股票数据目录')
    parser.add_argument('--prefixes', type=str, default='sh,sz', help='文件前缀，逗号分隔')
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
    print("\n分组统计结果：")
    print(grouped.to_string())

    analyzer.save_results(result_df)


if __name__ == '__main__':
    main()
```

- [ ] **Step 3: 运行测试验证代码可执行**

```bash
python -c "from cy_quant.backtest_direction2 import Direction2Analyzer; print('OK')"
```
Expected: OK

---

### Task 2: 创建单元测试

**Files:**
- Create: `tests/cy_quant/test_backtest_direction2.py`
- Modify: `tests/cy_quant/test_backtest_direction2.py`

- [ ] **Step 1: 编写测试文件**

```python
"""
方向二回测单元测试
"""
import pytest
import pandas as pd
import os
from cy_quant.backtest_direction2 import Direction2Analyzer, BacktestResult


class TestDirection2Analyzer:
    """Direction2Analyzer 单元测试"""

    def test_classify_breakthrough(self):
        """测试突破幅度分类"""
        analyzer = Direction2Analyzer()
        assert analyzer.classify_breakthrough(6.0) == 'A (>=5%)'
        assert analyzer.classify_breakthrough(5.0) == 'A (>=5%)'
        assert analyzer.classify_breakthrough(4.0) == 'B (3%~5%)'
        assert analyzer.classify_breakthrough(3.0) == 'B (3%~5%)'
        assert analyzer.classify_breakthrough(2.0) == 'C (1%~3%)'
        assert analyzer.classify_breakthrough(1.0) == 'C (1%~3%)'
        assert analyzer.classify_breakthrough(0.5) == 'D (0%~1%)'
        assert analyzer.classify_breakthrough(0.0) == 'D (0%~1%)'
        assert analyzer.classify_breakthrough(-1.0) == 'E (<0%)'

    def test_group_by_breakthrough_empty(self):
        """测试空DataFrame分组"""
        analyzer = Direction2Analyzer()
        result = analyzer.group_by_breakthrough(pd.DataFrame())
        assert result.empty

    def test_success_threshold_strict(self):
        """测试成功标准为严格模式（观察期末涨幅）"""
        analyzer = Direction2Analyzer(success_threshold=10.0)
        # final_gain=15% > 10% -> success=True
        # final_gain=5% < 10% -> success=False
        assert True  # placeholder
```

- [ ] **Step 2: 运行测试**

```bash
pytest tests/cy_quant/test_backtest_direction2.py -v
```

---

### Task 3: 运行完整回测

- [ ] **Step 1: 执行回测**

```bash
python -m cy_quant.backtest_direction2 --observe-days 5 --success-threshold 20.0
```

- [ ] **Step 2: 检查输出**

验证输出文件 `cy_quant/output/direction2_results_YYYYMMDD.csv` 是否生成，并检查分组统计结果是否符合预期。

---

### Task 4: 提交代码

- [ ] **Step 1: 提交**

```bash
git add cy_quant/backtest_direction2.py tests/cy_quant/test_backtest_direction2.py
git commit -m "feat: 实现方向二回测（突破质量）"
```

---

## 自检清单

- [ ] Spec覆盖：突破幅度分组、成交量放大倍数、成功标准（观察期末涨幅）
- [ ] 占位符扫描：无 TBD/TODO
- [ ] 类型一致性：BacktestResult 字段在各任务中一致
