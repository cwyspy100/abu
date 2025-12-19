import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
from abupy import ABuSymbolPd
import platform
import matplotlib.font_manager as fm


def calculate_dca_returns(csv_path, investment_amount, frequency='M', price_column='close'):
    """
    计算基于历史数据的定投策略收益

    参数:
    csv_path: 历史数据CSV文件路径
    investment_amount: 每次定投金额
    frequency: 定投频率，'M'为月，'W'为周
    price_column: 使用哪个价格列计算，默认为收盘价

    返回:
    包含策略结果的DataFrame
    """
    # 读取数据
    data = pd.read_csv(csv_path)

    # 确保日期列为datetime类型
    data['date'] = pd.to_datetime(data['date'], format='%Y%m%d')


    # 按日期排序
    data.sort_values('date', inplace=True)

    # 生成完整的投资日期序列
    start_date = data['date'].min()
    end_date = data['date'].max()

    if frequency == 'M':
        # 每月最后一天
        investment_dates = pd.date_range(start=start_date, end=end_date, freq='ME')
    elif frequency == 'W':
        # 每周最后一天（周日）
        investment_dates = pd.date_range(start=start_date, end=end_date, freq='W')
    else:
        raise ValueError("频率参数必须是'M'（月）或'W'（周）")

    # 将投资日期转换为DataFrame
    investment_dates = pd.DataFrame({'investment_date': investment_dates})

    # 使用merge_asof将投资日期与最近的交易日匹配
    # direction='backward'表示寻找当前日期或之前的最近日期
    investment_dates = pd.merge_asof(
        investment_dates,
        data,
        left_on='investment_date',
        right_on='date',
        direction='backward'
    )

    # 移除没有匹配到交易日的投资日期
    investment_dates.dropna(subset=['date'], inplace=True)

    # 计算每次购买的份额
    investment_dates['shares_purchased'] = investment_amount / investment_dates[price_column]
    investment_dates['total_investment'] = investment_amount
    investment_dates['cumulative_investment'] = investment_amount * (np.arange(len(investment_dates)) + 1)

    # 计算累计份额和价值
    investment_dates['cumulative_shares'] = investment_dates['shares_purchased'].cumsum()
    investment_dates['portfolio_value'] = investment_dates['cumulative_shares'] * investment_dates[price_column]

    # 计算收益率
    investment_dates['total_return'] = (investment_dates['portfolio_value'] /
                                        investment_dates['cumulative_investment'] - 1) * 100

    # 计算年化收益率
    # days_invested = (investment_dates.index[-1] - investment_dates.index[0]).days
    # investment_years = days_invested / 365.25

    first_date = investment_dates['investment_date'].iloc[0]
    last_date = investment_dates['investment_date'].iloc[-1]
    days_invested = (last_date - first_date).days
    investment_years = days_invested / 365.25
    investment_dates['annualized_return'] = ((1 + investment_dates['total_return'] / 100) ** (
                1 / investment_years) - 1) * 100

    return investment_dates


def setup_chinese_font():
    """设置中文字体，自动检测系统可用字体"""
    system = platform.system()
    
    # 根据操作系统选择字体
    if system == 'Darwin':  # macOS
        font_candidates = ['PingFang SC', 'STHeiti', 'Arial Unicode MS', 'Heiti TC', 'STSong']
    elif system == 'Windows':
        font_candidates = ['SimHei', 'Microsoft YaHei', 'SimSun', 'KaiTi']
    else:  # Linux
        font_candidates = ['WenQuanYi Micro Hei', 'WenQuanYi Zen Hei', 'Noto Sans CJK SC', 'DejaVu Sans']
    
    # 获取所有可用字体
    available_fonts = [f.name for f in fm.fontManager.ttflist]
    
    # 查找第一个可用的中文字体
    for font in font_candidates:
        if font in available_fonts:
            plt.rcParams['font.sans-serif'] = [font]
            plt.rcParams['axes.unicode_minus'] = False
            return font
    
    # 如果找不到中文字体，尝试使用通用字体
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'DejaVu Sans', 'sans-serif']
    plt.rcParams['axes.unicode_minus'] = False
    print("警告: 未找到中文字体，可能无法正确显示中文")
    return None


def plot_dca_results(results, title="定投策略收益分析"):
    """可视化定投策略结果"""
    # 设置中文字体
    setup_chinese_font()
    plt.figure(figsize=(14, 6))

    # 绘制投资价值和成本对比
    plt.subplot(1, 2, 1)
    plt.plot(results.index, results['portfolio_value'], label='投资组合价值')
    plt.plot(results.index, results['cumulative_investment'], label='累计投入', linestyle='--')
    plt.title('定投价值与成本')
    plt.xlabel('日期')
    plt.ylabel('金额')
    plt.legend()
    plt.grid(True)

    # 绘制收益率
    plt.subplot(1, 2, 2)
    plt.plot(results.index, results['total_return'], label='总回报率(%)')
    plt.plot(results.index, results['annualized_return'], label='年化收益率(%)')
    plt.title('定投收益率')
    plt.xlabel('日期')
    plt.ylabel('收益率 (%)')
    plt.legend()
    plt.grid(True)

    plt.suptitle(title, fontsize=16)
    plt.tight_layout()
    plt.show()


def calculate_smart_dca_returns(csv_path, base_investment=1000, price_column='close'):
    """
    计算基于120日均线的智能定投策略收益

    参数:
    csv_path: 历史数据CSV文件路径
    base_investment: 基准投资金额
    price_column: 使用哪个价格列计算，默认为收盘价

    返回:
    包含策略结果的DataFrame
    """
    # 读取数据
    data = pd.read_csv(csv_path)

    # 确保日期列为datetime类型，指定正确的日期格式
    data['date'] = pd.to_datetime(data['date'], format='%Y%m%d')

    # 按日期排序
    data.sort_values('date', inplace=True)

    # 计算120日均线
    data['ma120'] = data[price_column].rolling(window=120).mean()

    # 移除均线计算产生的NaN值
    data.dropna(subset=['ma120'], inplace=True)

    # 生成每月投资日期序列
    start_date = data['date'].min()
    end_date = data['date'].max()
    investment_dates = pd.date_range(start=start_date, end=end_date, freq='ME')
    investment_dates = pd.DataFrame({'investment_date': investment_dates})

    # 将投资日期与最近的交易日匹配
    investment_dates = pd.merge_asof(
        investment_dates,
        data,
        left_on='investment_date',
        right_on='date',
        direction='backward'
    )

    # 移除没有匹配到交易日的投资日期
    investment_dates.dropna(subset=['date'], inplace=True)

    # 计算价格与均线的比例
    investment_dates['price_ma_ratio'] = investment_dates[price_column] / investment_dates['ma120']

    # 根据价格与均线的比例确定投资金额
    conditions = [
        (investment_dates['price_ma_ratio'] <= 0.9),  # 低于均线10%
        (investment_dates['price_ma_ratio'] <= 1.0),  # 低于均线
        (investment_dates['price_ma_ratio'] <= 1.1),  # 高于均线但不超过10%
        (investment_dates['price_ma_ratio'] > 1.1)  # 高于均线10%
    ]

    # 对应的投资金额（可根据需要调整）
    amounts = [
        base_investment * 2,  # 2000元
        base_investment * 1.5,  # 1500元
        base_investment * 0.8,  # 800元
        base_investment * 0.5  # 500元
    ]

    # 应用条件确定每次投资金额
    investment_dates['investment_amount'] = np.select(conditions, amounts, base_investment)

    # 计算每次购买的份额
    investment_dates['shares_purchased'] = investment_dates['investment_amount'] / investment_dates[price_column]
    investment_dates['cumulative_investment'] = investment_dates['investment_amount'].cumsum()

    # 计算累计份额和价值
    investment_dates['cumulative_shares'] = investment_dates['shares_purchased'].cumsum()

    # 使用最后一个交易日的价格计算最终价值
    last_price = data.iloc[-1][price_column]
    investment_dates['portfolio_value'] = investment_dates['cumulative_shares'] * last_price

    # 计算收益率
    investment_dates['total_return'] = (investment_dates['portfolio_value'] /
                                        investment_dates['cumulative_investment'] - 1) * 100

    # 计算年化收益率
    first_date = investment_dates['investment_date'].iloc[0]
    last_date = investment_dates['investment_date'].iloc[-1]
    days_invested = (last_date - first_date).days
    investment_years = days_invested / 365.25
    investment_dates['annualized_return'] = ((1 + investment_dates['total_return'] / 100) ** (
                1 / investment_years) - 1) * 100

    return investment_dates

def compare_strategies(csv_path, base_investment=1000, price_column='close'):
    """比较固定定投和智能定投策略的收益"""
    # 计算固定定投策略
    fixed_results = calculate_dca_returns(csv_path, base_investment, 'M', price_column)

    # 计算智能定投策略
    smart_results = calculate_smart_dca_returns(csv_path, base_investment, price_column)

    # 打印固定定投结果
    print("=" * 40)
    print("固定金额定投策略结果:")
    final_fixed = fixed_results.iloc[-1]
    print(
        f"投资期间: {fixed_results['investment_date'].iloc[0].date()} 至 {fixed_results['investment_date'].iloc[-1].date()}")
    print(f"总投入: {final_fixed['cumulative_investment']:.2f}元")
    print(f"期末资产价值: {final_fixed['portfolio_value']:.2f}元")
    print(f"总回报率: {final_fixed['total_return']:.2f}%")
    print(f"年化收益率: {final_fixed['annualized_return']:.2f}%")

    # 打印智能定投结果
    print("\n" + "=" * 40)
    print("智能均线定投策略结果:")
    final_smart = smart_results.iloc[-1]
    print(
        f"投资期间: {smart_results['investment_date'].iloc[0].date()} 至 {smart_results['investment_date'].iloc[-1].date()}")
    print(f"总投入: {final_smart['cumulative_investment']:.2f}元")
    print(f"期末资产价值: {final_smart['portfolio_value']:.2f}元")
    print(f"总回报率: {final_smart['total_return']:.2f}%")
    print(f"年化收益率: {final_smart['annualized_return']:.2f}%")

    # 可视化比较
    plt.figure(figsize=(16, 8))
    # 设置中文字体
    setup_chinese_font()

    # 绘制投资价值对比
    plt.subplot(2, 1, 1)
    plt.plot(fixed_results['investment_date'], fixed_results['portfolio_value'], label='固定定投')
    plt.plot(smart_results['investment_date'], smart_results['portfolio_value'], label='智能定投')
    plt.title('不同策略投资价值对比')
    plt.xlabel('日期')
    plt.ylabel('资产价值 (元)')
    plt.legend()
    plt.grid(True)

    # 绘制收益率对比
    plt.subplot(2, 1, 2)
    plt.plot(fixed_results['investment_date'], fixed_results['total_return'], label='固定定投总回报率(%)')
    plt.plot(smart_results['investment_date'], smart_results['total_return'], label='智能定投总回报率(%)')
    plt.title('不同策略收益率对比')
    plt.xlabel('日期')
    plt.ylabel('收益率 (%)')
    plt.legend()
    plt.grid(True)

    plt.tight_layout()
    plt.show()

    return fixed_results, smart_results


def analyze_dca_strategy(csv_path, investment_amount=1000, frequency='M', price_column='close'):
    """分析定投策略并展示结果"""
    # 计算定投结果
    results = calculate_dca_returns(csv_path, investment_amount, frequency, price_column)

    # 打印关键结果
    final = results.iloc[-1]
    first = results.iloc[0]

    # 打印关键结果
    first_date = results['investment_date'].iloc[0].date()
    last_date = results['investment_date'].iloc[-1].date()

    print(f"定投分析 ({first_date} 至 {last_date})")
    print(f"定投频率: {frequency}（{'月' if frequency == 'M' else '周'}）")
    print(f"每次投入: {investment_amount}元")
    print(f"投资期数: {len(results)}期")
    print(f"总投入: {final['cumulative_investment']:.2f}元")
    print(f"期末资产价值: {final['portfolio_value']:.2f}元")
    print(f"总回报率: {final['total_return']:.2f}%")
    print(f"年化收益率: {final['annualized_return']:.2f}%")

    # 可视化结果
    plot_dca_results(results)

    return results


# 示例使用
if __name__ == "__main__":
    """
    策略测试的结果总结
    1、定投适合长期上涨的，比如TQQQ，比如FUTU
    2、有波动的适合增强的比如 TQQQ，  不增强13%， 增强25% ， 60日均线 1.7463%
    3、没有波动适合不增强的。比如腾讯 不增强的收益26.61%，增强只有7% ，60日均线只有 5%
    4、FUTU是个特例，增强比不增强差3% ， 60日均线 5.9%
    为什么会这样，60日均线还有很多因素。
    
    """
    # kl_pd = ABuSymbolPd.make_kl_df('usTSLA', n_folds=2)
    csv_file = "~/abu/data/csv/usTQQQ_20220606_20250628"

    # 分析月定投策略，每月投入1000元
    # analyze_dca_strategy(csv_file, investment_amount=1000, frequency='M')

    # fixed_results, smart_results = compare_strategies(
    #     csv_path=csv_file,
    #     base_investment=1000,
    #     price_column='close'
    # )

    # 如果你想分析周定投策略，可以取消下面这行的注释
    analyze_dca_strategy(csv_file, investment_amount=250, frequency='W')