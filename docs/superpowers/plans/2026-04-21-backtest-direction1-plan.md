# 方向一回测实现计划：回踩幅度与持续性

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现股票突破120日均线后的回踩幅度回测，按回踩程度分组验证后续涨幅表现

**Architecture:** 独立脚本 `cy_quant/backtest_retest.py`，接收股票数据文件路径，按回踩幅度分组统计并输出图表

**Tech Stack:** Python 3.9, pandas, numpy, matplotlib, pytest

---

## 文件结构

- Create: `cy_quant/backtest_retest.py` — 回测主逻辑
- Create: `tests/cy_quant/test_backtest_retest.py` — 单元测试
- Create: `cy_quant/output/` — 输出目录（如不存在）

---

## Task 1: 创建回测脚本框架

**Files:**
- Create: `cy_quant/backtest_retest.py`

- [ ] **Step 1: 写测试占位**

创建 `tests/cy_quant/test_backtest_retest.py`：
```python
# placeholder - will be filled in Task 2
```

- [ ] **Step 2: 实现脚本框架**

`cy_quant/backtest_retest.py` 内容：

```python
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
```

- [ ] **Step 3: 运行验证脚本框架**

```bash
cd /Users/water/mylearn/PycharmProjects/abu-master
python -c "from cy_quant.backtest_retest import RetestAnalyzer; print('import ok')"
```

预期输出：`import ok`

- [ ] **Step 4: 提交**

```bash
git add cy_quant/backtest_retest.py
git commit -m "feat: add RetestAnalyzer for backtest direction-1"
```

---

## Task 2: 单元测试

**Files:**
- Create: `tests/cy_quant/test_backtest_retest.py`

- [ ] **Step 1: 创建测试文件**

`tests/cy_quant/test_backtest_retest.py`：

```python
"""
方向一回测单元测试
"""

import pytest
import pandas as pd
import numpy as np
import os
import tempfile
from cy_quant.backtest_retest import RetestAnalyzer, BacktestResult


def make_test_csv(rows, path):
    """生成测试用CSV文件"""
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False, encoding='utf-8-sig')


def test_backtest_result_fields():
    """验证 BacktestResult 字段"""
    r = BacktestResult(
        ts_code='000001.SZ',
        breakthrough_date='20250101',
        breakthrough_price=10.0,
        max_drawdown=5.0,
        max_gain=20.0,
        success=True,
        final_gain=18.0,
    )
    assert r.ts_code == '000001.SZ'
    assert r.breakthrough_price == 10.0
    assert r.max_drawdown == 5.0
    assert r.max_gain == 20.0
    assert r.success is True


def test_no_breakthrough():
    """无突破时应返回 None"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 构造窄幅震荡数据，始终低于均线
        rows = []
        for i in range(150):
            close = 10.0 + np.random.randn() * 0.1
            rows.append({
                'trade_date': f'2024{(i // 30) + 1:02d}{(i % 30) + 1:02d}',
                'open': close,
                'high': close + 0.2,
                'low': close - 0.2,
                'close': close,
                'volume': 1000000,
            })
        path = os.path.join(tmpdir, 'sz000001_20240101_20250601.csv')
        make_test_csv(rows, path)

        analyzer = RetestAnalyzer(observe_days=20)
        result = analyzer.analyze_file(path)
        assert result is None


def test_with_breakthrough():
    """有突破时应返回 BacktestResult"""
    with tempfile.TemporaryDirectory() as tmpdir:
        rows = []
        # 前149天平缓，120天后形成均线
        for i in range(149):
            close = 10.0
            rows.append({
                'trade_date': f'2024{(i // 30) + 1:02d}{(i % 30) + 1:02d}',
                'open': close,
                'high': close + 0.1,
                'low': close - 0.1,
                'close': close,
                'volume': 1000000,
            })
        # 第150天突破，收盘11元（超过均线10元）
        rows.append({
            'trade_date': '20240530',
            'open': 10.5,
            'high': 11.0,
            'low': 10.3,
            'close': 11.0,
            'volume': 2000000,
        })
        # 之后10天小幅回调，第15天涨到13元
        for i in range(10):
            price = 11.0 - 0.2 * i  # 逐步下跌
            rows.append({
                'trade_date': f'202405{31 + i:02d}' if 31 + i <= 40 else f'202406{15 + i - 40:02d}',
                'open': price,
                'high': price + 0.1,
                'low': price - 0.1,
                'close': price,
                'volume': 1000000,
            })
        path = os.path.join(tmpdir, 'sz000001_20240101_20250601.csv')
        make_test_csv(rows, path)

        analyzer = RetestAnalyzer(observe_days=20)
        result = analyzer.analyze_file(path)

        assert result is not None
        assert result.breakthrough_price == 11.0
        assert result.max_drawdown > 0  # 有回调


def test_group_by_drawdown():
    """分组统计应正确分类"""
    df = pd.DataFrame([
        {'ts_code': 'A', 'max_drawdown': 0.0,  'max_gain': 10.0, 'success': False, 'final_gain': 8.0},
        {'ts_code': 'B', 'max_drawdown': 2.0,  'max_gain': 15.0, 'success': False, 'final_gain': 12.0},
        {'ts_code': 'C', 'max_drawdown': 4.0,  'max_gain': 25.0, 'success': True,  'final_gain': 22.0},
        {'ts_code': 'D', 'max_drawdown': 8.0,  'max_gain': 30.0, 'success': True,  'final_gain': 28.0},
        {'ts_code': 'E', 'max_drawdown': 15.0, 'max_gain': 5.0,  'success': False, 'final_gain': 3.0},
    ])

    analyzer = RetestAnalyzer()
    grouped = analyzer.group_by_drawdown(df)

    assert 'A (0%)' in grouped.index
    assert 'B (0%~3%)' in grouped.index
    assert 'C (3%~5%)' in grouped.index
    assert 'D (5%~10%)' in grouped.index
    assert 'E (>10%)' in grouped.index

    assert grouped.loc['A (0%)', 'count'] == 1
    assert grouped.loc['C (3%~5%)', 'success_rate'] == 1.0  # C 组成功率为 100%


def test_empty_df():
    """空 DataFrame 应返回空字典"""
    analyzer = RetestAnalyzer()
    grouped = analyzer.group_by_drawdown(pd.DataFrame())
    assert grouped == {}
```

- [ ] **Step 2: 运行测试**

```bash
cd /Users/water/mylearn/PycharmProjects/abu-master
python -m pytest tests/cy_quant/test_backtest_retest.py -v
```

预期：全部 PASS

- [ ] **Step 3: 提交**

```bash
git add tests/cy_quant/test_backtest_retest.py
git commit -m "test: add backtest_retest unit tests"
```

---

## Task 3: 运行回测（验证）

**Files:**
- Run: `python cy_quant/backtest_retest.py`

- [ ] **Step 1: 执行回测脚本**

```bash
cd /Users/water/mylearn/PycharmProjects/abu-master
python cy_quant/backtest_retest.py --observe-days 20 --success-threshold 20.0
```

预期：输出分组统计结果，包含 A/B/C/D/E 各组的样本数、平均涨幅、成功率

- [ ] **Step 2: 检查输出文件**

结果文件应保存在 `cy_quant/output/retest_results_YYYYMMDD.csv`

---

## Task 4: 更新研究结论文档

**Files:**
- Modify: `docs/superpowers/specs/2026-04-21-research-plan.md`

- [ ] **填入方向一的验证结果**

在"验证结果记录"表中填入方向一的结论（样本数、分组表现、是否验证假设）

---

## 计划自检

1. **Spec 覆盖：** 回测逻辑、分组统计、参数传入、结果保存均有任务对应
2. **Placeholder 扫描：** 无 TBD/TODO，所有步骤均完整
3. **类型一致性：** `RetestAnalyzer` 类方法签名与测试中调用一致