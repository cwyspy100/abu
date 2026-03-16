"""
利弗莫尔投资策略回测系统
策略规则：
1. 初始资金：10万元（可配置）
2. 超过120日均线后，连续3天确认行情（都在均线上方）再买入40%
3. 亏损10%立刻止损
4. 盈利10%，加仓30%
5. 整体盈利10%，加仓20%
6. 直到100%（满仓）
7. 从最大盈利回撤10%卖出（跟踪止盈）
"""

import pandas as pd
import numpy as np
import os
import glob
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')


class LivermoreBacktest:
    """利弗莫尔投资策略回测器"""
    
    def __init__(self, initial_capital=100000, csv_dir=None):
        """
        初始化回测器
        :param initial_capital: 初始资金（元），默认10万元
        :param csv_dir: CSV文件目录，默认为~/abu/data/csv
        """
        self.initial_capital = initial_capital
        self.csv_dir = csv_dir if csv_dir else os.path.expanduser('~/abu/data/csv')
        
        # 策略参数
        self.first_buy_ratio = 0.4  # 首次买入比例40%
        self.stop_loss_ratio = 0.10  # 止损比例10%（相对于成本价）
        self.trailing_stop_ratio = 0.10  # 跟踪止盈比例10%（从最大盈利回撤10%卖出）
        self.profit_add_ratio_1 = 0.3  # 盈利10%后加仓30%
        self.profit_add_ratio_2 = 0.2  # 整体盈利10%后加仓20%
        self.profit_threshold_1 = 0.1  # 盈利10%阈值
        self.profit_threshold_2 = 0.1  # 整体盈利10%阈值
        self.confirm_days = 3  # 突破后确认天数（连续N天在均线上方才买入）
        
    def calculate_120ma(self, df, slope_period=20):
        """
        计算120日均线和均线斜率
        :param df: 包含date和close的DataFrame
        :param slope_period: 计算斜率使用的周期（默认20天）
        :return: 添加了ma120和ma120_slope列的DataFrame
        """
        df = df.copy()
        # 按日期排序
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        # 计算120日均线
        df['ma120'] = df['close'].rolling(window=120, min_periods=120).mean()
        
        # 将前119天的ma120值填充为对应的close值
        df['ma120'] = df['ma120'].fillna(df['close'])
        
        # 计算120日均线的斜率（使用slope_period天的变化率）
        # 斜率 = (当前均线值 - N天前的均线值) / N
        # 使用shift和diff方法更高效
        df['ma120_slope'] = 0.0
        
        # 计算斜率：当前均线值 - slope_period天前的均线值，然后除以天数
        if len(df) > slope_period:
            ma120_shifted = df['ma120'].shift(slope_period)
            df['ma120_slope'] = (df['ma120'] - ma120_shifted) / slope_period
            # 将NaN值填充为0
            df['ma120_slope'] = df['ma120_slope'].fillna(0.0)
        else:
            # 如果数据不足slope_period天，斜率设为0
            df['ma120_slope'] = 0.0
        
        return df
    
    def find_breakthrough_points(self, df):
        """
        找出所有突破120日均线的点
        :param df: 包含ma120和close的DataFrame
        :return: 突破点的索引列表
        """
        if df is None or df.empty or 'ma120' not in df.columns or 'close' not in df.columns:
            return []
        
        # 确保数据按日期排序
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        # 找出价格超过120日均线的位置
        df['above_ma120'] = df['close'] > df['ma120']
        
        # 找出突破点（从下方突破到上方）
        breakthrough_points = []
        for i in range(1, len(df)):
            if not df.iloc[i-1]['above_ma120'] and df.iloc[i]['above_ma120']:
                breakthrough_points.append(i)
        
        return breakthrough_points
    
    def backtest_stock(self, stock_code, start_date=None, end_date=None):
        """
        回测单个股票
        支持A股、港股、美股：
        - A股：'600000' 或 'sh600000' 或 'sz000001'
        - 港股：'hk00700' 或 '00700'
        - 美股：'usAAPL' 或 'AAPL'
        :param stock_code: 股票代码
        :param start_date: 开始日期（可选，格式：'YYYYMMDD'）
        :param end_date: 结束日期（可选，格式：'YYYYMMDD'）
        :return: 回测结果字典
        """
        # 查找股票文件
        stock_file = self.find_stock_file(stock_code)
        if stock_file is None:
            return None
        
        # 读取股票数据（支持有扩展名和无扩展名的文件）
        try:
            df = pd.read_csv(stock_file, encoding='utf-8-sig', sep=',')
        except:
            try:
                df = pd.read_csv(stock_file, encoding='gbk', sep=',')
            except:
                try:
                    df = pd.read_csv(stock_file, encoding='utf-8', sep=',')
                except:
                    # 如果都失败，尝试使用制表符分隔
                    try:
                        df = pd.read_csv(stock_file, encoding='utf-8-sig', sep='\t')
                    except:
                        df = pd.read_csv(stock_file, encoding='gbk', sep='\t')
        
        if df.empty:
            return None
        
        # 确保有date和close列
        if 'date' in df.columns:
            df = df.rename(columns={'date': 'trade_date'})
        
        if 'trade_date' not in df.columns or 'close' not in df.columns:
            return None
        
        # 筛选日期范围
        if start_date:
            df = df[df['trade_date'] >= start_date]
        if end_date:
            df = df[df['trade_date'] <= end_date]
        
        if df.empty:
            return None
        
        # 计算120日均线
        df_with_ma = self.calculate_120ma(df)
        
        # 找出突破点
        breakthrough_points = self.find_breakthrough_points(df_with_ma)
        
        if not breakthrough_points:
            return {
                'stock_code': stock_code,
                'status': 'no_breakthrough',
                'total_return': 0,
                'total_return_rate': 0,
                'max_drawdown': 0,
                'trades': []
            }
        
        # 执行回测
        return self.execute_backtest(df_with_ma, breakthrough_points, stock_code)
    
    def execute_backtest(self, df, breakthrough_points, stock_code):
        """
        执行回测逻辑
        策略逻辑：
        1. 超过120日均线后，连续3天确认行情（都在均线上方）再买入40%
        2. 当持仓增长10%时（相对于成本价），加仓30%
        3. 当持仓盈利再增加10%时（相对于第一次加仓后的成本价），加仓20%
        4. 再增加10%时（相对于第二次加仓后的成本价），加仓10%
        5. 卖出条件（满足任一即卖出）：
           - 持仓亏损10%（相对于成本价）止损
           - 从最大盈利回撤10%（跟踪止盈）
           - 价格跌破120日均线
        """
        cash = self.initial_capital  # 现金
        shares = 0  # 持股数量
        cost_basis = 0  # 当前成本价
        total_value = cash  # 总资产
        
        trades = []  # 交易记录
        positions = []  # 持仓记录
        
        # 状态标记
        has_position = False  # 是否有持仓
        profit_add_1_done = False  # 是否完成第一次加仓（30%）
        profit_add_2_done = False  # 是否完成第二次加仓（20%）
        profit_add_3_done = False  # 是否完成第三次加仓（10%）
        
        # 记录每次加仓后的成本价基准（用于计算下次加仓条件）
        cost_basis_after_add1 = None  # 第一次加仓后的成本价
        cost_basis_after_add2 = None  # 第二次加仓后的成本价
        
        # 买入确认机制：突破后等待确认天数
        breakthrough_waiting = None  # 突破点索引，等待确认后买入
        confirm_count = 0  # 确认计数（连续在均线上方的天数）
        
        # 跟踪止盈：记录买入后的最大盈利
        max_profit_rate = 0.0  # 买入后的最大盈利比例（相对于成本价）
        
        max_value = self.initial_capital  # 最大资产值（用于计算最大回撤）
        max_drawdown = 0  # 最大回撤
        
        # 从第一个突破点开始逐日回测
        for i in range(len(df)):
            current_price = df.iloc[i]['close']
            current_date = df.iloc[i]['trade_date']
            current_ma120 = df.iloc[i]['ma120']
            
            # 如果没有持仓，检查是否突破120日均线
            if not has_position:
                # 检查是否是突破点
                if i in breakthrough_points:
                    if current_price > current_ma120:
                        # 记录突破点，开始等待确认
                        breakthrough_waiting = i
                        confirm_count = 1  # 突破当天算第1天
                
                # 如果正在等待确认突破
                if breakthrough_waiting is not None:
                    if current_price > current_ma120:
                        # 价格仍在均线上方，增加确认计数
                        confirm_count += 1
                        
                        # 如果确认天数达到要求，执行买入
                        if confirm_count >= self.confirm_days:
                            # 首次买入40%
                            buy_amount = cash * self.first_buy_ratio
                            shares = buy_amount / current_price
                            cash -= buy_amount
                            cost_basis = current_price
                            has_position = True
                            
                            # 重置加仓状态
                            profit_add_1_done = False
                            profit_add_2_done = False
                            profit_add_3_done = False
                            cost_basis_after_add1 = None
                            cost_basis_after_add2 = None
                            
                            # 重置确认状态
                            breakthrough_waiting = None
                            confirm_count = 0
                            
                            # 重置跟踪止盈
                            max_profit_rate = 0.0
                            
                            trades.append({
                                'date': current_date,
                                'action': '买入',
                                'price': current_price,
                                'shares': shares,
                                'amount': buy_amount,
                                'cash': cash,
                                'position_value': shares * current_price,
                                'total_value': cash + shares * current_price,
                                'confirm_days': self.confirm_days
                            })
                    else:
                        # 在确认期间价格跌破均线，取消买入
                        breakthrough_waiting = None
                        confirm_count = 0
            
            # 如果有持仓，检查止损和加仓条件
            if has_position:
                position_value = shares * current_price
                total_value = cash + position_value
                
                # 更新最大资产值
                if total_value > max_value:
                    max_value = total_value
                
                # 计算回撤
                drawdown = (max_value - total_value) / max_value * 100
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
                
                # 计算盈亏比例（基于当前成本价）
                profit_rate = (current_price - cost_basis) / cost_basis if cost_basis > 0 else 0
                total_profit_rate = (total_value - self.initial_capital) / self.initial_capital
                
                # 更新最大盈利（跟踪止盈）
                # 只有当盈利还在增长时才更新最大盈利
                if profit_rate > max_profit_rate:
                    max_profit_rate = profit_rate
                
                # 卖出条件检查（三个条件哪个先到先触发，优先级最高）
                # 条件1：当前持仓相对于成本价损失10%（止损）
                position_loss_triggered = profit_rate <= -self.stop_loss_ratio
                
                # 条件2：从最大盈利回撤10%（跟踪止盈）
                # 逻辑：盈利达到最大值后，如果盈利不再增长（当前盈利 < 最大盈利），
                # 且从最大盈利回撤了10个百分点，则卖出
                trailing_stop_triggered = False
                if max_profit_rate > 0:  # 只有当曾经盈利过才检查跟踪止盈
                    # 检查盈利是否不再增长（当前盈利 < 最大盈利）
                    if profit_rate < max_profit_rate:
                        # 计算从最大盈利的回撤（百分点）
                        drawdown_from_max = max_profit_rate - profit_rate
                        # 如果回撤超过10个百分点，触发跟踪止盈
                        if drawdown_from_max >= self.trailing_stop_ratio:
                            trailing_stop_triggered = True
                
                # 条件3：价格跌破120日均线
                below_ma120 = current_price < current_ma120
                
                # 哪个先到先触发
                if position_loss_triggered or trailing_stop_triggered or below_ma120:
                    # 确定卖出原因
                    if position_loss_triggered and below_ma120:
                        action = f'持仓损失{abs(profit_rate)*100:.2f}%且跌破均线卖出'
                    elif position_loss_triggered:
                        action = f'持仓损失{abs(profit_rate)*100:.2f}%卖出'
                    elif trailing_stop_triggered and below_ma120:
                        drawdown_pct = (max_profit_rate - profit_rate) * 100
                        action = f'从最大盈利{max_profit_rate*100:.2f}%回撤{drawdown_pct:.2f}%且跌破均线卖出'
                    elif trailing_stop_triggered:
                        drawdown_pct = (max_profit_rate - profit_rate) * 100
                        action = f'从最大盈利{max_profit_rate*100:.2f}%回撤{drawdown_pct:.2f}%卖出'
                    else:
                        action = '跌破均线卖出'
                    
                    # 全部卖出
                    sell_amount = shares * current_price
                    cash += sell_amount
                    
                    trades.append({
                        'date': current_date,
                        'action': action,
                        'price': current_price,
                        'shares': shares,
                        'amount': sell_amount,
                        'cash': cash,
                        'position_value': 0,
                        'total_value': cash,
                        'profit_rate': profit_rate * 100,
                        'total_profit_rate': total_profit_rate * 100,
                        'max_profit_rate': max_profit_rate * 100
                    })
                    
                    # 重置持仓状态
                    shares = 0
                    has_position = False
                    profit_add_1_done = False
                    profit_add_2_done = False
                    profit_add_3_done = False
                    cost_basis_after_add1 = None
                    cost_basis_after_add2 = None
                    max_profit_rate = 0.0  # 重置最大盈利
                    continue  # 立即退出，不再检查加仓条件
                
                # 加仓条件检查（只有在没有触发卖出条件时才检查）
                # 加仓条件1：首次买入40%后，持仓增长10%（相对于成本价），加仓30%
                if profit_rate >= self.profit_threshold_1 and not profit_add_1_done:
                    # 计算应该加仓的金额（基于初始资金的30%）
                    target_add_amount = self.initial_capital * self.profit_add_ratio_1
                    # 实际加仓金额不能超过可用现金
                    add_amount = min(cash, target_add_amount)
                    current_position_ratio = (shares * current_price) / self.initial_capital
                    if add_amount > 0 and current_position_ratio + (add_amount / self.initial_capital) <= 1.0:
                        add_shares = add_amount / current_price
                        old_shares = shares
                        shares += add_shares
                        cash -= add_amount
                        # 更新成本价（加权平均）
                        cost_basis = (cost_basis * old_shares + current_price * add_shares) / shares
                        cost_basis_after_add1 = cost_basis  # 记录第一次加仓后的成本价
                        profit_add_1_done = True
                        
                        # 加仓后更新最大盈利（因为成本价变化了，需要重新计算）
                        new_profit_rate = (current_price - cost_basis) / cost_basis if cost_basis > 0 else 0
                        if new_profit_rate > max_profit_rate:
                            max_profit_rate = new_profit_rate
                        
                        trades.append({
                            'date': current_date,
                            'action': '加仓30%',
                            'price': current_price,
                            'shares': add_shares,
                            'amount': add_amount,
                            'cash': cash,
                            'position_value': shares * current_price,
                            'total_value': cash + shares * current_price,
                            'profit_rate': profit_rate * 100,
                            'position_ratio': (shares * current_price) / self.initial_capital * 100
                        })
                
                # 加仓条件2：第一次加仓30%后，持仓盈利再增加10%（相对于第一次加仓后的成本价），加仓20%
                if profit_add_1_done and cost_basis_after_add1 is not None:
                    # 计算相对于第一次加仓后成本价的盈利
                    profit_rate_after_add1 = (current_price - cost_basis_after_add1) / cost_basis_after_add1 if cost_basis_after_add1 > 0 else 0
                    
                    if profit_rate_after_add1 >= self.profit_threshold_1 and not profit_add_2_done:
                        # 计算应该加仓的金额（基于初始资金的20%）
                        target_add_amount = self.initial_capital * self.profit_add_ratio_2
                        # 实际加仓金额不能超过可用现金
                        add_amount = min(cash, target_add_amount)
                        current_position_ratio = (shares * current_price) / self.initial_capital
                        if add_amount > 0 and current_position_ratio + (add_amount / self.initial_capital) <= 1.0:
                            add_shares = add_amount / current_price
                            old_shares = shares
                            shares += add_shares
                            cash -= add_amount
                            # 更新成本价（加权平均）
                            cost_basis = (cost_basis * old_shares + current_price * add_shares) / shares
                            cost_basis_after_add2 = cost_basis  # 记录第二次加仓后的成本价
                            profit_add_2_done = True
                            
                            # 加仓后更新最大盈利（因为成本价变化了，需要重新计算）
                            new_profit_rate = (current_price - cost_basis) / cost_basis if cost_basis > 0 else 0
                            if new_profit_rate > max_profit_rate:
                                max_profit_rate = new_profit_rate
                            
                            trades.append({
                                'date': current_date,
                                'action': '加仓20%',
                                'price': current_price,
                                'shares': add_shares,
                                'amount': add_amount,
                                'cash': cash,
                                'position_value': shares * current_price,
                                'total_value': cash + shares * current_price,
                                'profit_rate': profit_rate_after_add1 * 100,
                                'total_profit_rate': total_profit_rate * 100,
                                'position_ratio': (shares * current_price) / self.initial_capital * 100
                            })
                
                # 加仓条件3：第二次加仓20%后，持仓盈利再增加10%（相对于第二次加仓后的成本价），加仓10%
                if profit_add_2_done and cost_basis_after_add2 is not None:
                    # 计算相对于第二次加仓后成本价的盈利
                    profit_rate_after_add2 = (current_price - cost_basis_after_add2) / cost_basis_after_add2 if cost_basis_after_add2 > 0 else 0
                    
                    if profit_rate_after_add2 >= self.profit_threshold_1 and not profit_add_3_done:
                        # 计算应该加仓的金额（基于初始资金的10%）
                        target_add_amount = self.initial_capital * 0.1
                        # 实际加仓金额不能超过可用现金
                        add_amount = min(cash, target_add_amount)
                        current_position_ratio = (shares * current_price) / self.initial_capital
                        if add_amount > 0 and current_position_ratio + (add_amount / self.initial_capital) <= 1.0:
                            add_shares = add_amount / current_price
                            old_shares = shares
                            shares += add_shares
                            cash -= add_amount
                            # 更新成本价（加权平均）
                            cost_basis = (cost_basis * old_shares + current_price * add_shares) / shares
                            profit_add_3_done = True
                            
                            # 加仓后更新最大盈利（因为成本价变化了，需要重新计算）
                            new_profit_rate = (current_price - cost_basis) / cost_basis if cost_basis > 0 else 0
                            if new_profit_rate > max_profit_rate:
                                max_profit_rate = new_profit_rate
                            
                            trades.append({
                                'date': current_date,
                                'action': '加仓10%',
                                'price': current_price,
                                'shares': add_shares,
                                'amount': add_amount,
                                'cash': cash,
                                'position_value': shares * current_price,
                                'total_value': cash + shares * current_price,
                                'profit_rate': profit_rate_after_add2 * 100,
                                'total_profit_rate': total_profit_rate * 100,
                                'position_ratio': (shares * current_price) / self.initial_capital * 100
                            })
                
                # 记录持仓
                positions.append({
                    'date': current_date,
                    'price': current_price,
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
        # 获取回测时间跨度
        start_date_str = str(df.iloc[0]['trade_date'])
        end_date_str = str(df.iloc[-1]['trade_date'])
        
        # 计算天数
        days_diff = 0
        years = 0
        annual_return_rate = 0
        
        try:
            start_date_obj = datetime.strptime(start_date_str, '%Y%m%d')
            end_date_obj = datetime.strptime(end_date_str, '%Y%m%d')
            days_diff = (end_date_obj - start_date_obj).days
            years = days_diff / 365.25  # 考虑闰年
            
            # 计算年化收益率
            if years > 0:
                if final_value > 0:
                    # 年化收益率公式: (最终价值/初始价值)^(1/年数) - 1
                    annual_return_rate = ((final_value / self.initial_capital) ** (1 / years) - 1) * 100
                else:
                    annual_return_rate = -100  # 全部亏损
        except Exception as e:
            print(f"计算年化收益率时出错: {e}")
            days_diff = 0
            years = 0
            annual_return_rate = 0
        
        return {
            'stock_code': stock_code,
            'status': 'completed',
            'initial_capital': self.initial_capital,
            'final_value': final_value,
            'total_return': total_return,
            'total_return_rate': total_return_rate,
            'annual_return_rate': annual_return_rate,
            'backtest_days': days_diff if 'days_diff' in locals() else 0,
            'backtest_years': years,
            'max_drawdown': max_drawdown,
            'total_trades': len(trades),
            'trades': trades,
            'positions': positions
        }
    
    def find_stock_file(self, stock_code):
        """
        查找股票文件
        支持多种股票代码格式：
        - A股：'600000' 或 'sh600000' 或 'sz000001'
        - 港股：'hk00700' 或 '00700'（会自动尝试hk前缀）
        - 美股：'usAAPL' 或 'AAPL'（会自动尝试us前缀）
        :param stock_code: 股票代码
        :return: 文件路径或None
        """
        # 处理股票代码格式
        original_code = stock_code
        if '.' in stock_code:
            stock_code = stock_code.split('.')[0]
        
        # 尝试不同的前缀（包括A股、港股、美股）
        prefixes = ['sh', 'sz', 'hk', 'us']
        for prefix in prefixes:
            if stock_code.startswith(prefix):
                code = stock_code[len(prefix):]
                # 尝试带.csv扩展名的文件
                pattern = os.path.join(self.csv_dir, f'{prefix}{code}_*.csv')
                files = glob.glob(pattern)
                if files:
                    return files[0]  # 返回第一个匹配的文件
                # 尝试不带扩展名的文件
                pattern = os.path.join(self.csv_dir, f'{prefix}{code}_*')
                files = glob.glob(pattern)
                # 过滤掉已经是.csv的文件（避免重复）
                files = [f for f in files if not f.endswith('.csv')]
                if files:
                    return files[0]  # 返回第一个匹配的文件
        
        # 如果没有前缀，尝试所有可能的前缀（A股、港股、美股）
        all_prefixes = ['sh', 'sz', 'hk', 'us']
        for prefix in all_prefixes:
            # 尝试带.csv扩展名的文件
            pattern = os.path.join(self.csv_dir, f'{prefix}{stock_code}_*.csv')
            files = glob.glob(pattern)
            if files:
                return files[0]
            # 尝试不带扩展名的文件
            pattern = os.path.join(self.csv_dir, f'{prefix}{stock_code}_*')
            files = glob.glob(pattern)
            # 过滤掉已经是.csv的文件（避免重复）
            files = [f for f in files if not f.endswith('.csv')]
            if files:
                return files[0]
        
        # 如果找不到，打印调试信息
        print(f"无法找到股票文件: {original_code}")
        print(f"搜索目录: {self.csv_dir}")
        print(f"尝试的模式: sh{stock_code}_*, sz{stock_code}_*, hk{stock_code}_*, us{stock_code}_*")
        
        return None
    
    def backtest_stocks(self, stock_list, start_date=None, end_date=None):
        """
        回测多个股票
        :param stock_list: 股票代码列表
        :param start_date: 开始日期（可选）
        :param end_date: 结束日期（可选）
        :return: 回测结果列表
        """
        results = []
        for stock_code in stock_list:
            print(f"正在回测股票: {stock_code}")
            result = self.backtest_stock(stock_code, start_date, end_date)
            if result:
                results.append(result)
        return results
    
    def print_result(self, result):
        """
        打印回测结果
        :param result: 回测结果字典
        """
        print("=" * 60)
        print(f"股票代码: {result['stock_code']}")
        print(f"初始资金: {result['initial_capital']:,.2f} 元")
        print(f"最终资产: {result['final_value']:,.2f} 元")
        print(f"总收益: {result['total_return']:,.2f} 元")
        print(f"总收益率: {result['total_return_rate']:.2f}%")
        print("-" * 60)
        
        # 显示年化收益率（重点突出）
        annual_return_rate = result.get('annual_return_rate', 0)
        backtest_days = result.get('backtest_days', 0)
        backtest_years = result.get('backtest_years', 0)
        
        print(f"【年化收益率】: {annual_return_rate:.2f}%")
        if backtest_days > 0:
            print(f"回测天数: {backtest_days} 天")
        if backtest_years > 0:
            print(f"回测年数: {backtest_years:.2f} 年")
        print("-" * 60)
        
        print(f"最大回撤: {result['max_drawdown']:.2f}%")
        print(f"交易次数: {result['total_trades']}")
        print("=" * 60)
        
        # 打印交易记录
        if result['trades']:
            print("\n交易记录:")
            print("-" * 100)
            print(f"{'日期':<12} {'操作':<10} {'价格':<10} {'数量':<12} {'金额':<12} {'现金':<12} {'总资产':<12} {'收益率':<10}")
            print("-" * 100)
            for trade in result['trades']:
                profit_info = ""
                if 'profit_rate' in trade:
                    profit_info = f"{trade['profit_rate']:.2f}%"
                if 'total_profit_rate' in trade:
                    profit_info += f" ({trade['total_profit_rate']:.2f}%)"
                
                print(f"{trade['date']:<12} {trade['action']:<10} {trade['price']:<10.2f} "
                      f"{trade['shares']:<12.2f} {trade['amount']:<12.2f} {trade['cash']:<12.2f} "
                      f"{trade['total_value']:<12.2f} {profit_info:<10}")


def main():
    """
    主函数 - 示例用法
    可以修改以下参数：
    - initial_capital: 初始资金（元），默认10万元
    - stock_list: 股票代码列表，可以添加多个股票
      支持格式：
      - A股：'600000' 或 'sh600000' 或 'sz000001'
      - 港股：'hk00700' 或 '00700'
      - 美股：'usAAPL' 或 'AAPL'
    - start_date: 回测开始日期（可选）
    - end_date: 回测结束日期（可选）
    
    示例：
    - A股：["600000", "sh600519", "sz000001"]
    - 港股：["hk00700", "00700"]
    - 美股：["usAAPL", "AAPL", "usTSLA"]
    - 混合：["600000", "hk00700", "usAAPL"]
    """
    # ========== 可修改参数 ==========
    initial_capital = 100000  # 初始资金（元），可以修改，每个10万为一个单位
    # 股票代码列表，支持A股、港股、美股
    # A股示例：["600000", "sh600519", "sz000001"]
    # 港股示例：["hk00700", "00700"]
    # 美股示例：["usAAPL", "AAPL", "usTSLA"]
    # 混合示例：["600000", "hk00700", "usAAPL"]
    stock_list = ["usAAPL"]  # 股票代码列表，可以添加多个股票
    start_date = None  # 回测开始日期，格式："20240101"，None表示使用全部数据
    end_date = None  # 回测结束日期，格式："20260228"，None表示使用全部数据
    # ================================
    
    # 创建回测器
    backtest = LivermoreBacktest(initial_capital=initial_capital)
    
    # 回测单个或多个股票
    if len(stock_list) == 1:
        # 单个股票回测
        stock_code = stock_list[0]
        print(f"开始回测股票: {stock_code}")
        result = backtest.backtest_stock(stock_code, start_date, end_date)
        
        if result:
            backtest.print_result(result)
            
            # 保存结果到CSV
            if result['trades']:
                trades_df = pd.DataFrame(result['trades'])
                output_file = f"livermore_backtest_{stock_code}_{datetime.now().strftime('%Y%m%d')}.csv"
                trades_df.to_csv(output_file, index=False, encoding='utf-8-sig')
                print(f"\n交易记录已保存至: {output_file}")
        else:
            print(f"无法找到股票 {stock_code} 的数据文件")
    else:
        # 多个股票回测
        print(f"开始回测 {len(stock_list)} 个股票...")
        results = backtest.backtest_stocks(stock_list, start_date, end_date)
        
        # 汇总结果
        summary = []
        for result in results:
            summary_item = {
                '股票代码': result['stock_code'],
                '初始资金': result['initial_capital'],
                '最终资产': result['final_value'],
                '总收益': result['total_return'],
                '总收益率(%)': result['total_return_rate'],
                '最大回撤(%)': result['max_drawdown'],
                '交易次数': result['total_trades']
            }
            # 添加年化收益率
            if 'annual_return_rate' in result:
                summary_item['年化收益率(%)'] = result['annual_return_rate']
            if 'backtest_days' in result:
                summary_item['回测天数'] = result['backtest_days']
            summary.append(summary_item)
            backtest.print_result(result)
            print()
        
        # 保存汇总结果
        summary_df = pd.DataFrame(summary)
        output_file = f"livermore_backtest_summary_{datetime.now().strftime('%Y%m%d')}.csv"
        summary_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\n汇总结果已保存至: {output_file}")


if __name__ == '__main__':
    main()
