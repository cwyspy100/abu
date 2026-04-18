"""
AI多因子选股系统
基于Lasso模型的智能选股工具

因子构建：
1. Factor_M: 量价协同动量 (Volume-Price Momentum)
   逻辑：只有"放量上涨"才代表主力资金介入
   公式：EMA(Sign(p_change) * volume * Power(Abs(p_change), 2), 20)

2. Factor_Q: 波动调优质量 (ATR-Adjusted Quality)
   逻辑：低波动下的稳定上涨被视为高持仓质量
   公式：EMA(p_change, 20) / (atr21 / close)

3. Factor_V: ATR波动极值 (风险控制)
   逻辑：剔除极端放量、投机性过强的标的
   公式：atr14 / close

模型：Lasso回归进行因子合成和选股
"""

import pandas as pd
import numpy as np
import os
import glob
from datetime import datetime, timedelta
from sklearn.linear_model import Lasso
from sklearn.preprocessing import StandardScaler
import warnings
warnings.filterwarnings('ignore')


class AIFactorStockPicker:
    """AI多因子选股器"""
    
    def __init__(self, prefixes=None, csv_dir=None, train_window=250, alpha=0.001):
        """
        初始化
        :param prefixes: 文件前缀列表，默认为['sh', 'sz']
        :param csv_dir: CSV文件目录，默认为~/abu/data/csv
        :param train_window: 训练窗口（交易日），默认250天（约1年）
        :param alpha: Lasso惩罚系数，默认0.001
        """
        self.csv_dir = csv_dir if csv_dir else os.path.expanduser('~/abu/csv_his/')
        self.results = []
        if prefixes is None:
            prefixes = ['sh', 'sz']
        self.prefixes = prefixes if isinstance(prefixes, list) else [prefixes]
        
        self.train_window = train_window
        self.alpha = alpha
        self.model = None
        self.scaler = StandardScaler()
        
    def get_stock_files(self):
        """获取所有指定前缀开头的文件"""
        all_files = []
        patterns = []
        for prefix in self.prefixes:
            patterns.append(os.path.join(self.csv_dir, f'{prefix}*.csv'))
            patterns.append(os.path.join(self.csv_dir, f'{prefix}*'))
        
        for pattern in patterns:
            files = glob.glob(pattern)
            for f in files:
                if f not in all_files:
                    all_files.append(f)
        
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
        """解析文件名获取股票代码"""
        filename = os.path.basename(filepath)
        if filename.endswith('.csv'):
            filename = filename[:-4]
        parts = filename.split('_')
        if len(parts) >= 3:
            code_part = parts[0]
            start_date = parts[1]
            end_date = parts[2]
            
            prefix_to_exchange = {'sh': 'SH', 'sz': 'SZ', 'hk': 'HK', 'us': 'US'}
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
    
    def calculate_factors(self, df):
        """
        计算三个AI因子
        :param df: 包含p_change, volume, atr21, atr14, close的DataFrame
        :return: 添加了因子的DataFrame
        """
        df = df.copy()
        
        # 统一列名
        if 'date' in df.columns and 'trade_date' not in df.columns:
            df = df.rename(columns={'date': 'trade_date'})
        
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        # 确保必要列存在
        required_cols = ['p_change', 'volume', 'atr21', 'atr14', 'close']
        for col in required_cols:
            if col not in df.columns:
                print(f"警告: 缺少必要列 {col}")
                return None
        
        # ========== Factor_M: 量价协同动量 ==========
        # EMA(Sign(p_change) * volume * Power(Abs(p_change), 2), 20)
        sign_pc = np.sign(df['p_change'])
        abs_pc_sq = np.abs(df['p_change']) ** 2
        df['momentum_raw'] = sign_pc * df['volume'] * abs_pc_sq
        # EMA20
        df['Factor_M'] = df['momentum_raw'].ewm(span=20, adjust=False).mean()
        
        # ========== Factor_Q: 波动调优质量 ==========
        # EMA(p_change, 20) / (atr21 / close)
        ema_pchange = df['p_change'].ewm(span=20, adjust=False).mean()
        atr_adjusted = df['atr21'] / df['close']
        df['Factor_Q'] = ema_pchange / atr_adjusted.replace(0, np.nan)
        df['Factor_Q'] = df['Factor_Q'].fillna(0)
        
        # ========== Factor_V: ATR波动极值（风险因子） ==========
        # atr14 / close
        df['Factor_V'] = df['atr14'] / df['close']
        
        # 计算未来5日收益率（预测目标）
        df['future_return_5d'] = df['p_change'].rolling(window=5).sum().shift(-5)
        
        return df
    
    def rank_standardize(self, series):
        """截面Rank标准化（0-1）"""
        return (series.rank() - 1) / (len(series) - 1) if len(series) > 1 else series * 0
    
    def prepare_training_data(self, all_stock_data):
        """
        准备Lasso模型的训练数据
        :param all_stock_data: 所有股票的历史数据字典 {ts_code: df}
        :return: X_train, y_train
        """
        X_list = []
        y_list = []
        
        debug_info = {'too_short': 0, 'no_future': 0, 'nan_values': 0, 'valid': 0}
        
        for ts_code, df in all_stock_data.items():
            if df is None or len(df) < self.train_window + 5:
                debug_info['too_short'] += 1
                continue
            
            # 取最近train_window天的数据
            recent_df = df.iloc[-self.train_window:].copy()
            
            # 获取因子值（最后一天）
            last_row = recent_df.iloc[-1]
            
            # 检查因子值
            factor_m = last_row['Factor_M']
            factor_q = last_row['Factor_Q']
            factor_v = last_row['Factor_V']
            
            if any(pd.isna(v) for v in [factor_m, factor_q, factor_v]):
                debug_info['nan_values'] += 1
                continue
            
            # 获取未来5日收益（预测目标）
            future_return = last_row['future_return_5d']
            
            if pd.isna(future_return):
                debug_info['no_future'] += 1
                continue
            
            # 有效样本
            factors = [factor_m, factor_q, factor_v]
            X_list.append(factors)
            y_list.append(future_return)
            debug_info['valid'] += 1
        
        print(f"\n训练样本统计:")
        print(f"  数据长度不足: {debug_info['too_short']}")
        print(f"  因子值为NaN: {debug_info['nan_values']}")
        print(f"  无未来收益: {debug_info['no_future']}")
        print(f"  有效样本: {debug_info['valid']}")
        
        if len(X_list) < 30:
            print(f"警告: 训练样本仅{len(X_list)}个，需要至少30个")
            return None, None
        
        X = np.array(X_list)
        y = np.array(y_list)
        
        print(f"\n因子值范围:")
        print(f"  Factor_M: [{X[:,0].min():.2e}, {X[:,0].max():.2e}]")
        print(f"  Factor_Q: [{X[:,1].min():.4f}, {X[:,1].max():.4f}]")
        print(f"  Factor_V: [{X[:,2].min():.4f}, {X[:,2].max():.4f}]")
        
        # 标准化
        X = self.scaler.fit_transform(X)
        
        return X, y
    
    def train_model(self, X, y):
        """训练Lasso模型"""
        if X is None or y is None:
            return False
        
        self.model = Lasso(alpha=self.alpha, max_iter=10000, random_state=42)
        self.model.fit(X, y)
        
        print("\nLasso模型训练完成")
        print(f"特征权重: Factor_M={self.model.coef_[0]:.4f}, "
              f"Factor_Q={self.model.coef_[1]:.4f}, "
              f"Factor_V={self.model.coef_[2]:.4f}")
        print(f"截距: {self.model.intercept_:.4f}")
        print(f"R²得分: {self.model.score(X, y):.4f}")
        
        return True
    
    def predict_score(self, factors):
        """使用模型预测得分"""
        if self.model is None:
            return 0
        
        X = np.array([factors])
        X = self.scaler.transform(X)
        score = self.model.predict(X)[0]
        return score
    
    def select_stocks(self, top_n=20):
        """
        执行选股
        :param top_n: 选取前N只股票
        :return: 选股结果DataFrame
        """
        stock_files = self.get_stock_files()
        
        if not stock_files:
            print("没有找到股票数据文件")
            return pd.DataFrame()
        
        print(f"\n开始处理 {len(stock_files)} 个股票文件...")
        print(f"训练窗口要求: {self.train_window} 天")
        print("="*80)
        
        # 第一步：计算所有股票的因子
        all_stock_data = {}
        valid_stocks = []
        
        # 统计信息
        stats = {
            'total': len(stock_files),
            'read_error': 0,
            'data_too_short': 0,
            'missing_cols': 0,
            'factor_error': 0,
            'valid': 0
        }
        
        for idx, filepath in enumerate(stock_files, 1):
            if idx % 100 == 0:
                print(f"已处理 {idx}/{len(stock_files)} 个文件...")
            
            try:
                # 解析文件名
                parse_result = self.parse_filename(filepath)
                if parse_result is None:
                    continue
                
                ts_code, _, _ = parse_result
                
                # 读取数据
                try:
                    df = pd.read_csv(filepath, encoding='utf-8-sig')
                except:
                    try:
                        df = pd.read_csv(filepath, encoding='gbk')
                    except Exception as e:
                        stats['read_error'] += 1
                        continue
                
                if df.empty:
                    stats['read_error'] += 1
                    continue
                
                # 检查数据长度
                if len(df) < 30:  # 至少需要30天数据才能计算因子
                    stats['data_too_short'] += 1
                    continue
                
                # 检查必要列
                required_cols = ['p_change', 'volume', 'atr21', 'atr14', 'close']
                missing = [c for c in required_cols if c not in df.columns]
                if missing:
                    stats['missing_cols'] += 1
                    if idx <= 3:
                        print(f"  [{idx}] {ts_code} 缺少列: {missing}")
                    continue
                
                # 计算因子
                df_with_factors = self.calculate_factors(df)
                if df_with_factors is None:
                    stats['factor_error'] += 1
                    continue
                
                # 检查因子值是否有效
                last_row = df_with_factors.iloc[-1]
                if pd.isna(last_row['Factor_M']) or pd.isna(last_row['Factor_Q']) or pd.isna(last_row['Factor_V']):
                    stats['factor_error'] += 1
                    continue
                
                all_stock_data[ts_code] = df_with_factors
                valid_stocks.append(ts_code)
                stats['valid'] += 1
                
            except Exception as e:
                continue
        
        print(f"\n处理统计:")
        print(f"  总计: {stats['total']}")
        print(f"  有效: {stats['valid']}")
        print(f"  读取错误: {stats['read_error']}")
        print(f"  数据太短: {stats['data_too_short']}")
        print(f"  缺少列: {stats['missing_cols']}")
        print(f"  因子错误: {stats['factor_error']}")
        
        if len(valid_stocks) < 50:
            print(f"\n警告: 有效股票仅{len(valid_stocks)}只，尝试降低训练窗口要求")
            # 自动调整训练窗口
            min_length = min(len(df) for df in all_stock_data.values()) if all_stock_data else 0
            if min_length > 30:
                self.train_window = min(60, min_length - 5)  # 降低要求到60天或更少
                print(f"自动调整训练窗口为: {self.train_window} 天")
        
        if len(valid_stocks) < 30:
            print(f"\n错误: 有效股票数量({len(valid_stocks)})不足，无法训练模型")
            return pd.DataFrame()
        
        # 第二步：训练Lasso模型
        print("\n准备训练数据...")
        X_train, y_train = self.prepare_training_data(all_stock_data)
        
        if X_train is None:
            print("\n尝试降低训练窗口重新准备数据...")
            # 进一步降低要求
            self.train_window = 30
            X_train, y_train = self.prepare_training_data(all_stock_data)
        
        # 第三步：训练或使用因子直接选股
        use_lasso = True
        
        if not self.train_model(X_train, y_train):
            print("\nLasso模型训练失败，降级使用因子加权评分")
            use_lasso = False
            # 使用默认权重：动量0.5，质量0.4，波动-0.1（负向）
            default_weights = [0.5, 0.4, -0.1]
        
        print("\n计算股票得分...")
        predictions = []
        
        # 准备所有因子数据进行标准化（如果需要）
        all_factors = []
        all_ts_codes = []
        for ts_code, df in all_stock_data.items():
            last_row = df.iloc[-1]
            all_factors.append([last_row['Factor_M'], last_row['Factor_Q'], last_row['Factor_V']])
            all_ts_codes.append(ts_code)
        
        # 如果没有训练过scaler，现在拟合
        if not hasattr(self.scaler, 'mean_'):
            self.scaler.fit(all_factors)
        
        # 标准化所有因子
        factors_scaled_all = self.scaler.transform(all_factors)
        
        for idx, ts_code in enumerate(all_ts_codes):
            df = all_stock_data[ts_code]
            last_row = df.iloc[-1]
            
            factor_m = last_row['Factor_M']
            factor_q = last_row['Factor_Q']
            factor_v = last_row['Factor_V']
            factors_scaled = factors_scaled_all[idx]
            
            if use_lasso:
                score = self.predict_score([factor_m, factor_q, factor_v])
            else:
                # 使用默认权重计算加权得分
                score = np.dot(factors_scaled, default_weights)
            
            # ATR止损价格
            atr21 = last_row['atr21']
            close = last_row['close']
            stop_loss_price = close - 2 * atr21
            
            predictions.append({
                'ts_code': ts_code,
                'trade_date': last_row['trade_date'],
                'close': close,
                'Factor_M': factor_m,
                'Factor_Q': factor_q,
                'Factor_V': factor_v,
                'predicted_score': score,
                'atr21': atr21,
                'stop_loss_price': stop_loss_price,
                'volume': last_row['volume']
            })
        
        result_df = pd.DataFrame(predictions)
        
        # 按预测得分排序
        result_df = result_df.sort_values('predicted_score', ascending=False).reset_index(drop=True)
        
        # 剔除Factor_V异常高的（过于投机）
        v_threshold = result_df['Factor_V'].quantile(0.95)  # 取95%分位数作为阈值
        result_df = result_df[result_df['Factor_V'] <= v_threshold]
        
        # 选取Top N
        top_stocks = result_df.head(top_n).copy()
        
        print(f"\n选股完成！选出 {len(top_stocks)} 只股票")
        print(f"Factor_V阈值: {v_threshold:.4f} (剔除极端波动股)")
        if not use_lasso:
            print(f"使用默认权重: M=0.5, Q=0.4, V=-0.1")
        
        return top_stocks
    
    def save_results(self, df, filename=None):
        """保存选股结果"""
        if df is None or df.empty:
            print("没有数据可保存")
            return
        
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d')
            filename = f"ai_factor_stocks_{timestamp}.csv"
        
        if not os.path.dirname(filename):
            filename = os.path.join('cy_quant', filename)
        
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        # 调整列顺序
        columns_order = [
            'ts_code', 'trade_date', 'close', 'predicted_score',
            'Factor_M', 'Factor_Q', 'Factor_V',
            'atr21', 'stop_loss_price', 'volume'
        ]
        
        available_cols = [c for c in columns_order if c in df.columns]
        df_to_save = df[available_cols].copy()
        
        df_to_save.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"\n结果已保存至: {filename}")
        print(f"共 {len(df_to_save)} 只股票")


def main(prefixes=None, csv_dir=None, top_n=20, train_window=250, alpha=0.001):
    """
    主函数
    :param prefixes: 文件前缀列表
    :param csv_dir: CSV文件目录
    :param top_n: 选取前N只股票
    :param train_window: 训练窗口（交易日）
    :param alpha: Lasso惩罚系数
    """
    picker = AIFactorStockPicker(
        prefixes=prefixes,
        csv_dir=csv_dir,
        train_window=train_window,
        alpha=alpha
    )
    
    # 执行选股
    result_df = picker.select_stocks(top_n=top_n)
    
    if not result_df.empty:
        # 保存结果
        picker.save_results(result_df)
        
        # 打印结果
        print("\n" + "="*80)
        print(f"Top {len(result_df)} 选股结果:")
        print("="*80)
        display_cols = ['ts_code', 'close', 'predicted_score', 'Factor_M', 'Factor_Q', 'stop_loss_price']
        print(result_df[display_cols].to_string(index=False))
        
        # 打印统计
        print("\n因子统计:")
        print(f"Factor_M (动量): 均值={result_df['Factor_M'].mean():.2e}, 范围=[{result_df['Factor_M'].min():.2e}, {result_df['Factor_M'].max():.2e}]")
        print(f"Factor_Q (质量): 均值={result_df['Factor_Q'].mean():.4f}, 范围=[{result_df['Factor_Q'].min():.4f}, {result_df['Factor_Q'].max():.4f}]")
        print(f"Factor_V (波动): 均值={result_df['Factor_V'].mean():.4f}, 范围=[{result_df['Factor_V'].min():.4f}, {result_df['Factor_V'].max():.4f}]")
        print(f"\nATR止损说明: 当股价跌破 'stop_loss_price' (买入价 - 2*ATR) 时触发止损")
    else:
        print("\n选股失败，请检查数据")
    
    return result_df


if __name__ == '__main__':
    import argparse
    import time
    
    parser = argparse.ArgumentParser(description='AI多因子选股系统 (Lasso模型)')
    parser.add_argument('--top-n', type=int, default=20, help='选取前N只股票，默认20')
    parser.add_argument('--train-window', type=int, default=250, help='训练窗口(交易日)，默认250')
    parser.add_argument('--alpha', type=float, default=0.001, help='Lasso惩罚系数，默认0.001')
    parser.add_argument('--all', action='store_true', help='分析全部股票')
    args = parser.parse_args()
    
    start = time.time()
    
    result_df = main(
        top_n=args.top_n,
        train_window=args.train_window,
        alpha=args.alpha
    )
    
    end = time.time()
    print(f"\n总耗时: {end - start:.2f} 秒")
