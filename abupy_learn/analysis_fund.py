


import efinance as ef
import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt



def get_data():
    pd.read_csv('5213050.csv')



if __name__ == '__main__':
    '''
    1、获取数据，并转为为csv文件
    
    '''
    # etf_code = '513050'
    # my_etf_data = ef.stock.get_quote_history(etf_code)
    #
    # my_etf_data = my_etf_data.sort_values('日期')
    # my_etf_data['MA_5'] = my_etf_data['收盘'].rolling(window=5).mean()
    #
    # selected_col = ['日期', '收盘', '最高', '最低', '涨跌额', '开盘', '成交量']
    # my_new_data = my_etf_data[selected_col].copy()
    #
    # new_columns = {'收盘': 'close', '最高': 'high', '最低': 'low', '涨跌额': 'p_change', '开盘': 'open', '成交量': 'volume'}
    #
    # my_new_data = my_new_data.rename(columns=new_columns)
    #
    # my_new_data = my_new_data.set_index('日期')
    #
    # my_new_data = my_new_data.rename_axis('', axis='index')
    # my_new_data.insert(5, 'pre_close', pd.Series(my_new_data['close']).shift(1))
    #
    # my_new_data['MA_5'] = my_new_data['close'].rolling(window=5).mean()
    #
    # my_new_data['MA_60'] = my_new_data['close'].rolling(window=60).mean()
    #
    # my_new_data['MA_90'] = my_new_data['close'].rolling(window=90).mean()
    #
    # print(type(my_new_data))
    #
    # my_new_data = my_new_data.fillna(0)
    #
    # my_new_data.to_csv('5213050.csv', index=True)
    #
    # my_new_data

    '''
    2、读取csv文件，做固定分析。
    '''
    my_new_data = pd.read_csv('5213050.csv', index_col=0)

    my_new_data['distance'] = my_new_data['low'] - my_new_data['MA_90']
    print(my_new_data.tail())
    print(my_new_data['distance'].min())
    print(my_new_data['low'].mean())
    print(abs(my_new_data['distance'].min()) / my_new_data['low'].mean())

    print(my_new_data.loc[my_new_data['distance'].idxmin()])

    my_new_data[['low', 'distance']].plot(subplots=True, grid=True,
                                   figsize=(14, 7))
    plt.show()

    # 30 -90买入





    # # 头一年（[:252]）作为训练数据, 美股交易中一年的交易日有252天
    # train_kl = my_new_data[:833]
    # # 后一年（[252:]）作为回测数据
    # test_kl = my_new_data[835:]
    #
    # # 分别画出两部分数据收盘价格曲线
    # tmp_df = pd.DataFrame(
    #     np.array([train_kl.close.values, test_kl.close.values]).T,
    #     columns=['train', 'test'])
    #
    # tmp_df[['train', 'test']].plot(subplots=True, grid=True,
    #                                figsize=(14, 7))
    #
    # plt.show()
    #
    # # 训练数据的收盘价格均值
    # close_mean = train_kl.close.mean()
    # # 训练数据的收盘价格标准差
    # close_std = train_kl.close.std()
    #
    # # 构造卖出信号阀值
    # sell_signal = close_mean + close_std / 3
    # # 构造买入信号阀值
    # buy_signal = close_mean - close_std / 3
    #
    # # 可视化训练数据的卖出信号阀值，买入信号阀值及均值线
    # plt.figure(figsize=(14, 7))
    # # 训练集收盘价格可视化
    # train_kl.close.plot()
    # # 水平线，买入信号线, lw代表线的粗度
    # plt.axhline(buy_signal, color='r', lw=3)
    # # 水平线，均值线
    # plt.axhline(close_mean, color='black', lw=1)
    # # 水平线， 卖出信号线
    # plt.axhline(sell_signal, color='g', lw=3)
    # plt.legend(['train close', 'buy_signal', 'close_mean', 'sell_signal'],
    #            loc='best')
    # # plt.show()
    #
    # # 将卖出信号阀值，买入信号阀值代入回归测试数据可视化
    # plt.figure(figsize=(14, 7))
    # # 测试集收盘价格可视化
    # test_kl.close.plot()
    # # buy_signal直接代入买入信号
    # plt.axhline(buy_signal, color='r', lw=3)
    # # 直接代入训练集均值close
    # plt.axhline(close_mean, color='black', lw=1)
    # # sell_signal直接代入卖出信号
    # plt.axhline(sell_signal, color='g', lw=3)
    # # 按照上述绘制顺序标注
    # plt.legend(['test close', 'buy_signal', 'close_mean', 'sell_signal'],
    #            loc='best')
    # # plt.show()
    #
    # print('买入信号阀值:{} 卖出信号阀值:{}'.format(buy_signal, sell_signal))
    #
    # # 寻找测试数据中满足买入条件的时间序列
    # buy_index = test_kl[test_kl['close'] <= buy_signal].index
    #
    # # 将找到的买入时间系列的信号设置为1，代表买入操作
    # test_kl.loc[buy_index, 'signal'] = 1
    # # 表7-2所示
    # # 寻找测试数据中满足卖出条件的时间序列
    # sell_index = test_kl[test_kl['close'] >= sell_signal].index
    #
    # # 将找到的卖出时间系列的信号设置为0，代表卖出操作
    # test_kl.loc[sell_index, 'signal'] = 0
    #
    # # 由于假设都是全仓操作所以signal＝keep，即1代表买入持有，0代表卖出空仓
    # test_kl['keep'] = test_kl['signal']
    # # 将keep列中的nan使用向下填充的方式填充，结果使keep可以代表最终的交易持股状态
    # test_kl['keep'].fillna(method='ffill', inplace=True)
    #
    # # shift(1)及np.log下面会有内容详细讲解
    # test_kl['benchmark_profit'] = \
    #     np.log(test_kl['close'] / test_kl['close'].shift(1))
    #
    # # 仅仅为了说明np.log的意义，添加了benchmark_profit2，只为对比数据是否一致
    # test_kl['benchmark_profit2'] = \
    #     test_kl['close'] / test_kl['close'].shift(1) - 1
    #
    # # 可视化对比两种方式计算出的profit是一致的
    # test_kl[['benchmark_profit', 'benchmark_profit2']].plot(subplots=True,
    #                                                         grid=True,
    #                                                         figsize=(
    #                                                             14, 7))
    #
    # plt.show()




