"""
股票涨幅倍数分析器
扫描~/abu/data/csv/目录下所有指定前缀开头的文件
统计涨幅超过指定倍数的股票
"""

import pandas as pd
import numpy as np
import os
import glob
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')


class StockMultiplierAnalyzer:
    """股票涨幅倍数分析器"""
    
    def __init__(self, prefixes=None, multiplier=10.0):
        """
        初始化
        :param prefixes: 文件前缀列表，默认为['sh', 'sz']
        :param multiplier: 涨幅倍数阈值，默认为10.0（即涨幅超过10倍）
        """
        self.csv_dir = os.path.expanduser('~/abu/data/csv')
        self.results = []
        # 如果没有指定前缀，默认使用sh和sz
        if prefixes is None:
            prefixes = ['sh', 'sz']
        self.prefixes = prefixes if isinstance(prefixes, list) else [prefixes]
        self.multiplier = multiplier
    
    def get_stock_files(self):
        """
        获取所有指定前缀开头的文件（支持有或无.csv扩展名）
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
                # 排除已经是.csv的文件（避免重复）
                if not f.endswith('.csv') or f not in all_files:
                    if f not in all_files:
                        all_files.append(f)
        
        # 去重并过滤：只保留符合命名格式的文件（指定前缀开头，包含下划线和日期）
        valid_files = []
        for f in all_files:
            filename = os.path.basename(f)
            # 移除扩展名检查
            name_without_ext = filename.replace('.csv', '')
            parts = name_without_ext.split('_')
            # 检查是否以任一指定前缀开头
            if len(parts) >= 3 and any(name_without_ext.startswith(prefix) for prefix in self.prefixes):
                valid_files.append(f)
        
        print(f"找到 {len(valid_files)} 个股票数据文件")
        return valid_files
    
    def parse_filename(self, filepath):
        """
        从文件名解析股票代码和日期范围
        文件名格式：sh600452_20240703_20251217 或 sh600452_20240703_20251217.csv
        :param filepath: 文件路径
        :return: (股票代码, 开始日期, 结束日期) 或 None
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
                return ts_code, start_date, end_date
            
            return None
        
        return None
    
    def analyze_stock(self, filepath):
        """
        分析单个股票文件，找出涨幅超过倍数的记录
        :param filepath: 文件路径
        :return: 分析结果列表
        """
        results = []
        try:
            # 解析文件名
            parse_result = self.parse_filename(filepath)
            if parse_result is None:
                return results
            
            ts_code, start_date, end_date = parse_result
            
            # 读取CSV文件（尝试不同的编码）
            try:
                df = pd.read_csv(filepath, encoding='utf-8-sig')
            except:
                try:
                    df = pd.read_csv(filepath, encoding='gbk')
                except:
                    df = pd.read_csv(filepath, encoding='utf-8')
            
            if df.empty:
                return results
            
            # 确保有date和close列
            if 'date' in df.columns:
                df = df.rename(columns={'date': 'trade_date'})
            
            if 'trade_date' not in df.columns or 'close' not in df.columns:
                return results
            
            # 确保数据按日期排序
            df = df.sort_values('trade_date').reset_index(drop=True)
            
            # 获取第一条记录的价格作为起始价格
            if len(df) < 2:
                return results
            
            start_price = df.iloc[0]['close']
            start_date_record = df.iloc[0]['trade_date']
            
            if start_price <= 0:
                return results
            
            # 找出整个数据期间内涨幅超过倍数的最高点
            max_multiplier = 0
            max_idx = 0
            
            # 遍历所有记录，找出涨幅最大的点
            for i in range(1, len(df)):
                current_price = df.iloc[i]['close']
                
                if current_price > 0:
                    # 计算涨幅倍数
                    price_multiplier = current_price / start_price
                    
                    # 记录涨幅最大的点
                    if price_multiplier > max_multiplier:
                        max_multiplier = price_multiplier
                        max_idx = i
            
            # 如果最大涨幅超过阈值倍数，记录结果
            if max_multiplier >= self.multiplier:
                max_price = df.iloc[max_idx]['close']
                max_date = df.iloc[max_idx]['trade_date']
                
                # 计算涨幅百分比
                growth_rate = (max_multiplier - 1) * 100
                
                # 计算交易日数量
                trading_days = max_idx + 1
                
                # 计算最终价格和最终涨幅（如果数据有结束日期）
                final_price = df.iloc[-1]['close']
                final_date = df.iloc[-1]['trade_date']
                final_multiplier = final_price / start_price if final_price > 0 else 0
                final_growth_rate = (final_multiplier - 1) * 100 if final_multiplier > 0 else 0
                
                results.append({
                    'ts_code': ts_code,
                    'start_date': start_date,
                    'end_date': end_date,
                    'start_price': round(start_price, 2),
                    'max_price': round(max_price, 2),
                    'max_date': max_date,
                    'max_multiplier': round(max_multiplier, 2),
                    'max_growth_rate': round(growth_rate, 2),
                    'final_price': round(final_price, 2),
                    'final_date': final_date,
                    'final_multiplier': round(final_multiplier, 2),
                    'final_growth_rate': round(final_growth_rate, 2),
                    'trading_days_to_max': trading_days,
                    'total_trading_days': len(df)
                })
            
        except Exception as e:
            print(f"分析文件 {filepath} 时出错: {e}")
        
        return results
    
    def analyze_all(self):
        """
        分析所有股票文件
        :return: 结果DataFrame
        """
        print("=" * 60)
        print(f"开始分析涨幅超过 {self.multiplier} 倍的股票")
        print("=" * 60)
        
        # 获取所有股票文件
        stock_files = self.get_stock_files()
        
        if not stock_files:
            print("未找到股票数据文件！")
            return pd.DataFrame()
        
        # 分析每个股票
        all_results = []
        for i, filepath in enumerate(stock_files):
            results = self.analyze_stock(filepath)
            all_results.extend(results)
            
            # 每处理50个文件显示进度
            if (i + 1) % 50 == 0:
                print(f"已处理 {i + 1}/{len(stock_files)} 个文件，找到 {len(all_results)} 条超过{self.multiplier}倍的记录...")
        
        if not all_results:
            print(f"未找到任何涨幅超过 {self.multiplier} 倍的股票")
            return pd.DataFrame()
        
        # 转换为DataFrame
        result_df = pd.DataFrame(all_results)
        
        # 确保数值字段为正确的数值类型
        numeric_columns = ['start_price', 'max_price', 'max_multiplier', 'max_growth_rate',
                          'final_price', 'final_multiplier', 'final_growth_rate',
                          'trading_days_to_max', 'total_trading_days']
        for col in numeric_columns:
            if col in result_df.columns:
                result_df[col] = pd.to_numeric(result_df[col], errors='coerce')
        
        # 按最大倍数排序（最高的在前）
        result_df = result_df.sort_values('max_multiplier', ascending=False)
        
        print(f"\n分析完成！共找到 {len(result_df)} 条涨幅超过 {self.multiplier} 倍的记录")
        print("=" * 60)
        
        return result_df
    
    def save_results(self, result_df, filename=None):
        """
        保存结果到CSV文件
        :param result_df: 结果DataFrame
        :param filename: 文件名，None则自动生成
        """
        if result_df.empty:
            print("没有数据可保存")
            return
        
        if filename is None:
            today = datetime.now().strftime('%Y%m%d')
            # 获取前缀，如果有多个前缀，取第一个
            prefix = self.prefixes[0] if self.prefixes else ''
            if prefix:
                filename = f'{prefix}_multiplier_{self.multiplier}x_{today}.csv'
            else:
                filename = f'multiplier_{self.multiplier}x_{today}.csv'
        
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"\n结果已保存至: {filename}")
        
        # 显示前20条结果
        print("\n前20条结果:")
        print(result_df.head(20).to_string(index=False))


def analyze_multiplier(prefixes=None, multiplier=10.0):
    """
    分析涨幅超过指定倍数的股票
    :param prefixes: 文件前缀列表，默认为None（使用默认的['sh', 'sz']）
                     可以传入 ['sh', 'sz'] 或 ['sh'] 或 ['sz'] 等
    :param multiplier: 涨幅倍数阈值，默认为10.0（即涨幅超过10倍）
    :return: 结果DataFrame
    """
    analyzer = StockMultiplierAnalyzer(prefixes=prefixes, multiplier=multiplier)
    
    # 分析所有股票
    result_df = analyzer.analyze_all()
    
    # 保存结果
    if not result_df.empty:
        analyzer.save_results(result_df)
    
    return result_df


if __name__ == '__main__':
    import time
    start = time.time()
    
    # 使用默认参数（分析sh和sz开头的文件，涨幅超过10倍）
    result = analyze_multiplier(prefixes=['hk'])
    
    # 自定义示例：
    # result = analyze_multiplier(multiplier=5.0)  # 涨幅超过5倍
    # result = analyze_multiplier(prefixes=['sh'], multiplier=20.0)  # 只分析sh开头，涨幅超过20倍
    
    print(f"\n处理完成，耗时 {time.time() - start:.2f} 秒")

