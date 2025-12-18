"""
分析120日均线突破
扫描~/abu/data/csv/目录下所有sh和sz开头的文件
统计最后一次超过120日均线的开始时间、当前价格和增长率
"""

import pandas as pd
import numpy as np
import os
import glob
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')


class Analyze120MA:
    """120日均线分析器"""
    
    def __init__(self):
        """初始化"""
        self.csv_dir = os.path.expanduser('~/abu/data/csv')
        self.results = []
    
    def get_stock_files(self):
        """
        获取所有sh和sz开头的文件（支持有或无.csv扩展名）
        :return: 文件路径列表
        """
        all_files = []
        
        # 获取所有sh和sz开头的文件（包括.csv和无扩展名）
        patterns = [
            os.path.join(self.csv_dir, 'sh*.csv'),
            os.path.join(self.csv_dir, 'sz*.csv'),
            os.path.join(self.csv_dir, 'sh*'),
            os.path.join(self.csv_dir, 'sz*')
        ]
        
        for pattern in patterns:
            files = glob.glob(pattern)
            for f in files:
                # 排除已经是.csv的文件（避免重复）
                if not f.endswith('.csv') or f not in all_files:
                    if f not in all_files:
                        all_files.append(f)
        
        # 去重并过滤：只保留符合命名格式的文件（sh/sz开头，包含下划线和日期）
        valid_files = []
        for f in all_files:
            filename = os.path.basename(f)
            # 移除扩展名检查
            name_without_ext = filename.replace('.csv', '')
            parts = name_without_ext.split('_')
            if len(parts) >= 3 and (name_without_ext.startswith('sh') or name_without_ext.startswith('sz')):
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
            
            # 转换为标准格式：sh600452 -> 600452.SH
            if code_part.startswith('sh'):
                ts_code = f"{code_part[2:]}.SH"
            elif code_part.startswith('sz'):
                ts_code = f"{code_part[2:]}.SZ"
            else:
                return None
            
            return ts_code, start_date, end_date
        
        return None
    
    def calculate_120ma(self, df):
        """
        计算120日均线
        :param df: 包含date和close的DataFrame
        :return: 添加了ma120列的DataFrame
        """
        df = df.copy()
        # 按日期排序
        df = df.sort_values('trade_date')
        
        # 计算120日均线
        # min_periods=120 表示只有当有至少120条数据时才开始计算，前119天为NaN
        df['ma120'] = df['close'].rolling(window=120, min_periods=120).mean()
        
        # 将前119天的ma120值填充为对应的close值（因为数据不足120条时无法计算真正的120日均线）
        df['ma120'] = df['ma120'].fillna(df['close'])
        
        return df
    
    def find_last_breakthrough(self, df):
        """
        找出最后一次超过120日均线的开始和结束时间
        要求：最后一天必须在120日均线上方，才符合条件
        :param df: 包含ma120和close的DataFrame
        :return: (开始日期, 开始价格, 当前价格, 增长率, 天数) 或 None
        """
        if df is None or df.empty or 'ma120' not in df.columns or 'close' not in df.columns:
            return None
        
        # 确保数据按日期排序
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        # 需要至少120条数据才能有有效的120日均线
        if len(df) < 120:
            return None
        
        # 找出价格超过120日均线的位置
        df['above_ma120'] = df['close'] > df['ma120']
        
        # 关键条件：最后一天必须在120日均线上方，否则不符合条件
        if not df.iloc[-1]['above_ma120']:
            return None
        
        # 如果最后一天在均线上方，从最后一天往前找，找到这个连续区间的开始点
        # 开始点应该是：找到第一个不在均线上方的点，然后它的下一个点就是开始点
        start_idx = None
        
        # 从倒数第二个点往前找，找到第一个不在均线上方的点
        for i in range(len(df) - 2, -1, -1):
            if not df.iloc[i]['above_ma120']:
                # 找到了第一个不在均线上方的点，下一个点就是开始点
                start_idx = i + 1
                break
        
        # 如果没找到不在均线上方的点（说明从一开始就在均线上方），则第一个点就是开始点
        if start_idx is None:
            start_idx = 0
        
        # 获取开始点的信息
        start_date = df.iloc[start_idx]['trade_date']
        start_price = df.iloc[start_idx]['close']
        
        # 结束日期是最后一天（当前最新日期）
        end_date = df.iloc[-1]['trade_date']
        current_price = df.iloc[-1]['close']
        
        # 计算增长率
        if start_price > 0:
            growth_rate = (current_price - start_price) / start_price * 100
        else:
            growth_rate = 0
        
        # 计算从突破开始到当前的累计交易日数量（包含开始和结束）
        # 交易日数量 = 结束索引 - 开始索引 + 1
        end_idx = len(df) - 1
        trading_days = end_idx - start_idx + 1
        
        return start_date, start_price, current_price, growth_rate, trading_days
    
    def analyze_stock(self, filepath):
        """
        分析单个股票文件
        :param filepath: 文件路径
        :return: 分析结果字典或None
        """
        try:
            # 解析文件名
            parse_result = self.parse_filename(filepath)
            if parse_result is None:
                return None
            
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
                return None
            
            # 确保有date和close列
            if 'date' in df.columns:
                df = df.rename(columns={'date': 'trade_date'})
            
            if 'trade_date' not in df.columns or 'close' not in df.columns:
                return None
            
            # 计算120日均线
            df_with_ma = self.calculate_120ma(df)
            
            if df_with_ma is None:
                return None
            
            # 找出最后一次突破120日均线的信息
            breakthrough_info = self.find_last_breakthrough(df_with_ma)
            
            if breakthrough_info is None:
                return None
            
            start_date_breakthrough, start_price, current_price, growth_rate, days_diff = breakthrough_info
            
            return {
                'ts_code': ts_code,
                'start_date': start_date,
                'end_date': end_date,
                'breakthrough_date': start_date_breakthrough,
                'start_price': round(start_price, 2),
                'current_price': round(current_price, 2),
                'growth_rate': round(growth_rate, 2),
                'days': days_diff
            }
            
        except Exception as e:
            print(f"分析文件 {filepath} 时出错: {e}")
            return None
    
    def analyze_all(self):
        """
        分析所有股票文件
        :return: 结果DataFrame
        """
        print("=" * 60)
        print("开始分析120日均线突破")
        print("=" * 60)
        
        # 获取所有股票文件
        stock_files = self.get_stock_files()
        
        if not stock_files:
            print("未找到股票数据文件！")
            return pd.DataFrame()
        
        # 分析每个股票
        results = []
        for i, filepath in enumerate(stock_files):
            result = self.analyze_stock(filepath)
            if result:
                results.append(result)
            
            # 每处理50个文件显示进度
            if (i + 1) % 50 == 0:
                print(f"已处理 {i + 1}/{len(stock_files)} 个文件...")
        
        if not results:
            print("未找到任何突破120日均线的股票")
            return pd.DataFrame()
        
        # 转换为DataFrame
        result_df = pd.DataFrame(results)
        
        # 按突破日期排序（最新的在前）
        result_df = result_df.sort_values('breakthrough_date', ascending=False)
        
        print(f"\n分析完成！共找到 {len(result_df)} 只股票突破120日均线")
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
            filename = f'120ma_breakthrough_{today}.csv'
        
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"\n结果已保存至: {filename}")
        
        # 显示前20条结果
        print("\n前20条结果:")
        print(result_df.head(20).to_string(index=False))


def main():
    """主函数"""
    analyzer = Analyze120MA()

    # 测试流程
    # result_df = analyzer.analyze_stock(filepath='~/abu/data/csv/sh600226_20240703_20251217')

    # 分析所有股票
    result_df = analyzer.analyze_all()

    # 保存结果
    if not result_df.empty:
        analyzer.save_results(result_df)
    
    return result_df


if __name__ == '__main__':
    import time
    start = time.time()
    
    result = main()
    
    print(f"\n处理完成，耗时 {time.time() - start:.2f} 秒")

