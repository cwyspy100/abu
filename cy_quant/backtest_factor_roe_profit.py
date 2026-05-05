"""
因子 + 动量组合回测：测试 A4(创新高) x ROE 的交叉分组

核心问题：创新高条件（技术面）在不同财务质量下表现是否不同？

方法：
1. 读取突破事件（来自livermore_results）
2. 计算A4条件：突破当天是否创20日新高
3. 匹配财务数据（ROE）
4. 交叉分组：技术面(A4) x 基本面(ROE五分位)
"""

import pandas as pd
import numpy as np
import os
import glob
from dataclasses import dataclass
from typing import Optional, Dict, List
from datetime import datetime


def normalize_ts_code(ts_code: str) -> str:
    """标准化股票代码"""
    ts_code = str(ts_code).strip()
    if '.' in ts_code:
        return ts_code
    if ts_code.startswith('sh'):
        return f"{ts_code[2:]}.SH"
    elif ts_code.startswith('sz'):
        return f"{ts_code[2:]}.SZ"
    return ts_code


def ts_code_to_prefix(ts_code: str) -> tuple:
    """转换为文件前缀：603035.SH -> (sh603035, 600036.SH)"""
    ts_code = normalize_ts_code(ts_code)
    code, market = ts_code.split('.')
    if market == 'SH':
        prefix = f"sh{code}"
    else:
        prefix = f"sz{code}"
    return prefix, ts_code


def quintile_group(series: pd.Series, q: int = 5) -> pd.Series:
    """按分位数分组"""
    try:
        return pd.qcut(series, q=q, labels=False, duplicates='drop')
    except Exception:
        return pd.Series(np.nan, index=series.index)


class A4RoeFactorAnalyzer:
    """A4(创新高) x ROE 交叉分组分析器"""

    MA_PERIOD = 120
    NH_LOOKBACK = 20

    def __init__(self, observe_days: int = 10, success_threshold: float = 20.0):
        self.observe_days = observe_days
        self.success_threshold = success_threshold

    def load_financial_data(self, stock_dir: str = None) -> pd.DataFrame:
        """加载所有股票的财务数据"""
        if stock_dir is None:
            stock_dir = os.path.expanduser('~/abu/tushare/finance')

        all_finance = []
        for f in glob.glob(os.path.join(stock_dir, '*_finance.csv')):
            try:
                df = pd.read_csv(f, encoding='utf-8-sig')
                if 'ts_code' in df.columns and 'end_date' in df.columns:
                    df['ts_code'] = df['ts_code'].astype(str).apply(normalize_ts_code)
                    df['end_date'] = df['end_date'].astype(str)
                    all_finance.append(df)
            except Exception:
                continue

        if not all_finance:
            return pd.DataFrame()

        result = pd.concat(all_finance, ignore_index=True)
        cols = ['ts_code', 'end_date', 'roe', 'netprofit_yoy']
        cols = [c for c in cols if c in result.columns]
        return result[cols].copy()

    def match_financial_data(
        self,
        finance_df: pd.DataFrame,
        ts_code: str,
        breakthrough_date: str
    ) -> tuple:
        """匹配最近的财务数据（突破日之前的最新季度报告）"""
        if finance_df.empty:
            return (np.nan, np.nan)

        ts_code_norm = normalize_ts_code(ts_code)
        stock_fin = finance_df[finance_df['ts_code'] == ts_code_norm].copy()
        if stock_fin.empty:
            return (np.nan, np.nan)

        try:
            bt_date = datetime.strptime(str(breakthrough_date), '%Y%m%d')
        except Exception:
            try:
                bt_date = datetime.strptime(str(breakthrough_date), '%Y-%m-%d')
            except Exception:
                return (np.nan, np.nan)

        stock_fin['end_date_dt'] = pd.to_datetime(stock_fin['end_date'], format='%Y%m%d', errors='coerce')
        stock_fin = stock_fin[stock_fin['end_date_dt'] < bt_date]

        if stock_fin.empty:
            return (np.nan, np.nan)

        stock_fin = stock_fin.sort_values('end_date_dt', ascending=False)
        latest = stock_fin.iloc[0]
        return (latest.get('roe', np.nan), latest.get('netprofit_yoy', np.nan))

    def check_a4_new_high(self, kline_dir: str, ts_code: str, breakthrough_date: str) -> bool:
        """
        检查是否A4（创新高）：突破当天创20日新高
        """
        prefix, ts_norm = ts_code_to_prefix(ts_code)

        # 查找K线数据文件（可能在astock/子目录下）
        pattern1 = os.path.join(kline_dir, f'{prefix}*')
        pattern2 = os.path.join(kline_dir, 'astock', f'{prefix}*')

        files = glob.glob(pattern1)
        if not files:
            files = glob.glob(pattern2)
        if not files:
            return False

        filepath = files[0]
        try:
            df = pd.read_csv(filepath, encoding='utf-8-sig')
        except Exception:
            try:
                df = pd.read_csv(filepath, encoding='gbk')
            except Exception:
                return False

        if df.empty or 'high' not in df.columns:
            return False

        # 列名可能是 date 或 trade_date
        date_col = 'trade_date' if 'trade_date' in df.columns else 'date'
        if date_col not in df.columns:
            return False

        df = df.copy()
        df = df.rename(columns={date_col: 'trade_date'})
        df = df.sort_values('trade_date').reset_index(drop=True)
        df['trade_date'] = df['trade_date'].astype(str)

        # 突破日期直接转字符串比较（都是YYYYMMDD格式）
        bt_date_str = str(int(breakthrough_date))

        # 找突破日的index
        bt_rows = df[df['trade_date'] == bt_date_str]
        if bt_rows.empty:
            return False
        bt_idx = bt_rows.index[0]

        # 需要前NH_LOOKBACK天数据
        if bt_idx < self.NH_LOOKBACK:
            return False

        # 当天最高价
        today_high = df.iloc[bt_idx]['high']
        # 过去NH_LOOKBACK天的最高价
        lookback_high = df.iloc[bt_idx - self.NH_LOOKBACK:bt_idx]['high'].max()

        return today_high >= lookback_high

    def analyze(
        self,
        breakthrough_file: str,
        kline_dir: str = None,
        finance_dir: str = None,
        compute_a4: bool = True,
    ) -> pd.DataFrame:
        """执行因子回测"""
        if kline_dir is None:
            kline_dir = os.path.join(os.path.expanduser('~'), 'abu', 'data', 'csv', 'astock')
        if finance_dir is None:
            finance_dir = os.path.expanduser('~/abu/tushare/finance')

        # 加载突破数据
        bt_df = pd.read_csv(breakthrough_file, encoding='utf-8-sig')
        if bt_df.empty or 'ts_code' not in bt_df.columns:
            print(f"未找到突破数据: {breakthrough_file}")
            return pd.DataFrame()
        bt_df = bt_df[['ts_code', 'breakthrough_date', 'final_gain', 'success']].copy()
        print(f"加载 {len(bt_df)} 条突破事件")

        # 加载财务数据
        finance_df = self.load_financial_data(finance_dir)
        if finance_df.empty:
            print("未找到财务数据")
            return pd.DataFrame()
        print(f"加载 {len(finance_df)} 条财务记录")

        results = []
        for i, row in bt_df.iterrows():
            ts_code = str(row['ts_code'])
            bt_date = str(row['breakthrough_date'])
            roe, netprofit_yoy = self.match_financial_data(finance_df, ts_code, bt_date)

            new_high = False
            if compute_a4:
                new_high = self.check_a4_new_high(kline_dir, ts_code, bt_date)

            results.append({
                'ts_code': ts_code,
                'breakthrough_date': bt_date,
                'roe': roe,
                'netprofit_yoy': netprofit_yoy,
                'new_high': new_high,
                'final_gain': row['final_gain'],
                'success': row['success'],
            })

            if (i + 1) % 1000 == 0:
                print(f"  已处理 {i+1}/{len(bt_df)}...")

        result_df = pd.DataFrame(results)
        return result_df

    def group_statistics(self, result_df: pd.DataFrame) -> dict:
        """分组统计"""
        if result_df.empty:
            return {}

        df = result_df.copy()
        valid = df.dropna(subset=['roe'])
        print(f"\n总样本: {len(df)}, 有效财务数据: {len(valid)}")

        # ROE五分位
        valid = valid.copy()
        valid['roe_q'] = quintile_group(valid['roe'], q=5)

        # 1. A4 vs 非A4 总体对比
        print("\n" + "=" * 60)
        print("A4(创新高) 总体效果:")
        a4_df = valid[valid['new_high'] == True]
        no_a4_df = valid[valid['new_high'] == False]
        print(f"  A4组:   n={len(a4_df):>5}, 成功率={a4_df['success'].mean():.2%}, 平均涨幅={a4_df['final_gain'].mean():.2f}%")
        print(f"  非A4组: n={len(no_a4_df):>5}, 成功率={no_a4_df['success'].mean():.2%}, 平均涨幅={no_a4_df['final_gain'].mean():.2f}%")

        # 2. A4 x ROE 交叉分组
        print("\n" + "=" * 60)
        print("A4 x ROE五分位 交叉分组 (成功率):")
        cross = valid.pivot_table(
            values='success',
            index='new_high',
            columns='roe_q',
            aggfunc=['mean', 'count'],
        ).round(4)
        print(cross.to_string())

        print("\n" + "=" * 60)
        print("A4 x ROE五分位 交叉分组 (平均涨幅):")
        cross_gain = valid.pivot_table(
            values='final_gain',
            index='new_high',
            columns='roe_q',
            aggfunc='mean',
        ).round(2)
        print(cross_gain.to_string())

        # 3. 关键组合对比
        print("\n" + "=" * 60)
        print("关键组合对比:")

        high_roe = valid['roe_q'] >= 4
        low_roe = valid['roe_q'] <= 0

        combos = {
            'A4 + 高ROE': valid[(valid['new_high']) & high_roe],
            'A4 + 低ROE': valid[(valid['new_high']) & low_roe],
            '非A4 + 高ROE': valid[(~valid['new_high']) & high_roe],
            '非A4 + 低ROE': valid[(~valid['new_high']) & low_roe],
        }

        print(f"{'组合':<20} {'样本数':>8} {'成功率':>12} {'平均涨幅':>12}")
        print("-" * 60)
        for name, grp in combos.items():
            if len(grp) > 0:
                print(f"{name:<20} {len(grp):>8} {grp['success'].mean():>11.2%} {grp['final_gain'].mean():>11.2f}%")

        # 4. ROE分组内，A4的增量
        print("\n" + "=" * 60)
        print("ROE分组内，A4的增量效果:")
        print(f"{'ROE组':<10} {'非A4成功率':>12} {'A4成功率':>12} {'A4增量':>10}")
        print("-" * 50)
        for q in sorted(valid['roe_q'].dropna().unique()):
            no_a4_q = valid[(valid['roe_q'] == q) & (~valid['new_high'])]
            a4_q = valid[(valid['roe_q'] == q) & (valid['new_high'])]
            if len(no_a4_q) > 0 and len(a4_q) > 0:
                delta = a4_q['success'].mean() - no_a4_q['success'].mean()
                print(f"Q{int(q):<9} {no_a4_q['success'].mean():>11.2%} {a4_q['success'].mean():>11.2%} {delta:>+9.2%}")

        return {}

    def save_results(self, result_df: pd.DataFrame, filename: str = None):
        """保存结果"""
        if result_df.empty:
            return
        if filename is None:
            today = datetime.now().strftime('%Y%m%d')
            filename = os.path.join('cy_quant', 'output', f'a4_roe_results_{today}.csv')
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"\n数据已保存至: {filename}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='A4(创新高) x ROE 因子组合回测')
    parser.add_argument('--breakthrough-file', type=str,
                        default='cy_quant/output/livermore_results_20260422.csv')
    parser.add_argument('--kline-dir', type=str,
                        default='~/abu/data/csv')
    parser.add_argument('--finance-dir', type=str,
                        default='~/abu/tushare/finance')
    parser.add_argument('--no-a4', action='store_true',
                        help='跳过A4计算（使用已有结果）')
    parser.add_argument('--use-cached', type=str,
                        default=None, help='使用已缓存的A4+ROE结果CSV')
    args = parser.parse_args()

    analyzer = A4RoeFactorAnalyzer()

    breakthrough_file = os.path.expanduser(args.breakthrough_file)
    kline_dir = os.path.expanduser(args.kline_dir)
    finance_dir = os.path.expanduser(args.finance_dir)

    print(f"突破事件文件: {breakthrough_file}")
    print(f"K线数据目录: {kline_dir}")
    print(f"财务数据目录: {finance_dir}")

    if args.use_cached:
        result_df = pd.read_csv(args.use_cached, encoding='utf-8-sig')
        print(f"从缓存加载: {args.use_cached}")
    else:
        result_df = analyzer.analyze(
            breakthrough_file=breakthrough_file,
            kline_dir=kline_dir,
            finance_dir=finance_dir,
            compute_a4=not args.no_a4,
        )

    if result_df.empty:
        print("分析失败")
        return

    print(f"\n总样本: {len(result_df)}")
    print(f"A4样本: {result_df['new_high'].sum()}")
    print(f"总体成功率: {result_df['success'].mean():.2%}")

    analyzer.group_statistics(result_df)
    analyzer.save_results(result_df)

    return result_df


if __name__ == '__main__':
    main()