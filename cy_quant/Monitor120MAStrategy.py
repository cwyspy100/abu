"""
监控120均线策略
扫描~/abu/data/csv/目录下的股票文件
实现买入和加仓策略：
1. 超过120日均线，10日之后买入（底仓）
2. 回踩时加仓，加仓条件：
   - 底仓买入后，股价缩量回调至60日均线附近（距离均线±2%）
   - 回调时成交量≤5日均量的0.5倍（抛压小）
   - 回调后次日放量反弹（阳线收盘价站上5日均线）
"""

import pandas as pd
import numpy as np
import os
import glob
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')


class Monitor120MAStrategy:
    """120均线策略监控器"""
    
    def __init__(self, prefixes=None, min_price=1.0, filter_csv=None):
        """
        初始化
        :param prefixes: 文件前缀列表，默认为['sh', 'sz']
        :param min_price: 最小价格阈值，过滤掉start_price小于此值的股票
        :param filter_csv: 筛选CSV文件路径，如果提供，只处理该文件中列出的股票
        """
        self.csv_dir = os.path.expanduser('~/abu/data/csv')
        # 如果没有指定前缀，默认使用sh和sz
        if prefixes is None:
            prefixes = ['sh', 'sz']
        self.prefixes = prefixes if isinstance(prefixes, list) else [prefixes]
        self.min_price = min_price
        self.filter_csv = filter_csv
        # 存储已买入的股票信息 {ts_code: {'buy_date': date, 'buy_price': price}}
        self.positions = {}
        # 存储筛选股票列表 {(ts_code, start_date, end_date): filepath}
        self.filter_stocks = {}
        
        # 如果提供了筛选CSV文件，读取股票列表
        if self.filter_csv:
            self._load_filter_stocks()
    
    def _load_filter_stocks(self):
        """
        从筛选CSV文件中加载股票列表
        """
        try:
            filter_df = pd.read_csv(self.filter_csv, encoding='utf-8-sig')
            
            if filter_df.empty or 'ts_code' not in filter_df.columns:
                print(f"警告: 筛选CSV文件 {self.filter_csv} 为空或缺少ts_code列")
                return
            
            # 获取所有股票文件
            all_files = []
            patterns = []
            for prefix in self.prefixes:
                patterns.append(os.path.join(self.csv_dir, f'{prefix}*.csv'))
                patterns.append(os.path.join(self.csv_dir, f'{prefix}*'))
            
            for pattern in patterns:
                files = glob.glob(pattern)
                all_files.extend(files)
            
            # 去重
            all_files = list(set(all_files))
            
            # 将股票代码转换为文件名格式
            for _, row in filter_df.iterrows():
                ts_code = str(row['ts_code'])
                start_date = str(row.get('start_date', ''))
                end_date = str(row.get('end_date', ''))
                
                # 解析股票代码：03918.HK -> hk03918
                if '.' in ts_code:
                    code, exchange = ts_code.split('.')
                    exchange_lower = exchange.lower()
                    
                    # 根据交易所确定前缀
                    if exchange_lower == 'sh':
                        file_prefix = 'sh'
                    elif exchange_lower == 'sz':
                        file_prefix = 'sz'
                    elif exchange_lower == 'hk':
                        file_prefix = 'hk'
                    elif exchange_lower == 'us':
                        file_prefix = 'us'
                    else:
                        file_prefix = exchange_lower
                    
                    file_code = f"{file_prefix}{code}"
                else:
                    # 如果没有点，尝试从文件名推断
                    file_code = ts_code
                
                # 查找匹配的文件
                for filepath in all_files:
                    filename = os.path.basename(filepath)
                    name_without_ext = filename.replace('.csv', '')
                    
                    # 检查文件名是否匹配
                    if name_without_ext.startswith(file_code):
                        parts = name_without_ext.split('_')
                        if len(parts) >= 3:
                            file_start_date = parts[1]
                            file_end_date = parts[2]
                            
                            # 如果提供了日期，需要匹配；否则只要代码匹配即可
                            if start_date and end_date:
                                if file_start_date == start_date and file_end_date == end_date:
                                    self.filter_stocks[(ts_code, start_date, end_date)] = filepath
                                    break
                            else:
                                # 如果没有日期要求，使用第一个匹配的文件
                                if (ts_code, start_date, end_date) not in self.filter_stocks:
                                    self.filter_stocks[(ts_code, start_date, end_date)] = filepath
            
            print(f"从筛选CSV文件加载了 {len(self.filter_stocks)} 只股票")
            
        except Exception as e:
            print(f"加载筛选CSV文件失败 {self.filter_csv}: {e}")
            import traceback
            traceback.print_exc()
    
    def get_stock_files(self):
        """
        获取股票文件列表
        如果提供了筛选CSV文件，只返回筛选文件中的股票
        否则返回所有指定前缀开头的文件
        :return: 文件路径列表
        """
        # 如果提供了筛选CSV文件，只返回筛选的股票文件
        if self.filter_csv and self.filter_stocks:
            valid_files = list(self.filter_stocks.values())
            print(f"从筛选CSV文件找到 {len(valid_files)} 个股票数据文件")
            return valid_files
        
        # 否则返回所有符合条件的文件
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
            if len(parts) >= 3 and any(name_without_ext.startswith(prefix) for prefix in self.prefixes):
                valid_files.append(f)
        
        print(f"找到 {len(valid_files)} 个股票数据文件")
        return valid_files
    
    def parse_filename(self, filepath):
        """
        从文件名解析股票代码和日期范围
        :param filepath: 文件路径
        :return: (股票代码, 开始日期, 结束日期) 或 None
        """
        filename = os.path.basename(filepath)
        
        if filename.endswith('.csv'):
            filename = filename[:-4]
        
        parts = filename.split('_')
        if len(parts) >= 3:
            code_part = parts[0]
            start_date = parts[1]
            end_date = parts[2]
            
            prefix_to_exchange = {
                'sh': 'SH',
                'sz': 'SZ',
                'hk': 'HK',
                'us': 'US'
            }
            
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
    
    def calculate_moving_averages(self, df):
        """
        计算各种均线和成交量均线
        :param df: 包含close和volume的DataFrame
        :return: 添加了均线列的DataFrame
        """
        df = df.copy()
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        # 计算均线
        df['ma5'] = df['close'].rolling(window=5, min_periods=5).mean()
        df['ma60'] = df['close'].rolling(window=60, min_periods=60).mean()
        df['ma120'] = df['close'].rolling(window=120, min_periods=120).mean()
        
        # 填充前119天的ma120为close值
        df['ma120'] = df['ma120'].fillna(df['close'])
        
        # 计算5日均量
        if 'volume' in df.columns:
            df['vol_ma5'] = df['volume'].rolling(window=5, min_periods=5).mean()
        else:
            df['vol_ma5'] = np.nan
        
        return df
    
    def find_breakthrough(self, df):
        """
        找出最后一次超过120日均线的信息
        :param df: 包含ma120和close的DataFrame
        :return: (突破日期, 突破价格, 当前价格, 持续天数) 或 None
        """
        if df is None or df.empty or 'ma120' not in df.columns or 'close' not in df.columns:
            return None
        
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        if len(df) < 120:
            return None
        
        df['above_ma120'] = df['close'] > df['ma120']
        
        # 最后一天必须在120日均线上方
        if not df.iloc[-1]['above_ma120']:
            return None
        
        # 找到连续区间的开始点
        start_idx = None
        for i in range(len(df) - 2, -1, -1):
            if not df.iloc[i]['above_ma120']:
                start_idx = i + 1
                break
        
        if start_idx is None:
            start_idx = 0
        
        start_date = df.iloc[start_idx]['trade_date']
        start_price = df.iloc[start_idx]['close']
        current_price = df.iloc[-1]['close']
        days_diff = len(df) - start_idx
        
        return start_date, start_price, current_price, days_diff
    
    def check_buy_signal(self, df, breakthrough_date, breakthrough_price, days_diff):
        """
        检查是否满足买入条件
        条件：超过120日均线，10日之后
        :param df: DataFrame
        :param breakthrough_date: 突破日期
        :param breakthrough_price: 突破价格
        :param days_diff: 持续天数
        :return: True/False
        """
        # 必须超过10天
        if days_diff < 10:
            return False
        
        # 价格过滤
        if self.min_price is not None and breakthrough_price < self.min_price:
            return False
        
        return True
    
    def check_add_position_signal(self, df, buy_date, buy_price):
        """
        检查是否满足加仓条件
        条件：
        1. 底仓买入后，股价缩量回调至60日均线附近（距离均线±2%）
        2. 回调时成交量≤5日均量的0.5倍（抛压小）
        3. 回调后次日放量反弹（阳线收盘价站上5日均线）
        :param df: DataFrame，已按日期排序
        :param buy_date: 买入日期
        :param buy_price: 买入价格
        :return: (是否满足加仓条件, 加仓日期, 加仓价格) 或 (False, None, None)
        """
        df = df.copy()
        df = df.sort_values('trade_date').reset_index(drop=True)
        df['trade_date'] = df['trade_date'].astype(str)
        
        # 找到买入日期在DataFrame中的位置
        buy_idx = None
        for idx, row in df.iterrows():
            if str(row['trade_date']) == str(buy_date):
                buy_idx = idx
                break
        
        if buy_idx is None or buy_idx >= len(df) - 1:
            return False, None, None
        
        # 需要至少60条数据才能计算60日均线
        if len(df) < 60:
            return False, None, None
        
        # 从买入日期之后开始检查
        # 检查最近几天的数据（最多检查最近30天）
        check_range = min(30, len(df) - buy_idx - 1)
        
        for i in range(buy_idx + 1, min(buy_idx + check_range + 1, len(df) - 1)):
            # 检查第i天是否满足回调条件
            current_row = df.iloc[i]
            next_row = df.iloc[i + 1] if i + 1 < len(df) else None
            
            # 需要的数据列
            if pd.isna(current_row.get('ma60')) or pd.isna(current_row.get('vol_ma5')):
                continue
            
            if 'volume' not in current_row.index or pd.isna(current_row['volume']):
                continue
            
            # 条件1：股价回调至60日均线附近（距离均线±2%）
            ma60 = current_row['ma60']
            close_price = current_row['close']
            distance_pct = abs(close_price - ma60) / ma60 * 100
            
            if distance_pct > 2:
                continue
            
            # 条件2：回调时成交量≤5日均量的0.5倍
            volume = current_row['volume']
            vol_ma5 = current_row['vol_ma5']
            
            if vol_ma5 <= 0 or volume > vol_ma5 * 0.5:
                continue
            
            # 条件3：回调后次日放量反弹（阳线收盘价站上5日均线）
            if next_row is None:
                continue
            
            if pd.isna(next_row.get('ma5')) or pd.isna(next_row.get('close')):
                continue
            
            # 次日必须是阳线（收盘价>开盘价）
            if 'open' in next_row.index:
                if next_row['close'] <= next_row['open']:
                    continue
            
            # 次日收盘价站上5日均线
            if next_row['close'] <= next_row['ma5']:
                continue
            
            # 次日放量（成交量大于5日均量）
            if 'volume' in next_row.index and 'vol_ma5' in next_row.index:
                if pd.isna(next_row['volume']) or pd.isna(next_row['vol_ma5']):
                    continue
                if next_row['volume'] <= next_row['vol_ma5']:
                    continue
            
            # 所有条件满足，返回加仓信号
            add_date = next_row['trade_date']
            add_price = next_row['close']
            return True, add_date, add_price
        
        return False, None, None
    
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
            
            # 读取CSV文件
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
            
            # 计算均线
            df_with_ma = self.calculate_moving_averages(df)
            
            if df_with_ma is None or df_with_ma.empty:
                return None
            
            # 找出突破信息
            breakthrough_info = self.find_breakthrough(df_with_ma)
            
            if breakthrough_info is None:
                return None
            
            breakthrough_date, breakthrough_price, current_price, days_diff = breakthrough_info
            
            # 检查买入信号
            buy_signal = self.check_buy_signal(df_with_ma, breakthrough_date, breakthrough_price, days_diff)
            
            result = {
                'ts_code': ts_code,
                'breakthrough_date': breakthrough_date,
                'breakthrough_price': round(breakthrough_price, 2),
                'current_price': round(current_price, 2),
                'days': days_diff,
                'buy_signal': buy_signal
            }
            
            # 如果满足买入条件，检查加仓信号
            if buy_signal:
                # 检查是否已经买入（从positions中查找）
                if ts_code in self.positions:
                    buy_date = self.positions[ts_code]['buy_date']
                    buy_price = self.positions[ts_code]['buy_price']
                else:
                    # 假设在突破后第10天买入
                    df_sorted = df_with_ma.sort_values('trade_date').reset_index(drop=True)
                    df_sorted['trade_date'] = df_sorted['trade_date'].astype(str)
                    
                    breakthrough_idx = None
                    for idx, row in df_sorted.iterrows():
                        if str(row['trade_date']) == str(breakthrough_date):
                            breakthrough_idx = idx
                            break
                    
                    if breakthrough_idx is not None and breakthrough_idx + 9 < len(df_sorted):
                        buy_idx = breakthrough_idx + 9  # 第10天买入
                        buy_date = df_sorted.iloc[buy_idx]['trade_date']
                        buy_price = df_sorted.iloc[buy_idx]['close']
                    else:
                        buy_date = breakthrough_date
                        buy_price = breakthrough_price
                
                # 检查加仓信号
                add_signal, add_date, add_price = self.check_add_position_signal(
                    df_with_ma, buy_date, buy_price
                )
                
                result['buy_date'] = buy_date
                result['buy_price'] = round(buy_price, 2)
                result['add_signal'] = add_signal
                if add_signal:
                    result['add_date'] = add_date
                    result['add_price'] = round(add_price, 2)
                else:
                    result['add_date'] = None
                    result['add_price'] = None
            else:
                result['buy_date'] = None
                result['buy_price'] = None
                result['add_signal'] = False
                result['add_date'] = None
                result['add_price'] = None
            
            return result
            
        except Exception as e:
            print(f"分析文件 {filepath} 时出错: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def monitor_all(self):
        """
        监控所有股票
        :return: 结果DataFrame
        """
        print("=" * 60)
        print("开始监控120均线策略")
        print("=" * 60)
        
        stock_files = self.get_stock_files()
        
        if not stock_files:
            print("未找到股票数据文件！")
            return pd.DataFrame()
        
        results = []
        for i, filepath in enumerate(stock_files):
            result = self.analyze_stock(filepath)
            if result:
                results.append(result)
            
            if (i + 1) % 50 == 0:
                print(f"已处理 {i + 1}/{len(stock_files)} 个文件...")
        
        if not results:
            print("未找到符合条件的股票")
            return pd.DataFrame()
        
        result_df = pd.DataFrame(results)
        
        # 确保数值字段为正确的数值类型
        numeric_columns = ['breakthrough_price', 'current_price', 'days', 'buy_price', 'add_price']
        for col in numeric_columns:
            if col in result_df.columns:
                result_df[col] = pd.to_numeric(result_df[col], errors='coerce')
        
        print(f"\n监控完成！共找到 {len(result_df)} 只股票")
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
            prefix = self.prefixes[0] if self.prefixes else ''
            if prefix:
                filename = f'{prefix}_120ma_strategy_{today}.csv'
            else:
                filename = f'120ma_strategy_{today}.csv'
        
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"\n结果已保存至: {filename}")
        
        # 显示买入信号和加仓信号
        buy_signals = result_df[result_df['buy_signal'] == True]
        add_signals = result_df[result_df['add_signal'] == True]
        
        print(f"\n买入信号: {len(buy_signals)} 只股票")
        if len(buy_signals) > 0:
            print("\n买入信号股票:")
            print(buy_signals[['ts_code', 'breakthrough_date', 'breakthrough_price', 'current_price', 'days']].to_string(index=False))
        
        print(f"\n加仓信号: {len(add_signals)} 只股票")
        if len(add_signals) > 0:
            print("\n加仓信号股票:")
            print(add_signals[['ts_code', 'buy_date', 'buy_price', 'add_date', 'add_price']].to_string(index=False))


def main(prefixes=None, min_price=1.0, filter_csv=None):
    """
    主函数
    :param prefixes: 文件前缀列表，默认为None（使用默认的['sh', 'sz']）
    :param min_price: 最小价格阈值，默认为1.0
    :param filter_csv: 筛选CSV文件路径，如果提供，只处理该文件中列出的股票
    """
    monitor = Monitor120MAStrategy(prefixes=prefixes, min_price=min_price, filter_csv=filter_csv)
    
    # 监控所有股票
    result_df = monitor.monitor_all()
    
    # 保存结果
    if not result_df.empty:
        monitor.save_results(result_df)
    
    return result_df


if __name__ == '__main__':
    import time
    start = time.time()
    
    # 使用筛选CSV文件（可以传入相对路径或绝对路径）
    # 示例：使用todolist目录下的CSV文件
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    filter_csv_path = os.path.join(project_root, 'todolist', 'hk_120ma_breakthrough_20251219.csv')
    
    # 如果文件不存在，尝试使用绝对路径
    if not os.path.exists(filter_csv_path):
        filter_csv_path = os.path.expanduser('~/mylearn/PycharmProjects/abu-master/todolist/hk_120ma_breakthrough_20251219.csv')
    
    result = main(prefixes=['hk'], min_price=1.0, filter_csv=filter_csv_path)
    
    print(f"\n处理完成，耗时 {time.time() - start:.2f} 秒")

