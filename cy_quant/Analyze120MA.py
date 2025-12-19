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
    
    def __init__(self, prefixes=None, min_price=None):
        """
        初始化
        :param prefixes: 文件前缀列表，默认为['sh', 'sz']
        :param min_price: 最小价格阈值，过滤掉start_price小于此值的股票，默认为None（不过滤）
        """
        self.csv_dir = os.path.expanduser('~/abu/data/csv')
        self.results = []
        # 如果没有指定前缀，默认使用sh和sz
        if prefixes is None:
            prefixes = ['sh', 'sz']
        self.prefixes = prefixes if isinstance(prefixes, list) else [prefixes]
        self.min_price = min_price
    
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
    
    def calculate_120ma(self, df):
        """
        计算120日均线，同时计算10、20、30日均线
        :param df: 包含date和close的DataFrame
        :return: 添加了ma120、ma10、ma20、ma30列的DataFrame
        """
        df = df.copy()
        # 按日期排序
        df = df.sort_values('trade_date')
        
        # 计算120日均线
        # min_periods=120 表示只有当有至少120条数据时才开始计算，前119天为NaN
        df['ma120'] = df['close'].rolling(window=120, min_periods=120).mean()
        
        # 将前119天的ma120值填充为对应的close值（因为数据不足120条时无法计算真正的120日均线）
        df['ma120'] = df['ma120'].fillna(df['close'])
        
        # 计算10、20、30日均线
        df['ma10'] = df['close'].rolling(window=10, min_periods=10).mean()
        df['ma20'] = df['close'].rolling(window=20, min_periods=20).mean()
        df['ma30'] = df['close'].rolling(window=30, min_periods=30).mean()
        
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
    
    def calculate_growth_at_days(self, df, breakthrough_date, breakthrough_price, days_list=[10, 20, 30]):
        """
        计算突破120日均线后，指定天数的累计增长
        :param df: 包含trade_date和close的DataFrame，已按日期排序
        :param breakthrough_date: 突破日期（字符串格式，如'20250101'）
        :param breakthrough_price: 突破时的价格
        :param days_list: 要统计的天数列表，默认[10, 20, 30, 40, 50]
        :return: 字典，包含各天数的涨幅
        """
        # 确保数据按日期排序并重置索引
        df_sorted = df.sort_values('trade_date').reset_index(drop=True)
        df_sorted['trade_date'] = df_sorted['trade_date'].astype(str)
        
        # 找到突破日期在DataFrame中的位置
        breakthrough_idx = None
        for idx, row in df_sorted.iterrows():
            if row['trade_date'] == breakthrough_date:
                breakthrough_idx = idx
                break
        
        if breakthrough_idx is None:
            return {}
        
        result = {}
        
        # 计算每个天数的累计增长
        for days in days_list:
            target_idx = breakthrough_idx + days - 1  # 突破当天算第1天，所以需要-1
            
            if target_idx < len(df_sorted):
                # 有足够的数据
                target_price = df_sorted.iloc[target_idx]['close']
                if breakthrough_price > 0:
                    growth = (target_price - breakthrough_price) / breakthrough_price * 100
                else:
                    growth = 0
                result[f'growth_{days}d'] = round(growth, 2)
            else:
                # 数据不足，涨幅设置为0
                result[f'growth_{days}d'] = 0.0
        
        return result
    
    def calculate_ma_slope(self, df, breakthrough_date, ma_column, days=10):
        """
        计算从突破日期开始往后N天的均线斜率
        :param df: 包含均线数据的DataFrame，已按日期排序
        :param breakthrough_date: 突破日期（字符串格式）
        :param ma_column: 均线列名，如'ma10', 'ma20', 'ma30'
        :param days: 从突破日期开始往后计算的天数，默认10
        :return: 斜率值（如果数据不足返回None）
        """
        if ma_column not in df.columns:
            return None
        
        # 确保trade_date是字符串类型
        df = df.copy()
        df['trade_date'] = df['trade_date'].astype(str)
        
        # 找到突破日期在DataFrame中的位置
        breakthrough_idx = None
        for idx, row in df.iterrows():
            if row['trade_date'] == breakthrough_date:
                breakthrough_idx = idx
                break
        
        if breakthrough_idx is None:
            return None
        
        # 从突破日期开始，往后取days个数据点（包含突破当天）
        end_idx = breakthrough_idx + days
        if end_idx > len(df):
            return None
        
        # 获取从突破日期开始往后days天的均线数据
        ma_values = df.iloc[breakthrough_idx:end_idx][ma_column].dropna()
        
        if len(ma_values) < days:
            return None
        
        # 使用线性回归计算斜率
        y_values = ma_values.values
        x_values = np.arange(len(y_values))
        
        # 使用线性回归计算斜率
        slope = np.polyfit(x_values, y_values, 1)[0]
        
        return slope
    
    def calculate_max_price(self, df, breakthrough_date, days):
        """
        计算从突破日期开始往后N日的最高价格
        :param df: 包含close的DataFrame，已按日期排序
        :param breakthrough_date: 突破日期（字符串格式）
        :param days: 从突破日期开始往后计算的天数，如10、20、30
        :return: 最高价格（如果数据不足返回None）
        """
        if 'close' not in df.columns:
            return None
        
        # 确保trade_date是字符串类型
        df = df.copy()
        df['trade_date'] = df['trade_date'].astype(str)
        
        # 找到突破日期在DataFrame中的位置
        breakthrough_idx = None
        for idx, row in df.iterrows():
            if row['trade_date'] == breakthrough_date:
                breakthrough_idx = idx
                break
        
        if breakthrough_idx is None:
            return None
        
        # 从突破日期开始，往后取days个数据点（包含突破当天）
        end_idx = breakthrough_idx + days
        if end_idx > len(df):
            return None
        
        # 获取从突破日期开始往后days天的价格数据
        price_data = df.iloc[breakthrough_idx:end_idx]['close']
        
        if len(price_data) < days:
            return None
        
        return price_data.max()
    
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
            
            # 如果设置了最小价格阈值，过滤掉start_price小于阈值的股票
            if self.min_price is not None and start_price < self.min_price:
                return None
            
            # 计算年初到当前的涨跌幅
            # 确保数据按日期排序
            df_sorted = df_with_ma.sort_values('trade_date').reset_index(drop=True)
            
            # 确保trade_date列是字符串类型，以便进行比较
            df_sorted['trade_date'] = df_sorted['trade_date'].astype(str)
            
            # 获取当前年份（从结束日期获取）
            current_year = int(end_date[:4])
            year_start_str = f"{current_year}0101"
            
            # 找到年初的第一个交易日（大于等于年初日期的第一条记录）
            year_start_price = None
            year_to_date_growth = None
            
            # 查找年初第一个交易日
            year_start_records = df_sorted[df_sorted['trade_date'] >= year_start_str]
            if not year_start_records.empty:
                year_start_price = year_start_records.iloc[0]['close']
                # 计算年初到当前的涨幅
                if year_start_price > 0:
                    year_to_date_growth = (current_price - year_start_price) / year_start_price * 100
                else:
                    year_to_date_growth = 0
            
            # 计算突破后10、20、30、40、50天的累计增长
            # 确保突破日期是字符串格式
            breakthrough_date_str = str(start_date_breakthrough)
            growth_at_days = self.calculate_growth_at_days(
                df_sorted, 
                breakthrough_date_str, 
                start_price,
                days_list=[10, 20, 30]
            )
            
            result = {
                'ts_code': ts_code,
                'start_date': start_date,
                'end_date': end_date,
                'breakthrough_date': start_date_breakthrough,
                'start_price': round(start_price, 2),
                'current_price': round(current_price, 2),
                'growth_rate': round(growth_rate, 2),
                'days': days_diff
            }
            
            # 添加年初价格和年初至今涨幅
            if year_start_price is not None:
                result['year_start_price'] = round(year_start_price, 2)
                result['year_to_date_growth'] = round(year_to_date_growth, 2)
            else:
                result['year_start_price'] = 0
                result['year_to_date_growth'] = 0
            
            # 添加突破后不同天数的累计增长数据
            result.update(growth_at_days)
            
            # 计算从突破日期开始往后10、20、30天的均线斜率
            ma_slopes = {}
            breakthrough_date_str = str(start_date_breakthrough)
            for ma_period in [10, 20, 30]:
                ma_col = f'ma{ma_period}'
                slope = self.calculate_ma_slope(df_sorted, breakthrough_date_str, ma_col, days=ma_period)
                if slope is not None:
                    ma_slopes[f'ma{ma_period}_slope'] = round(slope, 4)
                else:
                    ma_slopes[f'ma{ma_period}_slope'] = 0.0
            
            # 计算从突破日期开始往后10、20、30日的最高价格
            max_prices = {}
            for days in [10, 20, 30]:
                max_price = self.calculate_max_price(df_sorted, breakthrough_date_str, days)
                if max_price is not None:
                    max_prices[f'max_price_{days}d'] = round(max_price, 2)
                else:
                    max_prices[f'max_price_{days}d'] = 0.0
            
            # 添加均线斜率和最高价格数据
            result.update(ma_slopes)
            result.update(max_prices)
            
            return result
            
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
        
        # 确保数值字段为正确的数值类型，以便排序
        numeric_columns = ['growth_rate', 'days', 'year_to_date_growth', 
                          'growth_10d', 'growth_20d', 'growth_30d', 'growth_40d', 'growth_50d',
                          'ma10_slope', 'ma20_slope', 'ma30_slope',
                          'max_price_10d', 'max_price_20d', 'max_price_30d']
        for col in numeric_columns:
            if col in result_df.columns:
                result_df[col] = pd.to_numeric(result_df[col], errors='coerce')
        
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
            # 获取前缀，如果有多个前缀，取第一个
            prefix = self.prefixes[0] if self.prefixes else ''
            if prefix:
                filename = f'{prefix}_120ma_breakthrough_{today}.csv'
            else:
                filename = f'120ma_breakthrough_{today}.csv'
        
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"\n结果已保存至: {filename}")
        
        # 显示前20条结果
        print("\n前20条结果:")
        print(result_df.head(20).to_string(index=False))


def main(prefixes=None, min_price=1.0):
    """
    主函数
    :param prefixes: 文件前缀列表，默认为None（使用默认的['sh', 'sz']）
                     可以传入 ['sh', 'sz'] 或 ['sh'] 或 ['sz'] 等
    :param min_price: 最小价格阈值，过滤掉start_price小于此值的股票，默认为None（不过滤）
    """
    analyzer = Analyze120MA(prefixes=prefixes, min_price=min_price)

    # 测试流程
    result_df = analyzer.analyze_stock(filepath='~/abu/data/csv/hk09992_20220606_20250624')

    # 分析所有股票
    result_df = analyzer.analyze_all()

    # 保存结果
    if not result_df.empty:
        analyzer.save_results(result_df)
    
    return result_df


if __name__ == '__main__':
    import time
    start = time.time()
    
    result = main('hk')
    
    print(f"\n处理完成，耗时 {time.time() - start:.2f} 秒")

