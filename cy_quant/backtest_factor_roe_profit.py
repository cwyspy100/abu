"""
因子投资回测：ROE + 利润增速 预测突破120日均线后的成功率

核心假设：高ROE + 高利润增速的股票，突破后成功概率更高

方法：
1. 读取突破事件（来自livermore_results）
2. 匹配每只股票突破前的最新财务数据（ROE, netprofit_yoy）
3. 按因子五分位分组，统计各组成功率
4. 对比：高ROE高增速 vs 其他组合
"""

import pandas as pd
import numpy as np
import os
import glob
from dataclasses import dataclass
from typing import Optional, Dict, List
from datetime import datetime


@dataclass
class FactorResult:
    """因子回测结果"""
    ts_code: str
    breakthrough_date: str
    roe: float
    netprofit_yoy: float
    final_gain: float
    success: bool


class RoeProfitFactorAnalyzer:
    """ROE + 利润增速因子回测分析器"""

    def __init__(
        self,
        success_threshold: float = 20.0,
        observe_days: int = 10,
    ):
        self.success_threshold = success_threshold
        self.observe_days = observe_days

    def load_financial_data(self, stock_dir: str = None) -> pd.DataFrame:
        """加载所有股票的财务数据"""
        if stock_dir is None:
            stock_dir = os.path.expanduser('~/abu/tushare/finance')

        all_finance = []
        for f in glob.glob(os.path.join(stock_dir, '*_finance.csv')):
            try:
                df = pd.read_csv(f, encoding='utf-8-sig')
                if 'ts_code' in df.columns and 'end_date' in df.columns:
                    df['ts_code'] = df['ts_code'].astype(str)
                    df['end_date'] = df['end_date'].astype(str)
                    all_finance.append(df)
            except Exception:
                continue

        if not all_finance:
            return pd.DataFrame()

        result = pd.concat(all_finance, ignore_index=True)
        # 只保留需要的列
        cols = ['ts_code', 'end_date', 'roe', 'netprofit_yoy', 'gross_margin', 'netprofit_margin']
        cols = [c for c in cols if c in result.columns]
        return result[cols].copy()

    def match_financial_data(
        self,
        finance_df: pd.DataFrame,
        ts_code: str,
        breakthrough_date: str
    ) -> tuple:
        """
        匹配最近的财务数据（突破日之前的最新季度报告）
        返回: (roe, netprofit_yoy)
        """
        if finance_df.empty:
            return (np.nan, np.nan)

        # 筛选该股票
        stock_fin = finance_df[finance_df['ts_code'] == ts_code].copy()
        if stock_fin.empty:
            return (np.nan, np.nan)

        # 转换日期
        try:
            bt_date = datetime.strptime(str(breakthrough_date), '%Y%m%d')
        except Exception:
            bt_date = datetime.strptime(str(breakthrough_date), '%Y-%m-%d')

        # 筛选突破日之前的报告
        stock_fin = stock_fin.copy()
        stock_fin['end_date_dt'] = pd.to_datetime(stock_fin['end_date'], format='%Y%m%d', errors='coerce')
        stock_fin = stock_fin[stock_fin['end_date_dt'] < bt_date]

        if stock_fin.empty:
            return (np.nan, np.nan)

        # 取最近的季度
        stock_fin = stock_fin.sort_values('end_date_dt', ascending=False)
        latest = stock_fin.iloc[0]

        roe = latest.get('roe', np.nan)
        netprofit_yoy = latest.get('netprofit_yoy', np.nan)

        return (roe, netprofit_yoy)

    def load_breakthrough_data(self, breakthrough_file: str) -> pd.DataFrame:
        """加载突破事件数据"""
        df = pd.read_csv(breakthrough_file, encoding='utf-8-sig')
        if 'ts_code' not in df.columns:
            return pd.DataFrame()
        return df[['ts_code', 'breakthrough_date', 'final_gain', 'success']].copy()

    def analyze(
        self,
        breakthrough_file: str,
        finance_dir: str = None,
    ) -> pd.DataFrame:
        """
        执行因子回测

        步骤：
        1. 加载突破数据
        2. 匹配财务数据
        3. 按ROE和netprofit_yoy分组
        4. 统计各组成功率
        """
        # 加载突破数据
        bt_df = self.load_breakthrough_data(breakthrough_file)
        if bt_df.empty:
            print(f"未找到突破数据: {breakthrough_file}")
            return pd.DataFrame()

        print(f"加载 {len(bt_df)} 条突破事件")

        # 加载财务数据
        finance_df = self.load_financial_data(finance_dir)
        if finance_df.empty:
            print("未找到财务数据")
            return pd.DataFrame()
        print(f"加载 {len(finance_df)} 条财务记录")

        # 匹配财务数据
        results = []
        for _, row in bt_df.iterrows():
            ts_code = str(row['ts_code'])
            bt_date = str(row['breakthrough_date'])
            roe, netprofit_yoy = self.match_financial_data(
                finance_df, ts_code, bt_date
            )
            results.append({
                'ts_code': ts_code,
                'breakthrough_date': bt_date,
                'roe': roe,
                'netprofit_yoy': netprofit_yoy,
                'final_gain': row['final_gain'],
                'success': row['success'],
            })

        result_df = pd.DataFrame(results)
        return result_df

    def quintile_group(self, series: pd.Series, q: int = 5) -> pd.Series:
        """按分位数分组"""
        try:
            return pd.qcut(series, q=q, labels=False, duplicates='drop')
        except Exception:
            return pd.Series(np.nan, index=series.index)

    def group_statistics(self, result_df: pd.DataFrame) -> dict:
        """分组统计"""
        if result_df.empty:
            return {}

        df = result_df.copy()

        # 有效数据
        valid_df = df.dropna(subset=['roe', 'netprofit_yoy'])
        print(f"\n有效数据（有财务因子）: {len(valid_df)} / {len(df)}")

        if valid_df.empty:
            print("无可用财务数据")
            return {}

        # ROE五分位
        valid_df['roe_q'] = self.quintile_group(valid_df['roe'], q=5)
        # netprofit_yoy五分位
        valid_df['profit_yoy_q'] = self.quintile_group(valid_df['netprofit_yoy'], q=5)

        # 1. 按ROE分组
        print("\n" + "=" * 60)
        print("按ROE五分位分组:")
        roe_groups = valid_df.groupby('roe_q').agg({
            'success': ['count', 'mean'],
            'final_gain': 'mean',
        }).round(4)
        roe_groups.columns = ['count', 'success_rate', 'avg_final_gain']
        print(roe_groups.to_string())

        # 2. 按利润增速分组
        print("\n" + "=" * 60)
        print("按净利润增速(netprofit_yoy)五分位分组:")
        yoy_groups = valid_df.groupby('profit_yoy_q').agg({
            'success': ['count', 'mean'],
            'final_gain': 'mean',
        }).round(4)
        yoy_groups.columns = ['count', 'success_rate', 'avg_final_gain']
        print(yoy_groups.to_string())

        # 3. ROE x 利润增速 交叉分组
        print("\n" + "=" * 60)
        print("ROE x 利润增速 交叉分组 (成功率):")
        cross = valid_df.pivot_table(
            values='success',
            index='roe_q',
            columns='profit_yoy_q',
            aggfunc='mean',
        ).round(4)
        print(cross.to_string())

        # 4. 高ROE + 高增速组合
        print("\n" + "=" * 60)
        print("关键组合对比:")
        # 高ROE (top 20%) + 高增速 (top 20%)
        high_roe = valid_df['roe_q'] >= 4  # top 20% (quintile 4 and 5 out of 0-4)
        high_yoy = valid_df['profit_yoy_q'] >= 4

        combo_high = valid_df[high_roe & high_yoy]
        combo_low_low = valid_df[(~high_roe) & (~high_yoy)]

        stats = {
            '高ROE高增速': {
                'count': len(combo_high),
                'success_rate': combo_high['success'].mean() if len(combo_high) > 0 else 0,
                'avg_final_gain': combo_high['final_gain'].mean() if len(combo_high) > 0 else 0,
            },
            '低ROE低增速': {
                'count': len(combo_low_low),
                'success_rate': combo_low_low['success'].mean() if len(combo_low_low) > 0 else 0,
                'avg_final_gain': combo_low_low['final_gain'].mean() if len(combo_low_low) > 0 else 0,
            },
        }

        # 额外：单维度最优
        high_roe_only = valid_df[high_roe]
        high_yoy_only = valid_df[high_yoy]

        stats['高ROE(只看ROE)'] = {
            'count': len(high_roe_only),
            'success_rate': high_roe_only['success'].mean() if len(high_roe_only) > 0 else 0,
            'avg_final_gain': high_roe_only['final_gain'].mean() if len(high_roe_only) > 0 else 0,
        }
        stats['高增速(只看增速)'] = {
            'count': len(high_yoy_only),
            'success_rate': high_yoy_only['success'].mean() if len(high_yoy_only) > 0 else 0,
            'avg_final_gain': high_yoy_only['final_gain'].mean() if len(high_yoy_only) > 0 else 0,
        }

        print(f"{'组合':<20} {'样本数':>8} {'成功率':>12} {'平均涨幅':>12}")
        print("-" * 60)
        for name, s in stats.items():
            print(f"{name:<20} {s['count']:>8} {s['success_rate']:>11.2%} {s['avg_final_gain']:>11.2f}%")

        return stats

    def save_results(self, result_df: pd.DataFrame, filename: str = None):
        """保存结果"""
        if result_df.empty:
            return
        if filename is None:
            today = datetime.now().strftime('%Y%m%d')
            filename = os.path.join('cy_quant', 'output', f'factor_roe_profit_{today}.csv')
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"\n数据已保存至: {filename}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='ROE + 利润增速因子回测')
    parser.add_argument('--breakthrough-file', type=str,
                        default='cy_quant/output/livermore_results_20260422.csv',
                        help='突破事件文件')
    parser.add_argument('--finance-dir', type=str,
                        default='~/abu/tushare/finance',
                        help='财务数据目录')
    parser.add_argument('--success-threshold', type=float, default=20.0,
                        help='成功阈值(%%)')
    args = parser.parse_args()

    analyzer = RoeProfitFactorAnalyzer(
        success_threshold=args.success_threshold,
    )

    breakthrough_file = os.path.expanduser(args.breakthrough_file)
    finance_dir = os.path.expanduser(args.finance_dir)

    print(f"突破事件文件: {breakthrough_file}")
    print(f"财务数据目录: {finance_dir}")
    print(f"成功阈值: {args.success_threshold}%")

    result_df = analyzer.analyze(
        breakthrough_file=breakthrough_file,
        finance_dir=finance_dir,
    )

    if result_df.empty:
        print("分析失败")
        return

    print(f"\n总样本: {len(result_df)}")
    print(f"总体成功率: {result_df['success'].mean():.2%}")
    print(f"总体平均涨幅: {result_df['final_gain'].mean():.2f}%")

    stats = analyzer.group_statistics(result_df)
    analyzer.save_results(result_df)

    return result_df, stats


if __name__ == '__main__':
    main()