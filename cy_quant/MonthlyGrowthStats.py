"""
统计给定年份每个月的涨幅和得分
扫描~/abu/data/csv/目录下所有股票文件
统计每个月的涨幅，不足一个月按照一个月算
涨幅10%，除以10，得1分；涨幅100%，除以10加10分；-50%，除以10得-5分
"""

import pandas as pd
import numpy as np
import os
import glob
from datetime import datetime
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')


class MonthlyGrowthStats:
    """月度涨幅统计器"""
    
    def __init__(self, prefixes=None):
        """
        初始化
        :param prefixes: 文件前缀列表，默认为['sh', 'sz']
        """
        self.csv_dir = os.path.expanduser('~/abu/data/csv')
        # 如果没有指定前缀，默认使用sh和sz
        if prefixes is None:
            prefixes = ['sh', 'sz']
        self.prefixes = prefixes if isinstance(prefixes, list) else [prefixes]
    
    def get_stock_files(self):
        """
        获取所有指定前缀开头的文件
        :return: 文件路径列表
        """
        all_files = []
        
        # 根据前缀动态生成文件模式
        patterns = []
        for prefix in self.prefixes:
            patterns.append(os.path.join(self.csv_dir, f'{prefix}*.csv'))
            patterns.append(os.path.join(self.csv_dir, f'{prefix}*'))
        
        for pattern in patterns:
            files = glob.glob(pattern)
            for f in files:
                if not f.endswith('.csv') or f not in all_files:
                    if f not in all_files:
                        all_files.append(f)
        
        # 去重并过滤：只保留符合命名格式的文件
        valid_files = []
        for f in all_files:
            filename = os.path.basename(f)
            name_without_ext = filename.replace('.csv', '')
            parts = name_without_ext.split('_')
            # 检查是否以任一指定前缀开头，且符合命名格式（至少3部分：代码_开始日期_结束日期）
            if len(parts) >= 3 and any(name_without_ext.startswith(prefix) for prefix in self.prefixes):
                valid_files.append(f)
        
        print(f"找到 {len(valid_files)} 个股票数据文件")
        return valid_files
    
    def parse_filename(self, filepath):
        """
        从文件名解析股票代码和日期范围
        文件名格式：sh600452_20240703_20251217 或 sh600452_20240703_20251217.csv
        :param filepath: 文件路径
        :return: (股票代码, 开始日期, 结束日期, 前缀) 或 None
        """
        filename = os.path.basename(filepath)
        
        # 移除.csv扩展名（如果有）
        if filename.endswith('.csv'):
            filename = filename[:-4]
        
        # 解析文件名：sh600452_20240703_20251217
        parts = filename.split('_')
        if len(parts) >= 3:
            code_part = parts[0]  # sh600452 或 sz000001
            start_date = parts[1]  # 20240703
            end_date = parts[2]     # 20251217
            
            # 前缀到交易所代码的映射
            prefix_to_exchange = {
                'sh': 'SH',
                'sz': 'SZ',
                'hk': 'HK',
                'us': 'US'
            }
            
            # 检查code_part是否以任一指定前缀开头
            matched_prefix = None
            for prefix in self.prefixes:
                if code_part.startswith(prefix):
                    matched_prefix = prefix
                    break
            
            if matched_prefix and matched_prefix in prefix_to_exchange:
                exchange = prefix_to_exchange[matched_prefix]
                ts_code = f"{code_part[len(matched_prefix):]}.{exchange}"
                return ts_code, start_date, end_date, matched_prefix
            
            return None
        
        return None
    
    def get_price_threshold(self, prefix):
        """
        根据股票前缀获取价格阈值
        :param prefix: 股票前缀（'us', 'hk', 'sh', 'sz'）
        :return: 价格阈值
        """
        # 美股和港股使用2，A股使用5
        if prefix in ['us', 'hk']:
            return 2.0
        else:
            return 5.0
    
    def calculate_score(self, growth_rate):
        """
        根据涨幅计算得分
        涨幅10%，除以10，得1分
        涨幅100%，除以10加10分（即100/10 + 10 = 20分）
        -50%，除以10得-5分
        :param growth_rate: 涨幅（百分比，如10表示10%）
        :return: 得分
        """
        base_score = growth_rate / 10.0
        
        # 如果涨幅>=100%，额外加10分
        if growth_rate >= 100:
            base_score += 10
        
        return round(base_score, 2)
    
    def calculate_monthly_growth(self, df, target_year):
        """
        计算指定年份每个月的涨幅和总涨幅
        :param df: 包含trade_date和close的DataFrame
        :param target_year: 目标年份（如2025）
        :return: (月度涨幅字典, 总涨幅, 年底价格)，月度涨幅字典key为月份（1-12），value为涨幅值；总涨幅为年初到年末的涨幅；年底价格为年末最后一个交易日的收盘价
        """
        if df is None or df.empty or 'trade_date' not in df.columns or 'close' not in df.columns:
            return {}, None, None
        
        # 确保数据按日期排序
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        # 确保trade_date列是字符串类型
        df['trade_date'] = df['trade_date'].astype(str)
        
        # 筛选目标年份的数据
        year_start_str = f"{target_year}0101"
        year_end_str = f"{target_year}1231"
        
        # 筛选目标年份的数据
        df_year = df[(df['trade_date'] >= year_start_str) & (df['trade_date'] <= year_end_str)].copy()
        
        if df_year.empty:
            return {}, None, None
        
        # 计算总涨幅（年初第一个交易日到年末最后一个交易日）
        total_growth = None
        year_end_price = None
        if not df_year.empty:
            first_price = df_year.iloc[0]['close']
            last_price = df_year.iloc[-1]['close']
            year_end_price = last_price  # 年底价格
            if first_price > 0:
                total_growth = (last_price - first_price) / first_price * 100
        
        # 按月分组统计
        monthly_data = {}
        
        # 为每条记录添加年月信息
        df_year['year_month'] = df_year['trade_date'].apply(
            lambda x: int(x[4:6]) if len(x) >= 6 else None
        )
        
        # 按月份分组
        for month in range(1, 13):
            month_data = df_year[df_year['year_month'] == month]
            if not month_data.empty:
                # 获取该月第一个交易日和最后一个交易日的收盘价
                # 不足一个月按照一个月算，只要有数据就算
                first_price = month_data.iloc[0]['close']
                last_price = month_data.iloc[-1]['close']
                
                # 计算涨幅
                if first_price > 0:
                    growth_rate = (last_price - first_price) / first_price * 100
                    monthly_data[month] = growth_rate
        
        return monthly_data, total_growth, year_end_price
    
    def analyze_stock(self, filepath, target_year):
        """
        分析单个股票文件
        :param filepath: 文件路径
        :param target_year: 目标年份
        :return: (股票代码, 月度涨幅字典, 总涨幅, 年底价格, 前缀)，月度涨幅字典key为月份(1-12)，value为涨幅值；总涨幅为年初到年末的涨幅；年底价格为年末最后一个交易日的收盘价；前缀用于确定价格阈值
        """
        try:
            # 解析文件名
            parse_result = self.parse_filename(filepath)
            if parse_result is None:
                return None
            
            ts_code, start_date, end_date, prefix = parse_result
            
            # 读取CSV文件（尝试不同的编码）
            try:
                df = pd.read_csv(filepath, encoding='utf-8-sig')
            except:
                try:
                    df = pd.read_csv(filepath, encoding='gbk')
                except:
                    df = pd.read_csv(filepath, encoding='utf-8')
            
            if df.empty:
                return None
            
            # 确保有date和close列
            if 'date' in df.columns:
                df = df.rename(columns={'date': 'trade_date'})
            
            if 'trade_date' not in df.columns or 'close' not in df.columns:
                return None
            
            # 计算月度涨幅和总涨幅
            monthly_growth, total_growth, year_end_price = self.calculate_monthly_growth(df, target_year)
            
            # 如果没有月度数据，返回None
            if not monthly_growth:
                return None
            
            return ts_code, monthly_growth, total_growth, year_end_price, prefix
            
        except Exception as e:
            print(f"分析文件 {filepath} 时出错: {e}")
            return None
    
    def analyze_all(self, target_year):
        """
        分析所有股票文件，统计指定年份每个股票每个月的涨幅和得分
        :param target_year: 目标年份（如2025）
        :return: 汇总结果DataFrame，包含股票代码、1-12月涨幅、总得分、总涨幅
        """
        print("=" * 60)
        print(f"开始统计 {target_year} 年每个股票每个月的涨幅和得分")
        print("=" * 60)
        
        # 获取所有股票文件
        stock_files = self.get_stock_files()
        
        if not stock_files:
            print("未找到股票数据文件！")
            return pd.DataFrame()
        
        # 存储每个股票的数据
        stock_results = []
        
        # 分析每个股票
        for i, filepath in enumerate(stock_files):
            result = self.analyze_stock(filepath, target_year)
            
            if result is None:
                continue
            
            ts_code, monthly_growth, total_growth, year_end_price, prefix = result
            
            # 去掉股票代码的后缀（.SZ、.SH、.HK、.US等）
            stock_code = ts_code.split('.')[0] if '.' in ts_code else ts_code
            
            # 构建该股票的记录
            stock_record = {
                '股票代码': stock_code
            }
            
            # 初始化1-12月的涨幅
            for month in range(1, 13):
                month_key = f'{month}月涨幅(%)'
                
                if month in monthly_growth:
                    growth_rate = monthly_growth[month]
                    stock_record[month_key] = round(growth_rate, 2)
                else:
                    # 该月没有数据
                    stock_record[month_key] = None
            
            # 添加总涨幅和总得分（基于总涨幅计算，更能反映涨幅好的股票）
            stock_record['总涨幅(%)'] = round(total_growth, 2) if total_growth is not None else None
            
            # 计算总得分：根据股票类型设置不同的价格阈值（美股/港股2，A股5）
            if total_growth is not None:
                # 获取价格阈值
                price_threshold = self.get_price_threshold(prefix)
                
                # 检查年底价格，如果小于阈值，总得分为0
                if year_end_price is not None and year_end_price < price_threshold:
                    stock_record['总得分'] = 0.0
                else:
                    # 总得分基于总涨幅计算，这样涨幅高的股票得分也高
                    total_score = self.calculate_score(total_growth)
                    stock_record['总得分'] = round(total_score, 2)
            else:
                stock_record['总得分'] = None
            
            stock_results.append(stock_record)
            
            # 每处理50个文件显示进度
            if (i + 1) % 50 == 0:
                print(f"已处理 {i + 1}/{len(stock_files)} 个文件...")
        
        if not stock_results:
            print(f"未找到 {target_year} 年的数据")
            return pd.DataFrame()
        
        # 转换为DataFrame
        result_df = pd.DataFrame(stock_results)
        
        # 按总得分降序排序
        result_df = result_df.sort_values('总得分', ascending=False).reset_index(drop=True)
        
        print(f"\n统计完成！共统计 {len(stock_results)} 个股票")
        print(f"总得分范围: {result_df['总得分'].min():.2f} ~ {result_df['总得分'].max():.2f}")
        print("=" * 60)
        
        return result_df
    
    def save_results(self, result_df, target_year, filename=None):
        """
        保存结果到CSV文件
        :param result_df: 结果DataFrame
        :param target_year: 目标年份
        :param filename: 文件名，None则自动生成
        """
        if result_df.empty:
            print("没有数据可保存")
            return
        
        # 确保列的顺序：股票代码、1月涨幅、2月涨幅、...、12月涨幅、总涨幅、总得分
        columns_order = ['股票代码']
        
        # 添加1-12月的涨幅列
        for month in range(1, 13):
            columns_order.append(f'{month}月涨幅(%)')
        
        columns_order.append('总涨幅(%)')
        columns_order.append('总得分')
        
        # 只保留存在的列
        columns_order = [col for col in columns_order if col in result_df.columns]
        
        # 重新排列列的顺序
        result_df = result_df[columns_order]
        
        if filename is None:
            today = datetime.now().strftime('%Y%m%d')
            # 获取前缀，如果有多个前缀，取第一个
            prefix = self.prefixes[0] if self.prefixes else ''
            if prefix:
                filename = f'{prefix}_monthly_growth_{target_year}_{today}.csv'
            else:
                filename = f'monthly_growth_{target_year}_{today}.csv'
        
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"\n结果已保存至: {filename}")
        
        # 显示前20条结果
        print("\n前20条结果:")
        print(result_df.head(20).to_string(index=False))


def main(target_year=2025, prefixes=None):
    """
    主函数
    :param target_year: 目标年份，默认为2025
    :param prefixes: 文件前缀列表，默认为None（使用默认的['sh', 'sz']）
    """
    analyzer = MonthlyGrowthStats(prefixes=prefixes)
    
    # 分析所有股票
    result_df = analyzer.analyze_all(target_year)
    
    # 保存结果
    if not result_df.empty:
        analyzer.save_results(result_df, target_year)
    
    return result_df


if __name__ == '__main__':
    import time
    start = time.time()
    
    # 统计2025年每个月的涨幅和得分
    result = main(target_year=2026)
    
    print(f"\n处理完成，耗时 {time.time() - start:.2f} 秒")
