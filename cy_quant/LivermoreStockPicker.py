"""
利弗莫尔选股工具
按照利弗莫尔选股标准筛选股票：
1. close > 60日最高
2. close > ma20, ma60, ma120
3. 均线多头: ma20 > ma60 > ma120
4. 涨幅: 近20日涨幅（个股部分，板块和市场平均需要额外数据）
5. 成交量: volume > ma_volume_20
"""

import pandas as pd
import numpy as np
import os
import glob
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')


class LivermoreStockPicker:
    """利弗莫尔选股器"""
    
    def __init__(self, prefixes=None, csv_dir=None, test_mode=False, test_date=None):
        """
        初始化
        :param prefixes: 文件前缀列表，默认为['sh', 'sz']
        :param csv_dir: CSV文件目录，默认为~/abu/data/csv
        :param test_mode: 是否开启测试模式（模拟历史日期选股）
        :param test_date: 测试模式下的模拟日期，格式'YYYYMMDD'或datetime，如'20250801'
        """
        self.csv_dir = csv_dir if csv_dir else os.path.expanduser('~/abu/data/csv')
        self.results = []
        # 如果没有指定前缀，默认使用sh和sz
        if prefixes is None:
            prefixes = ['sh', 'sz']
        self.prefixes = prefixes if isinstance(prefixes, list) else [prefixes]
        
        # 测试模式设置
        self.test_mode = test_mode
        self.test_date = None
        if test_mode and test_date:
            if isinstance(test_date, str):
                self.test_date = test_date
            elif isinstance(test_date, datetime):
                self.test_date = test_date.strftime('%Y%m%d')
            else:
                raise ValueError('test_date 必须是字符串(YYYYMMDD)或datetime对象')
        
        if self.test_mode:
            print(f"【测试模式】模拟日期: {self.test_date}")
            # 计算1个月后的日期用于收益统计
            test_dt = datetime.strptime(self.test_date, '%Y%m%d')
            # 简单加30天作为1个月后
            from datetime import timedelta
            self.test_date_1m_later = (test_dt + timedelta(days=30)).strftime('%Y%m%d')
            print(f"【测试模式】将统计至: {self.test_date_1m_later} 的收益")
    
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
                if f not in all_files:
                    all_files.append(f)
        
        # 去重并过滤：只保留符合命名格式的文件（指定前缀开头，包含下划线和日期）
        valid_files = []
        for f in all_files:
            filename = os.path.basename(f)
            name_without_ext = filename.replace('.csv', '')
            parts = name_without_ext.split('_')
            if len(parts) >= 3 and any(name_without_ext.startswith(prefix) for prefix in self.prefixes):
                valid_files.append(f)
        
        # 同一股票可能有多个文件（不同日期范围），只保留结束日期最新的文件
        stock_to_file = {}
        for f in valid_files:
            filename = os.path.basename(f).replace('.csv', '')
            parts = filename.split('_')
            if len(parts) >= 3:
                stock_key = parts[0]  # sh600000, sz301363 等
                end_date = parts[2]
                if stock_key not in stock_to_file or end_date > stock_to_file[stock_key][1]:
                    stock_to_file[stock_key] = (f, end_date)
        
        valid_files = [v[0] for v in stock_to_file.values()]
        print(f"找到 {len(valid_files)} 个股票数据文件（同一股票仅保留最新数据）")
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
    
    def calculate_indicators(self, df):
        """
        计算所有需要的技术指标
        :param df: 包含date/trade_date、close、high、low、volume的DataFrame
        :return: 添加了所有指标的DataFrame
        """
        df = df.copy()
        
        # 统一日期列名
        if 'date' in df.columns and 'trade_date' not in df.columns:
            df = df.rename(columns={'date': 'trade_date'})
        
        # 确保数据按日期排序
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        # 计算均线
        df['ma20'] = df['close'].rolling(window=20, min_periods=20).mean()
        df['ma60'] = df['close'].rolling(window=60, min_periods=60).mean()
        df['ma120'] = df['close'].rolling(window=120, min_periods=120).mean()
        
        # 填充NaN值（用close值填充）
        df['ma20'] = df['ma20'].fillna(df['close'])
        df['ma60'] = df['ma60'].fillna(df['close'])
        df['ma120'] = df['ma120'].fillna(df['close'])
        
        # 计算20日均线斜率
        # 10日斜率：过去10天的平均日变化，用于判断中期趋势
        # 3日斜率：过去3天的平均日变化，用于判断近期是否拐头向下
        df['ma20_slope_10d'] = (df['ma20'] - df['ma20'].shift(10)) / 10
        df['ma20_slope_10d'] = df['ma20_slope_10d'].fillna(0)
        df['ma20_slope_3d'] = (df['ma20'] - df['ma20'].shift(3)) / 3
        df['ma20_slope_3d'] = df['ma20_slope_3d'].fillna(0)
        # 主斜率用10日，需同时满足10日和3日斜率都>0
        df['ma20_slope'] = df['ma20_slope_10d']
        
        # 计算60日最高价（不含当天，即前60日的最高价，用于判断"突破60日高点"）
        # 利弗莫尔：close > 60日最高 = 收盘价突破前60日的最高点
        df['high_60'] = df['high'].shift(1).rolling(window=60, min_periods=60).max()
        df['high_60'] = df['high_60'].fillna(df['high'])
        
        # 计算20日均量
        if 'volume' in df.columns:
            df['ma_volume_20'] = df['volume'].rolling(window=20, min_periods=20).mean()
            df['ma_volume_20'] = df['ma_volume_20'].fillna(df['volume'])
        else:
            df['ma_volume_20'] = 0
        
        # 计算近20日涨幅
        if len(df) >= 20:
            df['growth_20d'] = ((df['close'] - df['close'].shift(20)) / df['close'].shift(20) * 100).fillna(0)
        else:
            df['growth_20d'] = 0
        
        return df
    
    def check_livermore_criteria(self, df, debug=False):
        """
        检查利弗莫尔选股标准
        :param df: 包含所有指标的DataFrame（必须已过滤到目标日期）
        :param debug: 是否打印调试信息
        :return: 是否符合所有条件的布尔值，以及详细信息字典
        """
        if df is None or df.empty:
            return False, {}
        
        # 确保数据按日期排序
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        # 需要至少120条数据才能有有效的指标
        if len(df) < 120:
            return False, {'reason': '数据不足120天'}
        
        # 获取最后一天的数据（即"当前日期"的数据）
        last_row = df.iloc[-1]
        current_date = last_row['trade_date']
        current_close = last_row['close']
        current_ma20 = last_row['ma20']
        current_ma60 = last_row['ma60']
        current_ma120 = last_row['ma120']
        current_ma20_slope = last_row['ma20_slope']
        current_ma20_slope_3d = last_row['ma20_slope_3d']
        current_high_60 = last_row['high_60']
        current_volume = last_row.get('volume', 0)
        current_ma_volume_20 = last_row['ma_volume_20']
        growth_20d = last_row['growth_20d']
        
        # 【测试模式】验证当前日期是否正确
        if self.test_mode and self.test_date:
            if str(current_date) != str(self.test_date):
                if debug:
                    print(f"    警告: 当前日期 {current_date} 与测试日期 {self.test_date} 不一致")
        
        # 获取前一天的均线值（用于判断均线方向）
        prev_ma20 = df.iloc[-2]['ma20'] if len(df) > 1 else current_ma20
        prev_ma60 = df.iloc[-2]['ma60'] if len(df) > 1 else current_ma60
        prev_ma120 = df.iloc[-2]['ma120'] if len(df) > 1 else current_ma120
        
        # 检查条件
        # 注意：close >= high_60 表示收盘价达到或超过60日最高价（突破60日高点）
        # 注意：high_60 包含当天，所以 close <= high（当天最高）<= high_60，只有创新高时 close 才可能接近 high_60
        criteria = {
            'close_gt_high60': current_close >= current_high_60,  # 条件1: close >= 60日最高（突破或达到60日高点）
            'close_gt_ma20': current_close > current_ma20,      # 条件2: close > ma20
            'close_gt_ma60': current_close > current_ma60,      # 条件2: close > ma60
            'close_gt_ma120': current_close > current_ma120,    # 条件2: close > ma120
            'ma20_gt_ma60': current_ma20 > current_ma60,         # 条件3: ma20 > ma60
            'ma60_gt_ma120': current_ma60 > current_ma120,       # 条件3: ma60 > ma120
            'ma20_slope_positive': current_ma20_slope > 0 and current_ma20_slope_3d > 0,  # 10日、3日斜率都>0，过滤斜率向下或近期拐头的股票
            'ma60_upward': current_ma60 >= prev_ma60,            # ma60朝上
            'ma120_upward': current_ma120 >= prev_ma120,         # ma120朝上
            'volume_gt_ma_volume': current_volume > current_ma_volume_20 if current_ma_volume_20 > 0 else True,  # 条件5: volume > ma_volume_20
            'growth_20d': growth_20d  # 近20日涨幅
        }
        
        # 判断是否符合所有条件
        # 注意：close > 60日最高 这个条件非常严格，因为收盘价要大于60日最高价（不包括等于）
        # 实际上收盘价等于60日最高价的情况也很少见，所以这个条件可能太严格了
        # 可以考虑改为 close >= high_60 * 0.98 或类似的放宽条件
        all_conditions_met = (
            criteria['close_gt_high60'] and
            criteria['close_gt_ma20'] and
            criteria['close_gt_ma60'] and
            criteria['close_gt_ma120'] and
            criteria['ma20_gt_ma60'] and
            criteria['ma60_gt_ma120'] and
            criteria['ma20_slope_positive'] and  # 20日均线斜率>0，过滤斜率向下的股票
            criteria['volume_gt_ma_volume']
        )
        
        # 添加详细信息
        details = {
            'current_close': current_close,
            'current_ma20': current_ma20,
            'current_ma60': current_ma60,
            'current_ma120': current_ma120,
            'current_ma20_slope': current_ma20_slope,
            'current_ma20_slope_3d': current_ma20_slope_3d,
            'high_60': current_high_60,
            'volume': current_volume,
            'ma_volume_20': current_ma_volume_20,
            'growth_20d': growth_20d,
            'trade_date': last_row['trade_date']
        }
        details.update(criteria)
        
        return all_conditions_met, details
    
    def analyze_stock(self, filepath, idx=0, debug=False):
        """
        分析单个股票文件
        :param filepath: 文件路径
        :param idx: 序号（用于调试输出）
        :param debug: 是否显示调试信息
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
            
            # 确保有必要的列
            required_columns = ['close', 'high']
            if 'date' in df.columns:
                df = df.rename(columns={'date': 'trade_date'})
            
            if 'trade_date' not in df.columns:
                return None
            
            for col in required_columns:
                if col not in df.columns:
                    return None
            
            # 【测试模式】过滤数据到模拟日期（将test_date作为"今天"）
            if self.test_mode and self.test_date:
                df['trade_date'] = df['trade_date'].astype(str)
                original_len = len(df)
                # 只保留到测试日期的数据（包含测试日期当天）
                df = df[df['trade_date'] <= self.test_date]
                
                if df.empty:
                    if debug and idx <= 5:
                        print(f"  [{idx}] {ts_code} 在 {self.test_date} 之前无数据")
                    return None
                
                # 检查是否有足够的数据（至少120天才能计算ma120）
                if len(df) < 120:
                    if debug and idx <= 5:
                        print(f"  [{idx}] {ts_code} 数据不足: 只有 {len(df)} 天，需要120天")
                    return None
                
                # 检查测试日期当天是否有数据
                test_day_data = df[df['trade_date'] == self.test_date]
                if test_day_data.empty:
                    if debug and idx <= 5:
                        print(f"  [{idx}] {ts_code} 在 {self.test_date} 当天无交易数据")
                    return None
                
                if debug and idx <= 3:
                    print(f"  [{idx}] {ts_code} 数据范围: {df['trade_date'].iloc[0]} ~ {df['trade_date'].iloc[-1]} (共{len(df)}天, 过滤前{original_len}天)")
            
            # 计算技术指标
            df_with_indicators = self.calculate_indicators(df)
            
            if df_with_indicators is None or df_with_indicators.empty:
                return None
            
            # 检查利弗莫尔选股标准（基于"当前日期"即test_date）
            meets_criteria, details = self.check_livermore_criteria(df_with_indicators, debug=debug)
            
            if not meets_criteria:
                return None
            
            # 【测试模式】计算未来1个月收益
            future_return_1m = None
            if self.test_mode and self.test_date:
                future_return_1m = self._calculate_future_return(filepath, details['trade_date'], details['current_close'])
            
            # 构建结果字典
            result = {
                'ts_code': ts_code,
                'stock_code': ts_code.split('.')[0] if '.' in ts_code else ts_code,
                'trade_date': details['trade_date'],
                'close': details['current_close'],
                'ma20': details['current_ma20'],
                'ma60': details['current_ma60'],
                'ma120': details['current_ma120'],
                'high_60': details['high_60'],
                'volume': details['volume'],
                'ma_volume_20': details['ma_volume_20'],
                'growth_20d': details['growth_20d'],
                'close_gt_high60': details['close_gt_high60'],
                'close_gt_ma20': details['close_gt_ma20'],
                'close_gt_ma60': details['close_gt_ma60'],
                'close_gt_ma120': details['close_gt_ma120'],
                'ma20_gt_ma60': details['ma20_gt_ma60'],
                'ma60_gt_ma120': details['ma60_gt_ma120'],
                'ma20_slope': details['current_ma20_slope'],
                'ma20_slope_positive': details['ma20_slope_positive'],
                'volume_gt_ma_volume': details['volume_gt_ma_volume']
            }
            
            # 【测试模式】添加未来收益
            if future_return_1m is not None:
                result['future_close_1m'] = future_return_1m['close']
                result['future_return_1m'] = future_return_1m['return_rate']
                result['future_days'] = future_return_1m['days']
            
            return result
            
        except Exception as e:
            print(f"分析股票文件 {filepath} 时出错: {e}")
            return None
    
    def _calculate_future_return(self, filepath, buy_date, buy_price):
        """
        【测试模式】计算买入后1个月的收益
        :param filepath: 股票文件路径
        :param buy_date: 买入日期
        :param buy_price: 买入价格
        :return: 包含未来价格、收益率、持有天数的字典
        """
        try:
            # 重新读取完整数据
            try:
                df = pd.read_csv(filepath, encoding='utf-8-sig')
            except:
                try:
                    df = pd.read_csv(filepath, encoding='gbk')
                except:
                    df = pd.read_csv(filepath, encoding='utf-8')
            
            if 'date' in df.columns:
                df = df.rename(columns={'date': 'trade_date'})
            
            df['trade_date'] = df['trade_date'].astype(str)
            
            # 找到买入日期后的数据
            df_after_buy = df[df['trade_date'] > buy_date]
            if df_after_buy.empty:
                return None
            
            # 找到1个月后的数据（或尽可能接近的）
            df_after_buy = df_after_buy.sort_values('trade_date')
            
            # 目标日期：买入后约30天
            target_date = (datetime.strptime(buy_date, '%Y%m%d') + timedelta(days=30)).strftime('%Y%m%d')
            
            # 找最接近目标日期的交易日
            df_target = df_after_buy[df_after_buy['trade_date'] <= target_date]
            if df_target.empty:
                # 如果30天内没有数据，取最后一个可用数据
                future_row = df_after_buy.iloc[-1]
            else:
                future_row = df_target.iloc[-1]
            
            future_close = float(future_row['close'])
            future_date = future_row['trade_date']
            
            # 计算收益率
            return_rate = ((future_close - buy_price) / buy_price) * 100
            
            # 计算持有天数
            days = (datetime.strptime(future_date, '%Y%m%d') - datetime.strptime(buy_date, '%Y%m%d')).days
            
            return {
                'close': future_close,
                'return_rate': return_rate,
                'days': days,
                'sell_date': future_date
            }
        except Exception as e:
            print(f"计算未来收益失败: {e}")
            return None
    
    def analyze_all(self, debug=False, sample_size=None):
        """
        分析所有股票文件
        :param debug: 是否显示调试信息
        :param sample_size: 只处理前N个文件（用于测试）
        :return: 符合条件的股票DataFrame
        """
        stock_files = self.get_stock_files()
        
        if not stock_files:
            print("没有找到股票数据文件")
            return pd.DataFrame()
        
        if sample_size:
            stock_files = stock_files[:sample_size]
            print(f"\n测试模式：只处理前 {sample_size} 个文件")
        
        print(f"\n开始分析 {len(stock_files)} 个股票文件...")
        print("="*80)
        
        results = []
        stats = {
            'total': 0,
            'parse_failed': 0,
            'read_failed': 0,
            'no_columns': 0,
            'insufficient_data': 0,
            'criteria_failed': 0,
            'passed': 0
        }
        
        for idx, filepath in enumerate(stock_files, 1):
            if idx % 100 == 0:
                print(f"已处理 {idx}/{len(stock_files)} 个文件...")
            
            stats['total'] += 1
            
            # 【测试模式】显示调试信息
            if self.test_mode and debug and idx <= 3:
                print(f"  [{idx}] 处理文件: {os.path.basename(filepath)}")
            
            # 调用 analyze_stock 进行完整分析
            result = self.analyze_stock(filepath, idx=idx, debug=debug)
            
            if result is None:
                # 分析失败，增加失败计数
                stats['criteria_failed'] += 1
                continue
            
            # 符合条件
            stats['passed'] += 1
            results.append(result)
        
        # 打印统计信息
        print(f"\n分析完成！统计信息:")
        print("="*80)
        print(f"总文件数: {stats['total']}")
        print(f"解析文件名失败: {stats['parse_failed']}")
        print(f"读取文件失败: {stats['read_failed']}")
        print(f"缺少必要列: {stats['no_columns']}")
        print(f"数据不足: {stats['insufficient_data']}")
        print(f"不满足条件: {stats['criteria_failed']}")
        print(f"符合条件的股票: {stats['passed']}")
        print("="*80)
        
        if results:
            df = pd.DataFrame(results)
            # 按涨幅排序
            df = df.sort_values('growth_20d', ascending=False).reset_index(drop=True)
            return df
        else:
            return pd.DataFrame()
    
    def save_results(self, df, filename=None):
        """
        保存结果到CSV文件
        :param df: 结果DataFrame
        :param filename: 输出文件名，如果为None则自动生成
        """
        if df is None or df.empty:
            print("没有数据可保存")
            return
        
        if filename is None:
            if self.test_mode and self.test_date:
                filename = f"livermore_stocks_test_{self.test_date}.csv"
            else:
                timestamp = datetime.now().strftime('%Y%m%d')
                filename = f"livermore_stocks_{timestamp}.csv"
        
        # 确保文件名在cy_quant目录下
        if not os.path.dirname(filename):
            filename = os.path.join('cy_quant', filename)
        
        # 确保目录存在
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        # 选择要保存的列
        columns_to_save = [
            'ts_code',
            'stock_code',
            'trade_date',
            'close',
            'ma20',
            'ma60',
            'ma120',
            'high_60',
            'volume',
            'ma_volume_20',
            'growth_20d',
            'close_gt_high60',
            'close_gt_ma20',
            'close_gt_ma60',
            'close_gt_ma120',
            'ma20_gt_ma60',
            'ma60_gt_ma120',
            'ma20_slope',
            'ma20_slope_positive',
            'volume_gt_ma_volume'
        ]
        
        # 【测试模式】添加未来收益列
        if self.test_mode:
            test_columns = ['future_close_1m', 'future_return_1m', 'future_days']
            columns_to_save.extend(test_columns)
        
        # 只保存存在的列
        available_columns = [col for col in columns_to_save if col in df.columns]
        df_to_save = df[available_columns].copy()
        
        df_to_save.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"\n结果已保存至: {filename}")
        print(f"共 {len(df_to_save)} 只股票")


def main(prefixes=None, csv_dir=None, output_file=None, debug=False, sample_size=None, 
         test_mode=False, test_date=None):
    """
    主函数
    :param prefixes: 文件前缀列表，默认为None（使用默认的['sh', 'sz']）
    :param csv_dir: CSV文件目录，默认为None（使用默认的~/abu/data/csv）
    :param output_file: 输出文件名，默认为None（自动生成）
    :param debug: 是否显示调试信息
    :param sample_size: 只处理前N个文件（用于测试）
    :param test_mode: 是否开启测试模式（模拟历史日期选股）
    :param test_date: 测试模式下的模拟日期，格式'YYYYMMDD'，如'20250801'
    """
    picker = LivermoreStockPicker(prefixes=prefixes, csv_dir=csv_dir, 
                                   test_mode=test_mode, test_date=test_date)
    
    # 分析所有股票
    result_df = picker.analyze_all(debug=debug, sample_size=sample_size)
    
    # 保存结果
    if not result_df.empty:
        picker.save_results(result_df, output_file)
        
        # 打印前10只股票
        print("\n前10只符合条件的股票:")
        print("="*80)
        # 【测试模式】显示未来收益列
        if test_mode and 'future_return_1m' in result_df.columns:
            display_columns = ['ts_code', 'stock_code', 'close', 'growth_20d', 'future_return_1m']
        else:
            display_columns = ['ts_code', 'stock_code', 'close', 'growth_20d', 'ma20', 'ma60', 'ma120']
        available_display_cols = [col for col in display_columns if col in result_df.columns]
        print(result_df[available_display_cols].head(10).to_string(index=False))
        
        # 打印统计摘要
        print("\n选股结果统计:")
        print("="*80)
        print(f"符合条件的股票总数: {len(result_df)}")
        if 'growth_20d' in result_df.columns:
            print(f"平均20日涨幅: {result_df['growth_20d'].mean():.2f}%")
            print(f"最大20日涨幅: {result_df['growth_20d'].max():.2f}%")
            print(f"最小20日涨幅: {result_df['growth_20d'].min():.2f}%")
        
        # 【测试模式】打印收益统计
        if test_mode and 'future_return_1m' in result_df.columns:
            print("\n【测试模式】未来1个月收益统计:")
            print("="*80)
            valid_returns = result_df['future_return_1m'].dropna()
            if not valid_returns.empty:
                print(f"平均收益率: {valid_returns.mean():.2f}%")
                print(f"最大收益率: {valid_returns.max():.2f}%")
                print(f"最小收益率: {valid_returns.min():.2f}%")
                print(f"正收益股票数: {(valid_returns > 0).sum()} / {len(valid_returns)}")
                print(f"胜率: {(valid_returns > 0).sum() / len(valid_returns) * 100:.1f}%")
    else:
        print("\n⚠️  没有找到符合条件的股票")
        print("="*80)
        print("可能的原因：")
        print("1. 选股条件过于严格")
        print("2. 当前市场环境下没有股票同时满足所有条件")
        if test_mode:
            print(f"3. 测试日期 {test_date} 可能没有足够的数据（需要至少120天的历史数据）")
        print("\n建议：")
        print("- 可以尝试放宽部分条件，比如将 'close >= 60日最高' 改为 'close >= 60日最高 * 0.98'")
        print("- 或者检查数据是否足够（需要至少120天的数据）")
        
        # 即使没有符合条件的股票，也保存一个空的CSV文件（包含列名）以便后续分析
        if output_file is None:
            if test_mode and test_date:
                output_file = f"livermore_stocks_test_{test_date}.csv"
            else:
                timestamp = datetime.now().strftime('%Y%m%d')
                output_file = f"livermore_stocks_{timestamp}.csv"
        
        if not os.path.dirname(output_file):
            output_file = os.path.join('cy_quant', output_file)
        
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        # 创建空的DataFrame，包含所有列名
        empty_columns = [
            'ts_code', 'stock_code', 'trade_date', 'close', 'ma20', 'ma60', 'ma120',
            'high_60', 'volume', 'ma_volume_20', 'growth_20d',
            'close_gt_high60', 'close_gt_ma20', 'close_gt_ma60', 'close_gt_ma120',
            'ma20_gt_ma60', 'ma60_gt_ma120', 'ma20_slope', 'ma20_slope_positive', 'volume_gt_ma_volume'
        ]
        if test_mode:
            empty_columns.extend(['future_close_1m', 'future_return_1m', 'future_days'])
        empty_df = pd.DataFrame(columns=empty_columns)
        empty_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\n已创建空的结果文件: {output_file}（包含列名，便于后续分析）")
    
    return result_df


if __name__ == '__main__':
    import argparse
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='利弗莫尔选股工具')
    parser.add_argument('--test-mode', action='store_true', help='开启测试模式（模拟历史日期选股）')
    parser.add_argument('--test-date', type=str, default=None, help='测试模式日期，格式YYYYMMDD，如20250801')
    parser.add_argument('--sample-size', type=int, default=None, help='只处理前N个文件（用于测试）')
    parser.add_argument('--debug', action='store_true', help='显示调试信息')
    parser.add_argument('--all', action='store_true', help='分析全部股票（默认只测试50个）')
    args = parser.parse_args()
    
    import time
    start = time.time()
    
    # 确定样本大小
    # sample_size = None if args.all else (args.sample_size or 50)
    sample_size = None

    # 运行主函数
    args.test_mode = True
    args.test_date = '20250801'

    if args.test_mode:
        if not args.test_date:
            print("错误: 测试模式需要指定 --test-date 参数，如 --test-date 20250801")
            exit(1)
        print(f"【测试模式】模拟日期: {args.test_date}")
        result_df = main(test_mode=True, test_date=args.test_date, debug=args.debug, sample_size=sample_size)
    else:
        # 正常模式
        print(f"【正常模式】使用当前日期: {datetime.now().strftime('%Y%m%d')}")
        result_df = main(debug=args.debug, sample_size=sample_size)
    
    end = time.time()
    print(f"\n总耗时: {end - start:.2f} 秒")
