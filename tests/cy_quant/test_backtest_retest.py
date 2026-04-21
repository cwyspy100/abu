"""
方向一回测单元测试
"""

import pytest
import pandas as pd
import numpy as np
import os
import tempfile
from datetime import datetime, timedelta
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
        # 构造恒定价格数据，始终低于均线（close=10, ma从12逐步下降到10）
        base_close = 10.0
        rows = []
        for i in range(150):
            rows.append({
                'trade_date': f'2024{(i // 30) + 1:02d}{(i % 30) + 1:02d}',
                'open': base_close,
                'high': base_close,
                'low': base_close,
                'close': base_close,
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
        base = datetime(2024, 1, 1)
        # 前149天平缓，120天后形成均线
        for i in range(149):
            close = 10.0
            trade_date = (base + timedelta(days=i)).strftime('%Y%m%d')
            rows.append({
                'trade_date': trade_date,
                'open': close,
                'high': close + 0.1,
                'low': close - 0.1,
                'close': close,
                'volume': 1000000,
            })
        # 第150天突破，收盘11元（超过均线10元）
        rows.append({
            'trade_date': (base + timedelta(days=149)).strftime('%Y%m%d'),
            'open': 10.5,
            'high': 11.0,
            'low': 10.3,
            'close': 11.0,
            'volume': 2000000,
        })
        # 之后10天小幅回调，第15天涨到13元
        for i in range(10):
            price = 11.0 - 0.2 * i  # 逐步下跌
            trade_date = (base + timedelta(days=150 + i)).strftime('%Y%m%d')
            rows.append({
                'trade_date': trade_date,
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
        assert 0 < result.max_drawdown < 50  # 有回调，50%是合理上限
        assert isinstance(result.success, bool)
        assert isinstance(result.final_gain, float)


def test_group_by_drawdown():
    """分组统计应正确分类"""
    df = pd.DataFrame([
        {'ts_code': 'A', 'max_drawdown': 0.0,  'max_gain': 10.0, 'success': False, 'final_gain': 8.0},
        {'ts_code': 'B2', 'max_drawdown': 2.0, 'max_gain': 15.0, 'success': False, 'final_gain': 12.0},
        {'ts_code': 'B3', 'max_drawdown': 3.0, 'max_gain': 18.0, 'success': False, 'final_gain': 15.0},  # boundary: exactly 3%
        {'ts_code': 'C', 'max_drawdown': 4.0,  'max_gain': 25.0, 'success': True,  'final_gain': 22.0},
        {'ts_code': 'C5', 'max_drawdown': 5.0,  'max_gain': 20.0, 'success': True,  'final_gain': 18.0},  # boundary: exactly 5%
        {'ts_code': 'D8', 'max_drawdown': 8.0,  'max_gain': 30.0, 'success': True,  'final_gain': 28.0},
        {'ts_code': 'D10', 'max_drawdown': 10.0, 'max_gain': 22.0, 'success': True, 'final_gain': 20.0},  # boundary: exactly 10%
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
    assert grouped.loc['B (0%~3%)', 'count'] >= 2  # B2 + B3
    assert grouped.loc['C (3%~5%)', 'count'] >= 2  # C + C5
    assert grouped.loc['D (5%~10%)', 'count'] >= 2  # D8 + D10

    # Verify boundary values are classified correctly
    assert analyzer.classify_drawdown(3.0) == 'B (0%~3%)', f"B3 (3.0%) should be in B, got {analyzer.classify_drawdown(3.0)}"
    assert analyzer.classify_drawdown(5.0) == 'C (3%~5%)', f"C5 (5.0%) should be in C, got {analyzer.classify_drawdown(5.0)}"
    assert analyzer.classify_drawdown(10.0) == 'D (5%~10%)', f"D10 (10.0%) should be in D, got {analyzer.classify_drawdown(10.0)}"


def test_empty_df():
    """空 DataFrame 应返回空字典"""
    analyzer = RetestAnalyzer()
    grouped = analyzer.group_by_drawdown(pd.DataFrame())
    assert grouped == {}