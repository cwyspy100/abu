import tushare as ts
import pandas as pd
import numpy as np

import time
import json
import os

# ----------------------
# 这个主要是为了获取股票列表 stock_code_CN.csv
# 步骤1：初始化Tushare（从配置文件读取token）
# ----------------------
# 读取配置文件中的token
config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'todolist', 'config.json')
with open(config_path, 'r', encoding='utf-8') as f:
    config = json.load(f)
    token = config.get('token', '')

ts.set_token(token)  # 从配置文件读取Tushare Token
pro = ts.pro_api()

# ----------------------
# 步骤2：获取A股基础信息（修复字段缺失问题）
# ----------------------
def get_stock_basic_info():
    """
    获取A股基础信息，包含代码、名称、行业、地域、主营业务、公司简介等
    修复字段名：busscope→business，补充公司简介接口
    """
    # 1. 获取基础列表（核心字段）
    stock_basic = pro.stock_basic(
        exchange='',
        list_status='L',  # 仅保留上市股票
        fields='ts_code,symbol,name,industry,area,market,exchange,list_date,business'
    )

    # 2. 补充公司简介（通过pro.stock_company接口）
    stock_company = pro.stock_company(
        fields='ts_code,introduction'
    )

    # 3. 合并基础信息和公司简介
    stock_basic = pd.merge(
        stock_basic,
        stock_company,
        on='ts_code',
        how='left'
    )

    # 4. 字段重命名与映射（对应需求字段）
    stock_basic.rename(
        columns={
            'name': 'co_name',          # 公司名称
            'symbol': 'symbol',         # 股票代码（纯数字）
            'market': 'market_raw',     # 原始市场类型（创业板/科创板等）
            'exchange': 'exchange',     # 交易所（SH/SZ/BJ）
            'business': 'co_business',  # 主营业务（修复busscope→business）
            'area': 'cc',               # 所属地域
            'introduction': 'co_intro', # 公司简介
            'industry': 'industry',     # 所属行业
            'ts_code': 'ts_code'        # Tushare专用代码
        },
        inplace=True
    )

    # 5. 处理market字段：映射为SH/SZ/BJ（与示例格式一致）
    def map_market(ts_code):
        """根据ts_code后缀判断市场（.SZ→SZ，.SH→SH，.BJ→BJ）"""
        if '.' in ts_code:
            return ts_code.split('.')[-1]
        return '-'
    stock_basic['market'] = stock_basic['ts_code'].apply(map_market)

    # 6. 资产类型固定为"股票"
    stock_basic['asset'] = '股票'

    # 7. 处理交易所字段（统一为SZ/SH/BJ，与market一致）
    stock_basic['exchange'] = stock_basic['market']

    return stock_basic

# 获取基础信息
stock_basic_df = get_stock_basic_info()
print(f"获取到{len(stock_basic_df)}只A股基础信息")

# ----------------------
# 步骤3：获取A股行情/财务数据（替换失效的get_today_all接口）
# ----------------------
def get_stock_finance_data(stock_basic_df):
    """
    获取A股财务基础数据（市盈率、市净率、市销率、总市值）
    改用pro.daily_basic接口，兼容新版Pandas，无振幅字段则设为'-'
    """
    # 获取最新交易日（用于daily_basic接口）
    trade_cal = pro.trade_cal(exchange='', start_date='', end_date='')
    latest_trade_date = trade_cal[trade_cal['is_open'] == 1]['cal_date'].iloc[-1]

    # 获取财务基础数据
    daily_basic = pro.daily_basic(
        ts_code='',
        trade_date=latest_trade_date,
        fields='ts_code,pe,pb,ps,total_mv,circ_mv'
    )

    # 处理代码：提取纯数字symbol
    daily_basic['symbol'] = daily_basic['ts_code'].apply(lambda x: x.split('.')[0] if '.' in x else x)

    # 字段重命名
    daily_basic.rename(
        columns={
            'pe': 'pe_s_d',       # 动态市盈率
            'pb': 'pb_d',         # 市净率
            'ps': 'ps_d',         # 市销率
            'total_mv': 'mv',     # 总市值（万元）
        },
        inplace=True
    )

    # 振幅字段：该接口无数据，设为np.nan（后续填充为'-'）
    daily_basic['amplitude'] = np.nan

    # 只保留需要的字段
    quote_fields = ['symbol', 'amplitude', 'pe_s_d', 'mv', 'pb_d', 'ps_d']
    daily_basic = daily_basic[quote_fields]

    return daily_basic

# 获取行情/财务数据
quote_df = get_stock_finance_data(stock_basic_df)

# ----------------------
# 步骤4：获取股东权益数据（equity）
# ----------------------
def get_stock_equity_data(ts_code_list):
    """
    获取股东权益合计（equity），适配新版Pandas（不用append，用列表存储）
    """
    equity_data = []
    # 分批获取（避免接口调用超限，每100个股票延迟1秒）
    for i, ts_code in enumerate(ts_code_list):
        try:
            # 获取最新一期资产负债表
            bal_sheet = pro.balancesheet(
                ts_code=ts_code,
                start_date='',
                end_date='',
                fields='ts_code,end_date,total_hldr_eqy_exc_min_int'
            )
            if not bal_sheet.empty:
                # 取最新一期的股东权益合计（万元）
                equity = bal_sheet.iloc[0]['total_hldr_eqy_exc_min_int']
                equity_data.append({
                    'ts_code': ts_code,
                    'equity': equity
                })
            else:
                equity_data.append({
                    'ts_code': ts_code,
                    'equity': np.nan
                })
        except Exception as e:
            equity_data.append({
                'ts_code': ts_code,
                'equity': np.nan
            })
        # 每100个股票延迟1秒，避免接口限流
        if (i + 1) % 100 == 0:
            time.sleep(1)

    # 转为DataFrame（新版Pandas用列表+pd.DataFrame，不用append）
    equity_df = pd.DataFrame(equity_data)
    # 提取纯数字symbol
    equity_df['symbol'] = equity_df['ts_code'].apply(lambda x: x.split('.')[0] if '.' in x else x)

    return equity_df

# 获取股东权益数据（传入ts_code列表，可限制数量如[:500]，全量则去掉切片）
equity_df = get_stock_equity_data(stock_basic_df['ts_code'].tolist()[:500])  # 测试用前500只，全量去掉[:500]

# ----------------------
# 步骤5：合并所有数据，处理空值，整理格式
# ----------------------
# 1. 合并基础信息与行情数据
final_df = pd.merge(
    stock_basic_df,
    quote_df,
    on='symbol',
    how='left'
)

# 2. 合并股东权益数据
final_df = pd.merge(
    final_df,
    equity_df[['symbol', 'equity']],
    on='symbol',
    how='left'
)

# 3. 处理空值：无数据填'-'，保留原始格式
def fill_nan(x):
    if pd.isna(x) or x == '' or x is None:
        return '-'
    # 处理数值类型（避免科学计数法）
    elif isinstance(x, (int, float)):
        if np.isnan(x):
            return '-'
        # 针对市值、股东权益等大数值，保留两位小数
        else:
            return f"{x:.2f}"
    else:
        # 处理公司简介中的换行符，保留格式
        return str(x).strip().replace('\\n', '\n')

# 遍历字段处理空值
for col in final_df.columns:
    final_df[col] = final_df[col].apply(fill_nan)

# 4. 筛选指定字段（与需求完全一致）
target_fields = [
    'co_name', 'symbol', 'market', 'asset', 'co_business', 'cc',
    'amplitude', 'pe_s_d', 'co_intro', 'exchange', 'mv', 'pb_d',
    'ps_d', 'equity', 'industry'
]
# 确保字段存在（防止个别字段缺失）
target_fields = [f for f in target_fields if f in final_df.columns]
final_df = final_df[target_fields].copy()

# 5. 重置索引（从0开始）
final_df = final_df.reset_index(drop=True)

# ----------------------
# 步骤6：保存并打印结果
# ----------------------
# 打印前5行示例
print("\n整理后的A股数据（指定格式）：")
print(final_df.head())

# 保存为CSV（支持中文和换行符）
final_df.to_csv("stock_code_CN.csv", index=True, encoding="utf-8-sig")
print(f"\n数据已保存为CSV文件，共{len(final_df)}条记录")