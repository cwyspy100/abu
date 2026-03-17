"""
动量突破策略回测系统
策略规则：
【买入条件】
1. 股价 > 60日均线
2. 60日均线方向向上
3. 收盘价突破50日最高价
4. 成交量 > 20日均量

【加仓条件】
1. 持仓已有 > 8% 盈利
2. 股价再创新高
3. 加仓仓位为首次仓位的50%（首次20%，加仓10%）
4. 加仓后总仓位不超过30%

【卖出条件】（满足任意一个就卖）
1. 跌破10日最低点
2. 跌破60日均线
3. 盈利 > 25% 后，回落8%止盈

【仓位管理】
1. 首次仓位：总资金20%
2. 加仓后总仓位不超过30%
3. 单笔最大风险：总资金2%
"""

import pandas as pd
import numpy as np
import os
import glob
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')


class MomentumBreakthroughBacktest:
    """动量突破策略回测器"""
    
    def __init__(self, initial_capital=100000, csv_dir=None):
        """
        初始化回测器
        :param initial_capital: 初始资金（元），默认10万元
        :param csv_dir: CSV文件目录，默认为~/abu/data/csv
        """
        self.initial_capital = initial_capital
        self.csv_dir = csv_dir if csv_dir else os.path.expanduser('~/abu/data/csv')
        
        # 策略参数
        self.first_buy_ratio = 0.20  # 首次买入比例20%
        self.add_position_ratio = 0.10  # 加仓比例10%（首次的50%）
        self.max_position_ratio = 0.30  # 最大仓位30%
        self.profit_threshold_for_add = 0.08  # 加仓盈利阈值8%
        self.profit_threshold_for_trailing = 0.25  # 跟踪止盈触发阈值25%
        self.trailing_stop_ratio = 0.08  # 跟踪止盈回撤8%
        self.max_risk_per_trade = 0.02  # 单笔最大风险2%
        
        # 均线参数
        self.ma_period = 60  # 60日均线
        self.ma_slope_period = 5  # 计算均线斜率使用的周期
        self.high_period = 50  # 50日最高价
        self.volume_ma_period = 20  # 20日均量
        self.low_period = 10  # 10日最低价
        
    def calculate_indicators(self, df):
        """
        计算所有技术指标
        :param df: 包含date和close的DataFrame
        :return: 添加了所有指标的DataFrame
        """
        df = df.copy()
        # 按日期排序
        df = df.sort_values('date').reset_index(drop=True)
        
        # 计算60日均线
        df['ma60'] = df['close'].rolling(window=self.ma_period, min_periods=self.ma_period).mean()
        df['ma60'] = df['ma60'].fillna(df['close'])
        
        # 计算60日均线斜率（方向）
        df['ma60_slope'] = 0.0
        if len(df) > self.ma_slope_period:
            ma60_shifted = df['ma60'].shift(self.ma_slope_period)
            df['ma60_slope'] = (df['ma60'] - ma60_shifted) / self.ma_slope_period
            df['ma60_slope'] = df['ma60_slope'].fillna(0.0)
        
        # 计算50日最高价
        df['high_50'] = df['high'].rolling(window=self.high_period, min_periods=self.high_period).max()
        df['high_50'] = df['high_50'].fillna(df['high'])
        
        # 计算20日均量
        df['volume_ma20'] = df['volume'].rolling(window=self.volume_ma_period, min_periods=self.volume_ma_period).mean()
        df['volume_ma20'] = df['volume_ma20'].fillna(df['volume'])
        
        # 计算10日最低价
        df['low_10'] = df['low'].rolling(window=self.low_period, min_periods=self.low_period).min()
        df['low_10'] = df['low_10'].fillna(df['low'])
        
        return df
    
    def check_buy_signal(self, df, i, debug=False):
        """
        检查买入信号
        :param df: 包含所有指标的DataFrame
        :param i: 当前索引
        :param debug: 是否输出调试信息
        :return: True表示满足买入条件, 如果debug=True，返回(结果, 条件详情)
        """
        if i < max(self.ma_period, self.high_period, self.volume_ma_period):
            if debug:
                return False, {'reason': '数据不足，需要至少60天数据'}
            return False
        
        current_close = df.iloc[i]['close']
        current_ma60 = df.iloc[i]['ma60']
        current_ma60_slope = df.iloc[i]['ma60_slope']
        current_high_50 = df.iloc[i]['high_50']
        current_volume = df.iloc[i]['volume']
        current_volume_ma20 = df.iloc[i]['volume_ma20']
        
        # 条件1：股价 > 60日均线
        condition1 = current_close > current_ma60
        
        # 条件2：60日均线方向向上
        condition2 = current_ma60_slope > 0
        
        # 条件3：收盘价突破50日最高价
        # 检查是否是突破（前一天收盘价没有突破，今天收盘价突破了）
        if i > 0:
            prev_close = df.iloc[i-1]['close']
            prev_high_50 = df.iloc[i-1]['high_50']
            # 前一天收盘价 <= 前一天50日最高价，且今天收盘价 > 今天50日最高价
            condition3 = (prev_close <= prev_high_50) and (current_close > current_high_50)
        else:
            # 第一天，只要收盘价 > 50日最高价即可
            condition3 = current_close > current_high_50

        condition3 = True
        
        # 条件4：成交量 > 20日均量
        condition4 = current_volume > current_volume_ma20
        
        result = condition1 and condition2 and condition3 and condition4
        
        if debug:
            details = {
                'date': df.iloc[i]['date'],
                'close': current_close,
                'ma60': current_ma60,
                'ma60_slope': current_ma60_slope,
                'high_50': current_high_50,
                'volume': current_volume,
                'volume_ma20': current_volume_ma20,
                'condition1_股价大于60日均线': condition1,
                'condition2_60日均线向上': condition2,
                'condition3_突破50日最高价': condition3,
                'condition4_成交量大于20日均量': condition4,
                'all_conditions_met': result
            }
            return result, details
        
        return result
    
    def calculate_buy_amount(self, current_price, stop_loss_price):
        """
        根据风险控制计算买入金额
        单笔最大风险：总资金2%
        买入金额 = 允许亏损金额 / (买入价 - 止损价) / 买入价
        :param current_price: 当前价格
        :param stop_loss_price: 止损价格（10日最低价或60日均线，取较低者）
        :return: 买入金额, 股数
        """
        # 允许的最大亏损金额
        max_loss_amount = self.initial_capital * self.max_risk_per_trade
        
        # 计算止损比例
        if stop_loss_price > 0 and current_price > stop_loss_price:
            stop_loss_ratio = (current_price - stop_loss_price) / current_price
        else:
            # 如果止损价不合理，使用默认止损比例10%
            stop_loss_ratio = 0.10
        
        # 买入金额 = 允许亏损金额 / 止损比例
        buy_amount = max_loss_amount / stop_loss_ratio
        
        # 限制买入金额不超过首次仓位的20%
        max_buy_amount = self.initial_capital * self.first_buy_ratio
        buy_amount = min(buy_amount, max_buy_amount)
        
        # 计算可买入的股数（向下取整）
        shares = int(buy_amount / current_price)
        
        # 实际买入金额 = 股数 * 价格
        actual_buy_amount = shares * current_price
        
        return actual_buy_amount, shares
    
    def find_stock_file(self, stock_code):
        """
        查找股票文件
        支持A股、港股、美股
        :param stock_code: 股票代码
        :return: 文件路径或None
        """
        original_code = stock_code
        if '.' in stock_code:
            stock_code = stock_code.split('.')[0]
        
        # 尝试不同的前缀
        prefixes = ['sh', 'sz', 'hk', 'us']
        for prefix in prefixes:
            if stock_code.startswith(prefix):
                code = stock_code[len(prefix):]
                pattern = os.path.join(self.csv_dir, f'{prefix}{code}_*.csv')
                files = glob.glob(pattern)
                if files:
                    return files[0]
                pattern = os.path.join(self.csv_dir, f'{prefix}{code}_*')
                files = glob.glob(pattern)
                files = [f for f in files if not f.endswith('.csv')]
                if files:
                    return files[0]
        
        # 如果没有前缀，尝试所有可能的前缀
        all_prefixes = ['sh', 'sz', 'hk', 'us']
        for prefix in all_prefixes:
            pattern = os.path.join(self.csv_dir, f'{prefix}{stock_code}_*.csv')
            files = glob.glob(pattern)
            if files:
                return files[0]
            pattern = os.path.join(self.csv_dir, f'{prefix}{stock_code}_*')
            files = glob.glob(pattern)
            files = [f for f in files if not f.endswith('.csv')]
            if files:
                return files[0]
        
        print(f"无法找到股票文件: {original_code}")
        print(f"搜索目录: {self.csv_dir}")
        return None
    
    def backtest_stock(self, stock_code, start_date=None, end_date=None):
        """
        回测单个股票
        :param stock_code: 股票代码
        :param start_date: 开始日期（可选）
        :param end_date: 结束日期（可选）
        :return: 回测结果字典
        """
        # 查找股票文件
        stock_file = self.find_stock_file(stock_code)
        if stock_file is None:
            return {
                'stock_code': stock_code,
                'status': 'file_not_found',
                'initial_capital': self.initial_capital,
                'final_value': self.initial_capital,
                'total_return': 0,
                'total_return_rate': 0,
                'annual_return_rate': 0,
                'backtest_days': 0,
                'backtest_years': 0,
                'max_drawdown': 0,
                'total_trades': 0,
                'trades': [],
                'positions': [],
                'buy_signal_stats': {}
            }
        
        # 读取股票数据
        try:
            df = pd.read_csv(stock_file, encoding='utf-8-sig', sep=',')
        except:
            try:
                df = pd.read_csv(stock_file, encoding='gbk', sep=',')
            except Exception as e:
                print(f"读取文件失败 {stock_file}: {e}")
                return {
                    'stock_code': stock_code,
                    'status': 'read_error',
                    'initial_capital': self.initial_capital,
                    'final_value': self.initial_capital,
                    'total_return': 0,
                    'total_return_rate': 0,
                    'annual_return_rate': 0,
                    'backtest_days': 0,
                    'backtest_years': 0,
                    'max_drawdown': 0,
                    'total_trades': 0,
                    'trades': [],
                    'positions': [],
                    'buy_signal_stats': {}
                }
        
        # 统一列名
        if 'date' in df.columns and 'trade_date' not in df.columns:
            df = df.rename(columns={'date': 'trade_date'})
        
        # 检查必要的列
        required_columns = ['trade_date', 'close', 'high', 'low', 'volume']
        if not all(col in df.columns for col in required_columns):
            print(f"文件缺少必要列: {stock_file}")
            return {
                'stock_code': stock_code,
                'status': 'missing_columns',
                'initial_capital': self.initial_capital,
                'final_value': self.initial_capital,
                'total_return': 0,
                'total_return_rate': 0,
                'annual_return_rate': 0,
                'backtest_days': 0,
                'backtest_years': 0,
                'max_drawdown': 0,
                'total_trades': 0,
                'trades': [],
                'positions': [],
                'buy_signal_stats': {}
            }
        
        # 日期过滤
        if start_date:
            df = df[df['trade_date'] >= start_date]
        if end_date:
            df = df[df['trade_date'] <= end_date]
        
        if df.empty:
            return {
                'stock_code': stock_code,
                'status': 'no_data',
                'initial_capital': self.initial_capital,
                'final_value': self.initial_capital,
                'total_return': 0,
                'total_return_rate': 0,
                'annual_return_rate': 0,
                'backtest_days': 0,
                'backtest_years': 0,
                'max_drawdown': 0,
                'total_trades': 0,
                'trades': [],
                'positions': [],
                'buy_signal_stats': {}
            }
        
        # 统一列名（确保有date列用于计算指标）
        if 'trade_date' in df.columns:
            df = df.rename(columns={'trade_date': 'date'})
        
        # 计算技术指标
        df_with_indicators = self.calculate_indicators(df)
        
        # 执行回测
        return self.execute_backtest(df_with_indicators, stock_code)
    
    def execute_backtest(self, df, stock_code):
        """
        执行回测逻辑
        """
        cash = self.initial_capital  # 现金
        shares = 0  # 持股数量
        cost_basis = 0  # 当前成本价
        total_value = cash  # 总资产
        
        trades = []  # 交易记录
        positions = []  # 持仓记录
        
        # 状态标记
        has_position = False  # 是否有持仓
        buy_date = None  # 买入日期
        max_profit_rate = 0.0  # 买入后的最大盈利比例
        highest_price_after_buy = 0.0  # 买入后的最高价（用于判断是否创新高）
        
        max_value = self.initial_capital  # 最大资产值（用于计算最大回撤）
        max_drawdown = 0  # 最大回撤
        
        # 统计买入条件满足情况（用于调试）
        buy_signal_stats = {
            'total_days': 0,
            'condition1_count': 0,  # 股价 > 60日均线
            'condition2_count': 0,  # 60日均线向上
            'condition3_count': 0,  # 突破50日最高价
            'condition4_count': 0,  # 成交量 > 20日均量
            'all_conditions_count': 0  # 所有条件都满足
        }
        
        # 逐日回测
        for i in range(len(df)):
            current_close = df.iloc[i]['close']
            current_high = df.iloc[i]['high']
            current_low = df.iloc[i]['low']
            current_date = df.iloc[i]['date']
            current_ma60 = df.iloc[i]['ma60']
            current_low_10 = df.iloc[i]['low_10']
            
            # 如果没有持仓，检查买入条件
            if not has_position:
                # 统计买入条件（仅在前60天之后统计）
                if i >= max(self.ma_period, self.high_period, self.volume_ma_period):
                    buy_signal_stats['total_days'] += 1
                    current_close = df.iloc[i]['close']
                    current_ma60 = df.iloc[i]['ma60']
                    current_ma60_slope = df.iloc[i]['ma60_slope']
                    current_high_50 = df.iloc[i]['high_50']
                    current_volume = df.iloc[i]['volume']
                    current_volume_ma20 = df.iloc[i]['volume_ma20']
                    
                    if current_close > current_ma60:
                        buy_signal_stats['condition1_count'] += 1
                    if current_ma60_slope > 0:
                        buy_signal_stats['condition2_count'] += 1
                    if i > 0:
                        prev_close = df.iloc[i-1]['close']
                        prev_high_50 = df.iloc[i-1]['high_50']
                        if (prev_close <= prev_high_50) and (current_close > current_high_50):
                            buy_signal_stats['condition3_count'] += 1
                    if current_volume > current_volume_ma20:
                        buy_signal_stats['condition4_count'] += 1
                    
                    # 检查所有条件
                    condition1 = current_close > current_ma60
                    condition2 = current_ma60_slope > 0
                    if i > 0:
                        prev_close = df.iloc[i-1]['close']
                        prev_high_50 = df.iloc[i-1]['high_50']
                        condition3 = (prev_close <= prev_high_50) and (current_close > current_high_50)
                    else:
                        condition3 = current_close > current_high_50
                    condition4 = current_volume > current_volume_ma20
                    
                    if condition1 and condition2 and condition3 and condition4:
                        buy_signal_stats['all_conditions_count'] += 1
                
                if self.check_buy_signal(df, i):
                    # 计算止损价格（10日最低价和60日均线的较低者）
                    stop_loss_price = min(current_low_10, current_ma60)
                    
                    # 计算买入金额和股数
                    buy_amount, buy_shares = self.calculate_buy_amount(current_close, stop_loss_price)
                    
                    # 检查是否有足够的现金
                    if buy_amount <= cash and buy_shares > 0:
                        # 买入
                        shares = buy_shares
                        cost_basis = current_close
                        cash -= buy_amount
                        has_position = True
                        buy_date = current_date
                        highest_price_after_buy = current_close
                        max_profit_rate = 0.0
                        
                        trades.append({
                            'date': current_date,
                            'action': '买入',
                            'price': current_close,
                            'shares': shares,
                            'amount': buy_amount,
                            'cash': cash,
                            'position_value': shares * current_close,
                            'total_value': cash + shares * current_close,
                            'stop_loss_price': stop_loss_price
                        })
            
            # 如果有持仓，检查卖出和加仓条件
            if has_position:
                position_value = shares * current_close
                total_value = cash + position_value
                
                # 更新最大资产值
                if total_value > max_value:
                    max_value = total_value
                
                # 计算回撤
                drawdown = (max_value - total_value) / max_value * 100
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
                
                # 计算盈亏比例（基于当前成本价）
                profit_rate = (current_close - cost_basis) / cost_basis if cost_basis > 0 else 0
                total_profit_rate = (total_value - self.initial_capital) / self.initial_capital
                
                # 更新最大盈利和最高价
                if profit_rate > max_profit_rate:
                    max_profit_rate = profit_rate
                if current_high > highest_price_after_buy:
                    highest_price_after_buy = current_high
                
                # 卖出条件检查（三个条件哪个先到先触发）
                # 条件1：跌破10日最低点
                sell_condition1 = current_close < current_low_10
                
                # 条件2：跌破60日均线
                sell_condition2 = current_close < current_ma60
                
                # 条件3：盈利 > 25% 后，回落8%止盈
                sell_condition3 = False
                if max_profit_rate >= self.profit_threshold_for_trailing:
                    # 从最大盈利回撤8%
                    if profit_rate < max_profit_rate:
                        drawdown_from_max = max_profit_rate - profit_rate
                        if drawdown_from_max >= self.trailing_stop_ratio:
                            sell_condition3 = True
                
                # 哪个先到先触发
                if sell_condition1 or sell_condition2 or sell_condition3:
                    # 确定卖出原因
                    if sell_condition1 and sell_condition2:
                        action = '跌破10日最低点且跌破60日均线卖出'
                    elif sell_condition1:
                        action = '跌破10日最低点卖出'
                    elif sell_condition2:
                        action = '跌破60日均线卖出'
                    elif sell_condition3:
                        drawdown_pct = (max_profit_rate - profit_rate) * 100
                        action = f'盈利{max_profit_rate*100:.2f}%后回落{drawdown_pct:.2f}%止盈'
                    else:
                        action = '卖出'
                    
                    # 全部卖出
                    sell_amount = shares * current_close
                    cash += sell_amount
                    
                    # 计算本次交易的盈亏金额
                    total_cost = cost_basis * shares
                    profit_amount = sell_amount - total_cost
                    
                    trades.append({
                        'date': current_date,
                        'action': action,
                        'price': current_close,
                        'shares': shares,
                        'amount': sell_amount,
                        'cash': cash,
                        'position_value': 0,
                        'total_value': cash,
                        'cost_basis': total_cost,  # 买入成本
                        'profit_amount': profit_amount,  # 盈亏金额
                        'profit_rate': profit_rate * 100,
                        'total_profit_rate': total_profit_rate * 100,
                        'max_profit_rate': max_profit_rate * 100
                    })
                    
                    # 重置持仓状态
                    shares = 0
                    has_position = False
                    buy_date = None
                    max_profit_rate = 0.0
                    highest_price_after_buy = 0.0
                    continue  # 立即退出，不再检查加仓条件
                
                # 加仓条件检查（只有在没有触发卖出条件时才检查）
                # 条件1：持仓已有 > 8% 盈利
                # 条件2：股价再创新高（当天最高价 > 买入后的最高价）
                # 条件3：加仓后总仓位不超过30%
                current_position_ratio = (shares * current_close) / self.initial_capital
                
                # 检查是否创新高（需要是真正的创新高，即当前最高价超过之前记录的最高价）
                is_new_high = current_high > highest_price_after_buy
                
                if (profit_rate >= self.profit_threshold_for_add and 
                    is_new_high and
                    current_position_ratio + self.add_position_ratio <= self.max_position_ratio):
                    
                    # 计算加仓金额（首次仓位的50%，即总资金的10%）
                    target_add_amount = self.initial_capital * self.add_position_ratio
                    add_amount = min(cash, target_add_amount)
                    
                    if add_amount > 0:
                        add_shares = int(add_amount / current_close)
                        if add_shares > 0:
                            old_shares = shares
                            shares += add_shares
                            actual_add_amount = add_shares * current_close
                            cash -= actual_add_amount
                            
                            # 更新成本价（加权平均）
                            cost_basis = (cost_basis * old_shares + current_close * add_shares) / shares
                            
                            # 更新最高价（加仓后重新记录为当前最高价）
                            highest_price_after_buy = current_high
                            
                            # 更新最大盈利（因为成本价变化了，需要重新计算）
                            new_profit_rate = (current_close - cost_basis) / cost_basis if cost_basis > 0 else 0
                            if new_profit_rate > max_profit_rate:
                                max_profit_rate = new_profit_rate
                            
                            trades.append({
                                'date': current_date,
                                'action': '加仓',
                                'price': current_close,
                                'shares': add_shares,
                                'amount': actual_add_amount,
                                'cash': cash,
                                'position_value': shares * current_close,
                                'total_value': cash + shares * current_close,
                                'profit_rate': profit_rate * 100,
                                'position_ratio': (shares * current_close) / self.initial_capital * 100
                            })
                
                # 记录持仓
                positions.append({
                    'date': current_date,
                    'price': current_close,
                    'shares': shares,
                    'cost_basis': cost_basis,
                    'position_value': position_value,
                    'cash': cash,
                    'total_value': total_value,
                    'profit_rate': profit_rate * 100,
                    'total_profit_rate': total_profit_rate * 100
                })
        
        # 计算最终结果
        final_value = cash + shares * df.iloc[-1]['close'] if shares > 0 else cash
        total_return = final_value - self.initial_capital
        total_return_rate = (total_return / self.initial_capital) * 100
        
        # 计算年化收益率
        start_date_str = str(df.iloc[0]['date'])
        end_date_str = str(df.iloc[-1]['date'])
        
        days_diff = 0
        years = 0
        annual_return_rate = 0
        
        try:
            start_date_obj = datetime.strptime(start_date_str, '%Y%m%d')
            end_date_obj = datetime.strptime(end_date_str, '%Y%m%d')
            days_diff = (end_date_obj - start_date_obj).days
            years = days_diff / 365.25
            
            if years > 0:
                if final_value > 0:
                    annual_return_rate = ((final_value / self.initial_capital) ** (1 / years) - 1) * 100
                else:
                    annual_return_rate = -100
        except Exception as e:
            print(f"计算年化收益率时出错: {e}")
        
        result = {
            'stock_code': stock_code,
            'status': 'completed',
            'initial_capital': self.initial_capital,
            'final_value': final_value,
            'total_return': total_return,
            'total_return_rate': total_return_rate,
            'annual_return_rate': annual_return_rate,
            'backtest_days': days_diff,
            'backtest_years': years,
            'max_drawdown': max_drawdown,
            'total_trades': len(trades),
            'trades': trades,
            'positions': positions,
            'buy_signal_stats': buy_signal_stats  # 买入条件统计
        }
        
        # 如果没有交易，打印买入条件统计
        if len(trades) == 0:
            print("\n" + "="*80)
            print("⚠️  未找到买入信号，买入条件统计：")
            print("="*80)
            print(f"可检查天数（数据充足后）: {buy_signal_stats['total_days']} 天")
            print(f"条件1满足（股价 > 60日均线）: {buy_signal_stats['condition1_count']} 天 ({buy_signal_stats['condition1_count']/buy_signal_stats['total_days']*100:.1f}%)" if buy_signal_stats['total_days'] > 0 else "条件1满足: 0 天")
            print(f"条件2满足（60日均线向上）: {buy_signal_stats['condition2_count']} 天 ({buy_signal_stats['condition2_count']/buy_signal_stats['total_days']*100:.1f}%)" if buy_signal_stats['total_days'] > 0 else "条件2满足: 0 天")
            print(f"条件3满足（突破50日最高价）: {buy_signal_stats['condition3_count']} 天 ({buy_signal_stats['condition3_count']/buy_signal_stats['total_days']*100:.1f}%)" if buy_signal_stats['total_days'] > 0 else "条件3满足: 0 天")
            print(f"条件4满足（成交量 > 20日均量）: {buy_signal_stats['condition4_count']} 天 ({buy_signal_stats['condition4_count']/buy_signal_stats['total_days']*100:.1f}%)" if buy_signal_stats['total_days'] > 0 else "条件4满足: 0 天")
            print(f"所有条件同时满足: {buy_signal_stats['all_conditions_count']} 天 ({buy_signal_stats['all_conditions_count']/buy_signal_stats['total_days']*100:.1f}%)" if buy_signal_stats['total_days'] > 0 else "所有条件同时满足: 0 天")
            print("="*80)
            print("💡 提示：买入条件较严格，需要同时满足4个条件。")
            print("   如果某个条件满足率很低，可以考虑放宽该条件。")
            print("="*80 + "\n")
        
        return result
    
    def print_result(self, result):
        """打印回测结果"""
        print("=" * 80)
        print(f"股票代码: {result['stock_code']}")
        print(f"回测状态: {result['status']}")
        print(f"初始资金: {result['initial_capital']:,.2f} 元")
        print(f"最终资产: {result['final_value']:,.2f} 元")
        print(f"总收益: {result['total_return']:+,.2f} 元")
        print(f"总收益率: {result['total_return_rate']:+.2f}%")
        print(f"年化收益率: {result['annual_return_rate']:+.2f}%")
        print(f"最大回撤: {result['max_drawdown']:.2f}%")
        print(f"交易次数: {result['total_trades']}")
        print(f"回测天数: {result['backtest_days']} 天")
        print("=" * 80)
        
        # 打印交易记录
        if result['trades']:
            print("\n交易记录:")
            print("-" * 100)
            print(f"{'日期':<12} {'操作':<15} {'价格':<10} {'数量':<12} {'金额':<12} {'现金':<12} {'总资产':<12} {'收益率':<10}")
            print("-" * 100)
            for trade in result['trades']:
                profit_info = ""
                if 'profit_rate' in trade:
                    profit_info = f"{trade['profit_rate']:.2f}%"
                print(f"{trade['date']:<12} {trade['action']:<15} {trade['price']:<10.2f} "
                      f"{trade['shares']:<12.2f} {trade['amount']:<12.2f} {trade['cash']:<12.2f} "
                      f"{trade['total_value']:<12.2f} {profit_info:<10}")


def load_stock_list_from_csv(csv_file):
    """
    从CSV文件加载股票代码列表
    :param csv_file: CSV文件路径
    :return: 股票代码列表
    """
    try:
        # 读取CSV时，将ts_code列指定为字符串类型，避免前导零丢失
        df = pd.read_csv(csv_file, encoding='utf-8-sig', dtype={'ts_code': str})
        if 'ts_code' not in df.columns:
            print(f"CSV文件中没有找到ts_code列，现有列: {df.columns.tolist()}")
            return []
        
        stock_codes = df['ts_code'].dropna().unique().tolist()
        
        # 处理股票代码格式：去掉后缀（如.SH, .SZ等），添加市场前缀
        processed_codes = []
        for code in stock_codes:
            # 确保是字符串类型，并去除空格
            code_str = str(code).strip()
            
            # 如果是纯数字且长度小于6位，补零到6位（A股代码通常是6位）
            if code_str.isdigit() and len(code_str) < 6:
                code_str = code_str.zfill(6)
            
            if '.' in code_str:
                # 分离代码和市场
                code_part, market = code_str.split('.')
                # 确保代码部分保持6位（如果是数字）
                if code_part.isdigit() and len(code_part) < 6:
                    code_part = code_part.zfill(6)
                market_upper = market.upper()
                # 根据市场添加前缀
                if market_upper == 'SH':
                    processed_codes.append(f'sh{code_part}')
                elif market_upper == 'SZ':
                    processed_codes.append(f'sz{code_part}')
                else:
                    processed_codes.append(code_part)
            else:
                # 没有后缀，根据A股代码规则判断市场
                # 6开头的是上海股票，0、3开头的是深圳股票
                if code_str.startswith('6'):
                    processed_codes.append(f'sh{code_str}')
                elif code_str.startswith('0') or code_str.startswith('3'):
                    processed_codes.append(f'sz{code_str}')
                else:
                    # 其他情况，直接使用
                    processed_codes.append(code_str)
        
        print(f"从CSV文件加载了 {len(processed_codes)} 个股票代码")
        return processed_codes
    
    except Exception as e:
        print(f"读取CSV文件失败: {e}")
        return []


def main():
    """主函数 - 示例用法"""
    # ========== 可修改参数 ==========
    initial_capital = 100000  # 初始资金（元）
    
    # 方式1：从CSV文件读取股票列表
    # CSV文件路径（支持相对路径和绝对路径）
    input_csv_file = "cy_quant/sh_120ma_breakthrough_20260316.csv"
    # 如果文件不在当前目录，尝试使用绝对路径
    if not os.path.exists(input_csv_file):
        # 尝试在当前工作目录下查找
        current_dir = os.getcwd()
        possible_paths = [
            input_csv_file,
            os.path.join(current_dir, input_csv_file),
            os.path.join(current_dir, "..", input_csv_file)
        ]
        for path in possible_paths:
            if os.path.exists(path):
                input_csv_file = path
                break
    
    stock_list = load_stock_list_from_csv(input_csv_file)
    
    # 方式2：手动指定股票列表（如果stock_list为空，使用这个）
    # if not stock_list:
    stock_list = ["002039"]  # 股票代码列表
    
    start_date = None  # 回测开始日期，格式："20240101"，None表示使用全部数据
    end_date = None  # 回测结束日期，格式："20260228"，None表示使用全部数据
    # ================================
    
    if not stock_list:
        print("没有找到股票代码，请检查CSV文件或手动指定股票列表")
        return
    
    # 创建回测器
    backtest = MomentumBreakthroughBacktest(initial_capital=initial_capital)
    
    # 判断是单个股票还是多个股票回测
    if len(stock_list) == 1:
        # 单个股票回测
        stock_code = stock_list[0]
        print(f"\n开始回测股票: {stock_code}")
        print("="*80)
        
        result = backtest.backtest_stock(stock_code, start_date, end_date)
        
        if result:
            backtest.print_result(result)
            
            # 保存交易明细到CSV
            if result.get('trades'):
                # 准备交易明细数据
                trades_data = []
                for trade in result['trades']:
                    trade_row = {
                        '日期': trade.get('date', ''),
                        '操作': trade.get('action', ''),
                        '价格': trade.get('price', 0),
                        '数量': trade.get('shares', 0),
                        '金额': trade.get('amount', 0),
                        '现金': trade.get('cash', 0),
                        '持仓市值': trade.get('position_value', 0),
                        '总资产': trade.get('total_value', 0)
                    }
                    
                    # 买入相关字段
                    if 'stop_loss_price' in trade:
                        trade_row['止损价格'] = trade['stop_loss_price']
                    
                    # 加仓相关字段
                    if 'profit_rate' in trade:
                        trade_row['收益率(%)'] = trade['profit_rate']
                    if 'position_ratio' in trade:
                        trade_row['持仓比例(%)'] = trade['position_ratio']
                    
                    # 卖出相关字段
                    if 'cost_basis' in trade:
                        trade_row['买入成本'] = trade['cost_basis']
                    if 'profit_amount' in trade:
                        trade_row['收益金额'] = trade['profit_amount']
                    if 'max_profit_rate' in trade:
                        trade_row['最大盈利(%)'] = trade['max_profit_rate']
                    if 'total_profit_rate' in trade:
                        trade_row['总账户收益率(%)'] = trade['total_profit_rate']
                    
                    trades_data.append(trade_row)
                
                # 保存到CSV
                trades_df = pd.DataFrame(trades_data)
                timestamp = datetime.now().strftime('%Y%m%d')
                output_file = f"momentum_backtest_{stock_code}_{timestamp}.csv"
                trades_df.to_csv(output_file, index=False, encoding='utf-8-sig')
                print(f"\n交易明细已保存至: {output_file}")
        else:
            print(f"无法找到股票 {stock_code} 的数据文件")
    else:
        # 多个股票回测
        print(f"\n开始回测 {len(stock_list)} 个股票...")
        print("="*80)
        
        results = []
        completed_count = 0
        no_signal_count = 0
        
        for idx, stock_code in enumerate(stock_list, 1):
            print(f"\n[{idx}/{len(stock_list)}] 正在回测: {stock_code}")
            print("-"*80)
            
            result = backtest.backtest_stock(stock_code, start_date, end_date)
            
            if result:
                results.append(result)
                
                # 安全获取total_trades，如果不存在则默认为0
                total_trades = result.get('total_trades', 0)
                
                # 只打印有交易的股票结果
                if total_trades > 0:
                    backtest.print_result(result)
                    completed_count += 1
                else:
                    no_signal_count += 1
                    status = result.get('status', 'unknown')
                    print(f"股票 {stock_code}: {status} - 未找到买入信号")
            
            print()
    
    # 保存汇总结果
    if results:
        summary = []
        for result in results:
            summary_item = {
                '股票代码': result.get('stock_code', 'N/A'),
                '状态': result.get('status', 'unknown'),
                '初始资金': result.get('initial_capital', initial_capital),
                '最终资产': result.get('final_value', initial_capital),
                '总收益': result.get('total_return', 0),
                '总收益率(%)': result.get('total_return_rate', 0),
                '年化收益率(%)': result.get('annual_return_rate', 0),
                '最大回撤(%)': result.get('max_drawdown', 0),
                '交易次数': result.get('total_trades', 0),
                '回测天数': result.get('backtest_days', 0)
            }
            
            # 添加买入条件统计（如果有）
            if 'buy_signal_stats' in result:
                stats = result['buy_signal_stats']
                summary_item['条件1满足次数'] = stats.get('condition1_count', 0)
                summary_item['条件2满足次数'] = stats.get('condition2_count', 0)
                summary_item['条件3满足次数'] = stats.get('condition3_count', 0)
                summary_item['条件4满足次数'] = stats.get('condition4_count', 0)
                summary_item['所有条件满足次数'] = stats.get('all_conditions_count', 0)
            
            summary.append(summary_item)
        
        summary_df = pd.DataFrame(summary)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"momentum_backtest_summary_{timestamp}.csv"
        summary_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        
        # 打印汇总统计
        print("\n" + "="*80)
        print("📊 回测汇总统计")
        print("="*80)
        print(f"总股票数: {len(results)}")
        print(f"有交易的股票: {completed_count}")
        print(f"无买入信号的股票: {no_signal_count}")
        
        if completed_count > 0:
            completed_results = [r for r in results if r.get('total_trades', 0) > 0]
            if completed_results:
                avg_return_rate = np.mean([r.get('total_return_rate', 0) for r in completed_results])
                avg_annual_return = np.mean([r.get('annual_return_rate', 0) for r in completed_results])
                total_trades = sum([r.get('total_trades', 0) for r in completed_results])
            else:
                avg_return_rate = 0
                avg_annual_return = 0
                total_trades = 0
            
            print(f"\n有交易的股票统计:")
            print(f"  平均总收益率: {avg_return_rate:.2f}%")
            print(f"  平均年化收益率: {avg_annual_return:.2f}%")
            print(f"  总交易次数: {total_trades}")
        
        print(f"\n汇总结果已保存至: {output_file}")
        print("="*80)


if __name__ == '__main__':
    main()
