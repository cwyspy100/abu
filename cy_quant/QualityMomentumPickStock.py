"""
高质量+高动量因子选股策略
使用tushare接口获取A股数据，结合质量因子和动量因子进行选股

高质量因子指标：
1. ROE（净资产收益率）- 衡量盈利能力
2. ROA（总资产收益率）- 衡量资产使用效率
3. 毛利率 - 衡量盈利质量
4. 净利率 - 衡量盈利效率
5. 盈利增长率 - 衡量成长性

高动量因子指标：
1. 1个月收益率
2. 3个月收益率
3. 6个月收益率
4. 12个月收益率
5. 相对强度（相对于市场）
"""

import tushare as ts
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta
import time
import warnings
warnings.filterwarnings('ignore')


class QualityMomentumStockPicker:
    """高质量+高动量因子选股器"""
    
    def __init__(self, token=None, use_local_only=False):
        """
        初始化选股器
        :param token: tushare token，如果为None则从配置文件读取
        :param use_local_only: 是否只使用本地缓存数据，不访问外部API。True=仅本地，False=本地+外部
        """
        if token is None:
            # 从配置文件读取token
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'todolist', 'config.json')
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                token = config.get('token', '')
        
        ts.set_token(token)
        self.pro = ts.pro_api()
        
        # 设置缓存目录
        self.cache_dir = os.path.expanduser('~/abu/tushare')
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # 设置数据获取模式
        self.use_local_only = use_local_only  # True=仅本地，False=本地+外部
        
        # 因子权重配置（可根据回测结果调整）
        self.quality_weights = {
            'roe': 0.3,      # ROE权重
            'roa': 0.2,      # ROA权重
            'gross_profit_margin': 0.2,  # 毛利率权重
            'net_profit_margin': 0.2,    # 净利率权重
            'profit_growth': 0.1         # 盈利增长率权重
        }
        
        self.momentum_weights = {
            'return_1m': 0.3,   # 1个月收益率权重
            'return_3m': 0.3,   # 3个月收益率权重
            'return_6m': 0.3,   # 6个月收益率权重
            'return_12m': 0.1   # 12个月收益率权重
        }
        
        # 质量因子和动量因子的综合权重
        self.quality_weight = 0.5  # 质量因子权重
        self.momentum_weight = 0.5  # 动量因子权重
    
    def _get_cache_key(self, func_name, **kwargs):
        """
        生成可读的缓存文件名
        :param func_name: 函数名
        :param kwargs: 参数字典
        :return: 缓存文件名（不含扩展名）
        """
        # 检查是否有股票代码
        ts_code = kwargs.get('ts_code', '')
        
        if ts_code:
            # 单个股票：股票代码_数据类型
            # 将股票代码中的点号替换为下划线，例如 000001.SZ -> 000001_SZ
            ts_code_clean = ts_code.replace('.', '_')
            
            # 对于daily类型，添加起止日期
            if func_name == 'daily' or func_name == 'index_daily':
                start_date = kwargs.get('start_date', '')
                end_date = kwargs.get('end_date', '')
                if start_date and end_date:
                    cache_key = f"{ts_code_clean}_{func_name}_{start_date}_{end_date}"
                else:
                    cache_key = f"{ts_code_clean}_{func_name}"
            else:
                cache_key = f"{ts_code_clean}_{func_name}"
        else:
            # 全体数据：数据类型_all
            cache_key = f"{func_name}_all"
        
        return cache_key
    
    def _get_cache_folder(self, func_name):
        """
        根据函数名获取缓存文件夹
        :param func_name: 函数名
        :return: 文件夹路径
        """
        if func_name in ['daily', 'index_daily']:
            # daily数据放入daily文件夹
            folder = os.path.join(self.cache_dir, 'daily')
        else:
            # 其他数据放入finance文件夹
            folder = os.path.join(self.cache_dir, 'finance')
        
        # 确保文件夹存在
        os.makedirs(folder, exist_ok=True)
        return folder
    
    def _load_from_cache(self, cache_key, func_name):
        """
        从本地缓存加载数据（CSV格式）
        :param cache_key: 缓存键
        :param func_name: 函数名（用于确定文件夹）
        :return: DataFrame或None
        """
        folder = self._get_cache_folder(func_name)
        cache_file = os.path.join(folder, f"{cache_key}.csv")
        if os.path.exists(cache_file):
            try:
                # 读取CSV文件
                df = pd.read_csv(cache_file, index_col=0, encoding='utf-8-sig')
                return df
            except Exception as e:
                print(f"加载缓存失败 {cache_file}: {e}")
                return None
        return None
    
    def _save_to_cache(self, cache_key, data, func_name):
        """
        保存数据到本地缓存（CSV格式）
        :param cache_key: 缓存键
        :param data: 要保存的数据（DataFrame）
        :param func_name: 函数名（用于确定文件夹）
        """
        folder = self._get_cache_folder(func_name)
        cache_file = os.path.join(folder, f"{cache_key}.csv")
        try:
            # 保存为CSV格式，包含索引，使用UTF-8-BOM编码以支持Excel打开
            data.to_csv(cache_file, index=True, encoding='utf-8-sig')
        except Exception as e:
            print(f"保存缓存失败 {cache_file}: {e}")
    
    def _get_data_with_cache(self, cache_key, fetch_func, func_name):
        """
        带缓存的数据获取方法
        :param cache_key: 缓存键（由调用者生成）
        :param fetch_func: 实际的数据获取函数（无参数）
        :param func_name: 函数名（用于确定文件夹）
        :return: (DataFrame, bool) 元组，DataFrame为数据，bool为是否从本地获取（True=本地，False=外部）
        """
        # 尝试从缓存加载
        cached_data = self._load_from_cache(cache_key, func_name)
        if cached_data is not None:
            return cached_data, True  # 从本地获取
        
        # 如果设置为仅本地模式，且缓存中没有数据，返回空DataFrame
        if self.use_local_only:
            return pd.DataFrame(), True  # 标记为本地获取（虽然为空）
        
        # 从网络获取
        data = fetch_func()
        
        # 保存到缓存
        if data is not None and not data.empty:
            self._save_to_cache(cache_key, data, func_name)
        
        return data, False  # 从外部获取
    
    def get_stock_basic(self, exchange='', list_status='L', fields='ts_code,symbol,name,market,list_date'):
        """
        获取股票基本信息（带缓存）
        """
        cache_key = self._get_cache_key('stock_basic', exchange=exchange, list_status=list_status, fields=fields)
        
        def fetch():
            return self.pro.stock_basic(
                exchange=exchange,
                list_status=list_status,
                fields=fields
            )
        
        data, _ = self._get_data_with_cache(cache_key, fetch, 'stock_basic')
        return data
    
    def get_trade_cal(self, exchange='', start_date='', end_date=''):
        """
        获取交易日历（带缓存）
        """
        cache_key = self._get_cache_key('trade_cal', exchange=exchange, start_date=start_date, end_date=end_date)
        
        def fetch():
            return self.pro.trade_cal(exchange=exchange, start_date=start_date, end_date=end_date)
        
        data, _ = self._get_data_with_cache(cache_key, fetch, 'trade_cal')
        return data
    
    def get_finance_data(self, ts_code, start_date='', end_date=''):
        """
        获取财务数据（合并fina_indicator和income，带缓存）
        :param ts_code: 股票代码
        :param start_date: 开始日期
        :param end_date: 结束日期
        :return: 合并后的DataFrame
        """
        cache_key = self._get_cache_key('finance', ts_code=ts_code, start_date=start_date, end_date=end_date)
        
        def fetch():
            # 获取财务指标
            fina_indicator = self.pro.fina_indicator(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )

            # 获取利润表数据
            income = self.pro.income(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
                # fields='ts_code,end_date,n_income'
            )
            
            # 按ann_date去重（如果有ann_date字段）
            if not fina_indicator.empty and 'ann_date' in fina_indicator.columns:
                # 按ann_date去重，保留最新的记录
                fina_indicator = fina_indicator.sort_values('ann_date', ascending=False).drop_duplicates(subset=['ann_date'], keep='first')
            
            if not income.empty and 'ann_date' in income.columns:
                # 按ann_date去重，保留最新的记录
                income = income.sort_values('ann_date', ascending=False).drop_duplicates(subset=['ann_date'], keep='first')
            
            # 合并数据
            if not fina_indicator.empty and not income.empty:
                # 按end_date合并
                merged = pd.merge(fina_indicator, income, on=['ts_code', 'end_date'], how='outer')
            elif not fina_indicator.empty:
                merged = fina_indicator.copy()
                merged['n_income'] = np.nan
            elif not income.empty:
                merged = income.copy()
                merged['roe'] = np.nan
                merged['roa'] = np.nan
                merged['grossprofit_margin'] = np.nan
                merged['netprofit_margin'] = np.nan
            else:
                merged = pd.DataFrame()
            
            return merged
        
        data, _ = self._get_data_with_cache(cache_key, fetch, 'finance')
        return data
    
    def _load_from_abu_csv(self, ts_code, start_date, end_date):
        """
        从abu/data/csv目录加载日线数据
        :param ts_code: 股票代码，例如 '000001.SZ' 或 '600000.SH'
        :param start_date: 开始日期，格式YYYYMMDD
        :param end_date: 结束日期，格式YYYYMMDD
        :return: DataFrame或None
        """
        # 将ts_code转换为文件名格式：000001.SZ -> 000001_SZ, 600000.SH -> sh600000
        # 根据用户示例：sh600452_20240703_20251217，看起来是小写sh/sz前缀
        if '.' in ts_code:
            code, market = ts_code.split('.')
            if market == 'SH':
                file_code = f"sh{code}"
            elif market == 'SZ':
                file_code = f"sz{code}"
            else:
                file_code = f"{code}_{market.lower()}"
        else:
            file_code = ts_code
        
        # 构建文件路径：abu/data/csv/{code}_{start_date}_{end_date}.csv
        abu_csv_dir = os.path.join(os.path.expanduser('~'), 'abu', 'data', 'csv')
        csv_file = os.path.join(abu_csv_dir, f"{file_code}_{start_date}_{end_date}")
        
        if os.path.exists(csv_file):
            try:
                print(f"从abu/data/csv加载数据: {csv_file}")
                df = pd.read_csv(csv_file, encoding='utf-8-sig')
                # 确保有date和close字段
                if 'date' in df.columns and 'close' in df.columns:
                    # 将date列重命名为trade_date
                    df = df.rename(columns={'date': 'trade_date'})
                    return df
                else:
                    print(f"警告: {csv_file} 缺少必要字段")
                    return None
            except Exception as e:
                print(f"加载abu CSV文件失败 {csv_file}: {e}")
                return None
        return None
    
    def get_daily(self, ts_code, start_date='', end_date=''):
        """
        获取日线数据（带缓存）
        优先从abu/data/csv目录读取，如果没有则从tushare获取并缓存
        """
        # 如果有起止日期，先尝试从abu/data/csv读取
        if start_date and end_date:
            abu_data = self._load_from_abu_csv(ts_code, start_date, end_date)
            if abu_data is not None and not abu_data.empty:
                return abu_data
        
        # 如果abu目录没有数据，使用原来的方法（tushare + 缓存）
        cache_key = self._get_cache_key('daily', ts_code=ts_code, start_date=start_date,
                                        end_date=end_date)
        
        def fetch():
            return self.pro.daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date
            )
        
        data, _ = self._get_data_with_cache(cache_key, fetch, 'daily')
        return data
    
    def get_index_daily(self, ts_code, start_date='', end_date=''):
        """
        获取指数日线数据（带缓存）
        优先从abu/data/csv目录读取，如果没有则从tushare获取并缓存
        """
        # 如果有起止日期，先尝试从abu/data/csv读取
        if start_date and end_date:
            abu_data = self._load_from_abu_csv(ts_code, start_date, end_date)
            if abu_data is not None and not abu_data.empty:
                return abu_data
        
        # 如果abu目录没有数据，使用原来的方法（tushare + 缓存）
        cache_key = self._get_cache_key('index_daily', ts_code=ts_code, start_date=start_date,
                                        end_date=end_date)
        
        def fetch():
            return self.pro.index_daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date
            )
        
        data, _ = self._get_data_with_cache(cache_key, fetch, 'index_daily')
        return data
    
    def get_stock_list(self, exchange='', list_status='L'):
        """
        获取股票列表
        :param exchange: 交易所代码，''表示全部
        :param list_status: 上市状态，'L'表示上市
        :return: 股票代码列表
        """
        stock_basic = self.get_stock_basic(exchange=exchange, list_status=list_status)
        return stock_basic['ts_code'].tolist()
    
    def get_quality_factors(self, ts_code_list, start_date=None, end_date=None):
        """
        获取高质量因子数据
        :param ts_code_list: 股票代码列表
        :param start_date: 开始日期，格式YYYYMMDD，None表示不限制开始日期
        :param end_date: 截止日期，格式YYYYMMDD，None表示最新
        :return: DataFrame，包含质量因子
        """
        print("正在获取质量因子数据...")
        
        # 设置起止日期
        if start_date is None:
            start_date_str = ''
        else:
            start_date_str = start_date
        
        if end_date is None:
            end_date_str = ''
        else:
            end_date_str = end_date
        
        quality_data = []
        
        # 按股票代码逐个获取财务数据
        external_fetch_count = 0  # 记录从外部获取的次数
        for i, ts_code in enumerate(ts_code_list[:]):  # 限制数量，避免接口调用过多
            try:
                # 获取合并后的财务数据（包含财务指标和利润表），使用指定的起止日期
                cache_key = self._get_cache_key('finance', ts_code=ts_code, start_date=start_date_str, end_date=end_date_str)
                
                def fetch():
                    # 获取财务指标
                    fina_indicator = self.pro.fina_indicator(
                        ts_code=ts_code,
                        start_date=start_date_str,
                        end_date=end_date_str,
                    )

                    # 获取利润表数据
                    income = self.pro.income(
                        ts_code=ts_code,
                        start_date=start_date_str,
                        end_date=end_date_str,
                    )
                    
                    # 按ann_date去重（如果有ann_date字段）
                    if not fina_indicator.empty and 'ann_date' in fina_indicator.columns:
                        # 按ann_date去重，保留最新的记录
                        fina_indicator = fina_indicator.sort_values('ann_date', ascending=False).drop_duplicates(subset=['ann_date'], keep='first')
                    
                    if not income.empty and 'ann_date' in income.columns:
                        # 按ann_date去重，保留最新的记录
                        income = income.sort_values('ann_date', ascending=False).drop_duplicates(subset=['ann_date'], keep='first')
                    
                    # 合并数据
                    if not fina_indicator.empty and not income.empty:
                        # 按end_date合并
                        merged = pd.merge(fina_indicator, income, on=['ts_code', 'end_date'], how='outer')
                    elif not fina_indicator.empty:
                        merged = fina_indicator.copy()
                        merged['n_income'] = np.nan
                    elif not income.empty:
                        merged = income.copy()
                        merged['roe'] = np.nan
                        merged['roa'] = np.nan
                        merged['grossprofit_margin'] = np.nan
                        merged['netprofit_margin'] = np.nan
                    else:
                        merged = pd.DataFrame()
                    
                    return merged
                
                finance_data, is_local = self._get_data_with_cache(cache_key, fetch, 'finance')
                
                # 如果从外部获取，增加计数
                if not is_local:
                    external_fetch_count += 1
                
                if finance_data.empty:
                    continue
                
                # 按报告期排序，取最新一期
                finance_data = finance_data.sort_values('end_date', ascending=False)
                latest_finance = finance_data.iloc[0]
                
                # 计算盈利增长率（使用最新一期与前一年同期的数据对比）
                profit_growth = np.nan
                if 'n_income' in finance_data.columns and 'end_date' in finance_data.columns:
                    latest_profit = latest_finance['n_income']
                    latest_end_date = latest_finance['end_date']
                    
                    # 计算前一年同期的end_date（例如：20250930 -> 20240930）
                    if not pd.isna(latest_end_date) and str(latest_end_date) != '':
                        try:
                            # 将end_date转换为日期对象
                            if isinstance(latest_end_date, str):
                                latest_date = datetime.strptime(latest_end_date, '%Y%m%d')
                            else:
                                latest_date = pd.to_datetime(str(latest_end_date), format='%Y%m%d')
                            
                            # 计算前一年同期日期
                            prev_year_date = latest_date - timedelta(days=365)
                            # 如果月份和日期相同，直接减一年；否则使用365天前
                            # 为了更准确，尝试找到相同月份和日期的前一年
                            if latest_date.month == 2 and latest_date.day == 29:
                                # 处理闰年2月29日的情况
                                prev_year_date = datetime(latest_date.year - 1, 2, 28)
                            else:
                                prev_year_date = datetime(latest_date.year - 1, latest_date.month, latest_date.day)
                            
                            prev_year_end_date = prev_year_date.strftime('%Y%m%d')
                            
                            # 在finance_data中查找前一年同期的数据
                            prev_year_data = finance_data[finance_data['end_date'] == prev_year_end_date]
                            
                            if not prev_year_data.empty and 'n_income' in prev_year_data.columns:
                                prev_profit = prev_year_data.iloc[0]['n_income']
                                if prev_profit != 0 and not pd.isna(prev_profit) and not pd.isna(latest_profit):
                                    profit_growth = (latest_profit - prev_profit) / abs(prev_profit) * 100
                        except Exception as e:
                            # 如果日期解析失败，使用原来的方法（取前一条记录）
                            if len(finance_data) >= 2:
                                prev_profit = finance_data.iloc[1]['n_income']
                                if prev_profit != 0 and not pd.isna(prev_profit) and not pd.isna(latest_profit):
                                    profit_growth = (latest_profit - prev_profit) / abs(prev_profit) * 100
                
                quality_data.append({
                    'ts_code': ts_code,
                    'roe': latest_finance['roe'] if 'roe' in latest_finance and not pd.isna(latest_finance['roe']) else 0,
                    'roa': latest_finance['roa'] if 'roa' in latest_finance and not pd.isna(latest_finance['roa']) else 0,
                    'gross_profit_margin': latest_finance['grossprofit_margin'] if 'grossprofit_margin' in latest_finance and not pd.isna(latest_finance['grossprofit_margin']) else 0,
                    'net_profit_margin': latest_finance['netprofit_margin'] if 'netprofit_margin' in latest_finance and not pd.isna(latest_finance['netprofit_margin']) else 0,
                    'profit_growth': profit_growth if not pd.isna(profit_growth) else 0
                })
                
                # 只有从外部获取时才延迟，避免接口限流
                # 每50个外部获取延迟18秒
                if not is_local and external_fetch_count % 50 == 0 and external_fetch_count > 0:
                    time.sleep(18)
                    print(f"已处理 {i + 1} 只股票的质量因子（其中 {external_fetch_count} 次从外部获取）...")
                elif is_local and (i + 1) % 100 == 0:
                    # 从本地获取时，每100个打印一次进度，不延迟
                    print(f"已处理 {i + 1} 只股票的质量因子（从本地缓存）...")
                    
            except Exception as e:
                print(f"处理 {ts_code} 质量因子时出错: {e}")
                continue
        
        quality_df = pd.DataFrame(quality_data)
        # 将所有NaN值填充为0
        quality_df = quality_df.fillna(0)
        print(f"成功获取 {len(quality_df)} 只股票的质量因子数据")
        return quality_df
    
    def get_momentum_factors(self, ts_code_list, start_date=None, end_date=None):
        """
        获取高动量因子数据
        :param ts_code_list: 股票代码列表
        :param start_date: 开始日期，格式YYYYMMDD，None表示12个月前
        :param end_date: 截止日期，格式YYYYMMDD，None表示最新
        :return: DataFrame，包含动量因子
        """
        print("正在获取动量因子数据...")
        
        if end_date is None:
            end_date = datetime.now()
        else:
            end_date = datetime.strptime(end_date, '%Y%m%d')
        
        # 如果没有指定开始日期，默认使用12个月前
        if start_date is None:
            start_date_dt = end_date - timedelta(days=365)
            start_date_str = start_date_dt.strftime('%Y%m%d')
        else:
            start_date_str = start_date
        
        # 计算各个时间段的起始日期
        date_1m = (end_date - timedelta(days=30)).strftime('%Y%m%d')
        date_3m = (end_date - timedelta(days=90)).strftime('%Y%m%d')
        date_6m = (end_date - timedelta(days=180)).strftime('%Y%m%d')
        date_12m = start_date_str  # 使用指定的开始日期
        end_date_str = end_date.strftime('%Y%m%d')
        
        momentum_data = []
        
        # 获取市场基准收益率（使用沪深300指数）
        try:
            index_daily = self.get_index_daily(
                ts_code='000300.SH',  # 沪深300
                start_date=start_date_str,
                end_date=end_date_str,
            )
            index_daily = index_daily.sort_values('trade_date')
            if len(index_daily) >= 2:
                market_return_1m = (index_daily.iloc[-1]['close'] / index_daily.iloc[-21]['close'] - 1) * 100 if len(index_daily) >= 21 else 0
                market_return_3m = (index_daily.iloc[-1]['close'] / index_daily.iloc[-63]['close'] - 1) * 100 if len(index_daily) >= 63 else 0
                market_return_6m = (index_daily.iloc[-1]['close'] / index_daily.iloc[-126]['close'] - 1) * 100 if len(index_daily) >= 126 else 0
                market_return_12m = (index_daily.iloc[-1]['close'] / index_daily.iloc[0]['close'] - 1) * 100
            else:
                market_return_1m = market_return_3m = market_return_6m = market_return_12m = 0
        except:
            market_return_1m = market_return_3m = market_return_6m = market_return_12m = 0
        
        # 获取每只股票的日线数据
        external_fetch_count = 0  # 记录从外部获取的次数
        for idx, ts_code in enumerate(ts_code_list[:]):  # 限制数量
            try:
                # 先尝试从abu/data/csv读取
                is_local = False
                if start_date_str and end_date_str:
                    abu_data = self._load_from_abu_csv(ts_code, start_date_str, end_date_str)
                    if abu_data is not None and not abu_data.empty:
                        daily = abu_data
                        is_local = True
                    else:
                        # 如果abu目录没有数据，使用原来的方法（tushare + 缓存）
                        cache_key = self._get_cache_key('daily', ts_code=ts_code, start_date=start_date_str,
                                                        end_date=end_date_str)
                        
                        def fetch():
                            return self.pro.daily(
                                ts_code=ts_code,
                                start_date=start_date_str,
                                end_date=end_date_str
                            )
                        
                        daily, is_local = self._get_data_with_cache(cache_key, fetch, 'daily')
                else:
                    # 如果没有起止日期，使用原来的方法
                    cache_key = self._get_cache_key('daily', ts_code=ts_code, start_date=start_date_str,
                                                    end_date=end_date_str)
                    
                    def fetch():
                        return self.pro.daily(
                            ts_code=ts_code,
                            start_date=start_date_str,
                            end_date=end_date_str
                        )
                    
                    daily, is_local = self._get_data_with_cache(cache_key, fetch, 'daily')
                
                # 如果从外部获取，增加计数
                if not is_local:
                    external_fetch_count += 1
                
                if daily.empty or len(daily) < 2:
                    continue
                
                daily = daily.sort_values('trade_date')
                latest_close = daily.iloc[-1]['close']
                
                # 计算各个时间段的收益率
                return_1m = 0.4
                return_3m = 0.3
                return_6m = 0.3
                return_12m = 0
                
                # 1个月收益率
                if len(daily) >= 21:
                    close_1m_ago = daily.iloc[-21]['close']
                    if close_1m_ago > 0:
                        return_1m = (latest_close / close_1m_ago - 1) * 100
                
                # 3个月收益率
                if len(daily) >= 63:
                    close_3m_ago = daily.iloc[-63]['close']
                    if close_3m_ago > 0:
                        return_3m = (latest_close / close_3m_ago - 1) * 100
                
                # 6个月收益率
                if len(daily) >= 126:
                    close_6m_ago = daily.iloc[-126]['close']
                    if close_6m_ago > 0:
                        return_6m = (latest_close / close_6m_ago - 1) * 100
                
                # 12个月收益率
                close_12m_ago = daily.iloc[0]['close']
                if close_12m_ago > 0:
                    return_12m = (latest_close / close_12m_ago - 1) * 100
                
                # 计算相对强度（相对于市场）
                relative_strength_1m = return_1m - market_return_1m
                relative_strength_3m = return_3m - market_return_3m
                relative_strength_6m = return_6m - market_return_6m
                relative_strength_12m = return_12m - market_return_12m
                
                momentum_data.append({
                    'ts_code': ts_code,
                    'return_1m': return_1m,
                    'return_3m': return_3m,
                    'return_6m': return_6m,
                    'return_12m': return_12m,
                    'relative_strength_1m': relative_strength_1m,
                    'relative_strength_3m': relative_strength_3m,
                    'relative_strength_6m': relative_strength_6m,
                    'relative_strength_12m': relative_strength_12m
                })
                
                # 只有从外部获取时才延迟，避免接口限流
                # 每100个外部获取延迟1秒
                if not is_local and external_fetch_count % 100 == 0 and external_fetch_count > 0:
                    time.sleep(1)
                    print(f"已处理 {len(momentum_data)} 只股票的动量因子（其中 {external_fetch_count} 次从外部获取）...")
                elif is_local and len(momentum_data) % 200 == 0:
                    # 从本地获取时，每200个打印一次进度，不延迟
                    print(f"已处理 {len(momentum_data)} 只股票的动量因子（从本地缓存）...")
                    
            except Exception as e:
                print(f"处理 {ts_code} 动量因子时出错: {e}")
                continue
        
        momentum_df = pd.DataFrame(momentum_data)
        # 将所有NaN值填充为0
        momentum_df = momentum_df.fillna(0)
        print(f"成功获取 {len(momentum_df)} 只股票的动量因子数据")
        return momentum_df
    
    def calculate_quality_score(self, quality_df):
        """
        计算质量因子得分
        :param quality_df: 质量因子DataFrame
        :return: 添加了quality_score列的DataFrame
        """
        df = quality_df.copy()
        
        # 对每个质量因子进行标准化（使用分位数排名）
        quality_factors = ['roe', 'roa', 'gross_profit_margin', 'net_profit_margin', 'profit_growth']
        
        for factor in quality_factors:
            if factor in df.columns:
                # 使用分位数排名，值越大排名越高，NaN值排名为0
                df[f'{factor}_rank'] = df[factor].rank(pct=True, na_option='keep').fillna(0)

        # 这里的rank指的是“分位数排名”，即将每个质量因子的取值按照升序排列后，计算每个数值在整个序列中的分位位置（百分比），数值越大，rank值越高。
        # 例如，rank为0.8表示该值高于80%的样本。这样可以消除原始因子量纲的影响，将不同因子的值标准化到[0, 1]区间，也便于后续加权计算总分。
        # 举例说明分位数排名（rank）的含义：
        # 假设roe列所有股票的值分别为 [5, 12, 8, 20, 10]
        # 经过 rank(pct=True) 处理后，分位数排名结果为：
        # 5   -> 0.2   # 低于 80% 的股票
        # 8   -> 0.4
        # 10  -> 0.6
        # 12  -> 0.8
        # 20  -> 1.0   # 所有股票中最高
        # 也就是说，分位数排名为0.8表示该股票的roe高于80%的同行，1.0表示最高，0.2表示较低。
        # 如果数据量较大（如超过100只股票），为了确保排名的有效性和代表性，建议保留所有有用数据参与排名。
        # 排名方法默认会根据所有传入数据自动计算分位数，能反映该序列中的相对位置。
        # 但如果数据集包含异常值、极端值，或数据质量不稳定，可考虑以下措施进一步优化：
        #
        # 1. 剔除极端异常值（如低于1%分位数或高于99%分位数的数据），避免极端值扰动排名。
        # 2. 保证分位数排名基于有用/有效数据（如因子缺失或无效的股票可先填充0或剔除）。
        # 3. 若数据量特别大（如几千上万），而只关注前100排名，可先过滤掉明显不合格样本再做排名，提升效率。
        # 4. 根据需求，也可以采用rolling/expanding window对历史数据分批排名，聚焦近一段时期的相对优势。
        #
        # 但通常情况下，对于100只甚至数千只股票，直接用当前的数据集全量排名即可，pandas的rank方法自动适配样本量大小，越多数据排名越精准。
        
        # 计算加权质量得分，确保NaN被填充为0
        df['quality_score'] = (
            df['roe_rank'].fillna(0) * self.quality_weights['roe'] +
            df['roa_rank'].fillna(0) * self.quality_weights['roa'] +
            df['gross_profit_margin_rank'].fillna(0) * self.quality_weights['gross_profit_margin'] +
            df['net_profit_margin_rank'].fillna(0) * self.quality_weights['net_profit_margin'] +
            df['profit_growth_rank'].fillna(0) * self.quality_weights['profit_growth']
        )
        
        return df
    
    def calculate_momentum_score(self, momentum_df):
        """
        计算动量因子得分
        :param momentum_df: 动量因子DataFrame
        :return: 添加了momentum_score列的DataFrame
        """
        df = momentum_df.copy()
        
        # 对每个动量因子进行标准化（使用分位数排名）
        momentum_factors = ['return_1m', 'return_3m', 'return_6m', 'return_12m']
        
        for factor in momentum_factors:
            if factor in df.columns:
                # 使用分位数排名，值越大排名越高，NaN值排名为0
                df[f'{factor}_rank'] = df[factor].rank(pct=True, na_option='keep').fillna(0)
        
        # 计算加权动量得分，确保NaN被填充为0
        df['momentum_score'] = (
            df['return_1m_rank'].fillna(0) * self.momentum_weights['return_1m'] +
            df['return_3m_rank'].fillna(0) * self.momentum_weights['return_3m'] +
            df['return_6m_rank'].fillna(0) * self.momentum_weights['return_6m'] +
            df['return_12m_rank'].fillna(0) * self.momentum_weights['return_12m']
        )
        
        return df
    
    def pick_stocks(self, top_n=50, min_quality_score=0.5, min_momentum_score=0.5, stock_list=None, start_date='20210101', end_date='20251217'):
        """
        执行选股
        :param top_n: 返回前N只股票
        :param min_quality_score: 最小质量得分阈值
        :param min_momentum_score: 最小动量得分阈值
        :param stock_list: 股票代码列表，如果提供则使用该列表计算排名，否则获取所有股票
        :return: 选股结果DataFrame
        """
        print("=" * 60)
        if stock_list:
            print(f"开始使用给定股票列表进行选股（共{len(stock_list)}只）")
        else:
            print("开始执行高质量+高动量因子选股策略（使用全市场股票）")
        print("=" * 60)
        
        # 1. 确定用于计算排名的股票列表
        if stock_list is not None:
            # 如果给定了股票列表，使用该列表计算排名
            print(f"\n步骤1: 使用给定股票列表计算排名（共{len(stock_list)}只股票）")
            rank_stock_list = stock_list.copy()
        else:
            # 如果没有给定列表，获取所有股票列表
            print("\n步骤1: 获取全市场股票列表用于计算排名...")
            rank_stock_list = self.get_stock_list()
            print(f"共获取 {len(rank_stock_list)} 只股票用于计算排名")
        
        # 2. 获取质量因子（获取排名列表的所有股票数据）
        print("\n步骤2: 获取质量因子...")
        quality_df = self.get_quality_factors(rank_stock_list, start_date='20210101', end_date='20251217')
        
        # 3. 获取动量因子（获取排名列表的所有股票数据）
        print("\n步骤3: 获取动量因子...")
        momentum_df = self.get_momentum_factors(rank_stock_list, start_date=start_date, end_date=end_date)
        
        # 4. 合并数据
        print("\n步骤4: 合并因子数据...")
        merged_df = pd.merge(quality_df, momentum_df, on='ts_code', how='inner')
        # 确保合并后所有数值列的NaN都被填充为0
        numeric_columns = merged_df.select_dtypes(include=[np.number]).columns
        merged_df[numeric_columns] = merged_df[numeric_columns].fillna(0)
        print(f"合并后共有 {len(merged_df)} 只股票")
        
        if merged_df.empty:
            print("警告：合并后没有股票数据！")
            return pd.DataFrame()
        
        # 5. 计算质量得分（基于排名列表计算排名）
        print("\n步骤5: 计算质量因子得分...")
        merged_df = self.calculate_quality_score(merged_df)
        
        # 6. 计算动量得分（基于排名列表计算排名）
        print("\n步骤6: 计算动量因子得分...")
        merged_df = self.calculate_momentum_score(merged_df)
        
        # 7. 计算综合得分
        print("\n步骤7: 计算综合得分...")
        merged_df['composite_score'] = (
            merged_df['quality_score'].fillna(0) * self.quality_weight +
            merged_df['momentum_score'].fillna(0) * self.momentum_weight
        )
        
        # 8. 筛选股票
        print("\n步骤8: 筛选股票...")
        filtered_df = merged_df[
            (merged_df['quality_score'] >= min_quality_score) &
            (merged_df['momentum_score'] >= min_momentum_score)
        ].copy()
        
        # 9. 按综合得分排序
        filtered_df = filtered_df.sort_values('composite_score', ascending=False)
        
        # 10. 获取股票基本信息
        print("\n步骤9: 获取股票基本信息...")
        stock_basic = self.get_stock_basic(
            exchange='',
            list_status='L',
            fields='ts_code,symbol,name,industry,area,market'
        )
        
        result_df = pd.merge(
            filtered_df.head(top_n),
            stock_basic[['ts_code', 'name', 'industry', 'area', 'market']],
            on='ts_code',
            how='left'
        )
        
        # 选择输出字段
        output_columns = [
            'ts_code', 'name', 'industry', 'area', 'market',
            'roe', 'roa', 'gross_profit_margin', 'net_profit_margin', 'profit_growth',
            'return_1m', 'return_3m', 'return_6m', 'return_12m',
            'quality_score', 'momentum_score', 'composite_score'
        ]
        
        result_df = result_df[[col for col in output_columns if col in result_df.columns]]
        
        print(f"\n选股完成！共选出 {len(result_df)} 只股票")
        print("=" * 60)
        
        return result_df
    
    def save_results(self, result_df, filename=None):
        """
        保存选股结果
        :param result_df: 选股结果DataFrame
        :param filename: 保存文件名，None则自动生成
        :return: 保存的文件路径（绝对路径）
        """
        if filename is None:
            today = datetime.now().strftime('%Y%m%d')
            filename = f'quality_momentum_pick_{today}.csv'
        
        # 如果文件名不是绝对路径，转换为绝对路径
        if not os.path.isabs(filename):
            filename = os.path.abspath(filename)
        
        result_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"\n选股结果已保存至: {filename}")
        
        return filename


def main(stock_list=None, use_local_only=True, auto_analyze_120ma=True):
    """
    主函数
    :param stock_list: 股票代码列表，如果提供则使用该列表计算排名，否则获取所有股票
    :param use_local_only: 是否只使用本地缓存数据，不访问外部API。True=仅本地，False=本地+外部
    :param auto_analyze_120ma: 是否自动调用120MA分析，默认为True
    """
    # 创建选股器
    picker = QualityMomentumStockPicker(use_local_only=use_local_only)
    
    # 执行选股（选出前50只股票）
    result_df = picker.pick_stocks(
        top_n=500,
        min_quality_score=0.5,
        min_momentum_score=0.5,
        stock_list=stock_list,
        start_date='20240703',
        end_date='20251220'
    )
    
    # 显示结果
    print("\n选股结果（前20只）:")
    print(result_df.head(20).to_string(index=False))
    
    # 保存结果
    csv_file = picker.save_results(result_df)
    
    # 如果启用自动分析120MA，调用Analyze120MA进行分析
    if auto_analyze_120ma and csv_file:
        print("\n" + "=" * 60)
        print("开始自动调用120MA分析...")
        print("=" * 60)
        try:
            # 导入Analyze120MA模块（使用相对导入或绝对导入）
            import sys
            current_dir = os.path.dirname(os.path.abspath(__file__))
            if current_dir not in sys.path:
                sys.path.insert(0, current_dir)
            
            from Analyze120MA import main as analyze_120ma_main
            
            # 调用120MA分析
            ma_result_df = analyze_120ma_main(input_csv=csv_file)
            print("\n120MA分析完成！")
        except Exception as e:
            print(f"调用120MA分析时出错: {e}")
            import traceback
            traceback.print_exc()
    
    return result_df


if __name__ == '__main__':
    start = time.time()
    
    # 示例1: 使用给定股票列表进行选股
    # test_stock_list = ['000001.SZ', '000002.SZ', '600000.SH', '600036.SH']
    # test_stock_list = ['000001.SZ', '300295.SZ']
    # result = main(stock_list=test_stock_list)
    
    # 示例2: 使用全市场股票进行选股（默认）
    result = main()
    
    print(f"\nhandle finish cost time {time.time() - start:.2f} 秒")

