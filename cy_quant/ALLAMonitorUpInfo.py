# noinspection PyUnresolvedReferences
import abu_local_env

import abupy
from abupy import ABuMarket
from abupy import AbuBenchmark
from abupy import AbuCapital
from abupy import AbuKLManager
from abupy import EMarketSourceType, EDataCacheType, EMarketTargetType, EMarketDataFetchMode
from abupy import ABuRegUtil
from abupy import abu
import pandas as pd
import numpy as np
import time
import datetime
import os


class ALLAMonitorUpInfo:
    def __init__(self):
        self.benchmark = AbuBenchmark()
        self.capital = AbuCapital(1000000, self.benchmark)
        self.kl_pd_manager = AbuKLManager(self.benchmark, self.capital)

    def update_all_a_data(self):
        """
        更新所有A股数据到本地
        """
        abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_tx
        abupy.env.g_data_cache_type = EDataCacheType.E_DATA_CACHE_CSV
        abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_CN
        abu.run_kl_update(n_folds=1, market=EMarketTargetType.E_MARKET_TARGET_CN, n_jobs=2)

    def test_single_stock(self, symbol, save_to_csv=True):
        """
        测试单个股票，获取详细数据并保存到CSV

        Args:
            symbol (str): 股票代码，如 '000001'
            save_to_csv (bool): 是否保存到CSV文件，默认True

        Returns:
            dict: 包含股票详细分析数据的字典
        """
        print(f"开始分析股票: {symbol}")

        # 设置环境
        self._setup_environment()

        try:
            # 获取股票数据
            kl_pd = self.kl_pd_manager.get_pick_stock_kl_pd(symbol)
            if kl_pd is None or len(kl_pd) < 120:
                print(f"股票 {symbol} 数据不足，需要至少120个交易日数据")
                return None

            print(f"获取到 {len(kl_pd)} 个交易日数据")

            # 计算技术指标
            analysis_data = self._calculate_technical_indicators(kl_pd, symbol)

            # 分析突破情况
            cross_analysis = self._analyze_cross_above_ma120(kl_pd)

            # 计算上涨下跌统计
            if cross_analysis['has_crossed_ma120']:
                _, _, up_count, down_count, up_down_ratio = self._calculate_up_info(kl_pd, cross_analysis['cross_date'])
                cross_analysis['up_count'] = up_count
                cross_analysis['down_count'] = down_count
                cross_analysis['up_down_ratio'] = round(up_down_ratio, 2) if up_down_ratio != float('inf') else 'inf'
            else:
                cross_analysis['up_count'] = 0
                cross_analysis['down_count'] = 0
                cross_analysis['up_down_ratio'] = 0

            # 合并分析结果
            result = {**analysis_data, **cross_analysis}

            # 保存到CSV
            if save_to_csv:
                self._save_single_stock_to_csv(symbol, kl_pd, result)

            # 打印分析结果
            self._print_single_stock_analysis(symbol, result)

            return result

        except Exception as e:
            print(f"分析股票 {symbol} 时出错: {str(e)}")
            return None

    def _setup_environment(self):
        """
        设置分析环境
        """
        abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_tx
        abupy.env.disable_example_env_ipython()
        abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_FORCE_LOCAL
        abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_CN

    def _calculate_technical_indicators(self, kl_pd, symbol):
        """
        计算技术指标

        Args:
            kl_pd: 股票K线数据
            symbol: 股票代码

        Returns:
            dict: 技术指标数据
        """
        # 计算各种均线
        kl_pd['MA5'] = kl_pd['close'].rolling(window=5).mean()
        kl_pd['MA10'] = kl_pd['close'].rolling(window=10).mean()
        kl_pd['MA20'] = kl_pd['close'].rolling(window=20).mean()
        kl_pd['MA60'] = kl_pd['close'].rolling(window=60).mean()
        kl_pd['MA120'] = kl_pd['close'].rolling(window=120).mean()

        # 计算120日均线角度
        ma120_angle = 0
        if len(kl_pd) >= 30:
            recent_ma120 = kl_pd['MA120'].dropna().tail(30)
            if len(recent_ma120) >= 10:
                ma120_angle = ABuRegUtil.calc_regress_deg(recent_ma120, show=False)

        # 计算其他技术指标
        kl_pd['VOL_MA5'] = kl_pd['volume'].rolling(window=5).mean()
        kl_pd['VOL_MA10'] = kl_pd['volume'].rolling(window=10).mean()

        # 计算价格相对均线的位置
        current_price = kl_pd['close'].iloc[-1]
        kl_pd['PRICE_MA5_RATIO'] = (kl_pd['close'] / kl_pd['MA5'] - 1) * 100
        kl_pd['PRICE_MA10_RATIO'] = (kl_pd['close'] / kl_pd['MA10'] - 1) * 100
        kl_pd['PRICE_MA20_RATIO'] = (kl_pd['close'] / kl_pd['MA20'] - 1) * 100
        kl_pd['PRICE_MA60_RATIO'] = (kl_pd['close'] / kl_pd['MA60'] - 1) * 100
        kl_pd['PRICE_MA120_RATIO'] = (kl_pd['close'] / kl_pd['MA120'] - 1) * 100

        # 获取股票基本信息
        stock_info = self._get_stock_info(symbol)

        return {
            'symbol': symbol,
            'co_name': stock_info.get('co_name', ''),
            'ma120_angle': round(ma120_angle, 3),
            'current_price': current_price,
            'ma5_price': kl_pd['MA5'].iloc[-1],
            'ma10_price': kl_pd['MA10'].iloc[-1],
            'ma20_price': kl_pd['MA20'].iloc[-1],
            'ma60_price': kl_pd['MA60'].iloc[-1],
            'ma120_price': kl_pd['MA120'].iloc[-1],
            'current_volume': kl_pd['volume'].iloc[-1],
            'vol_ma5': kl_pd['VOL_MA5'].iloc[-1],
            'vol_ma10': kl_pd['VOL_MA10'].iloc[-1],
            'price_ma5_ratio': round(kl_pd['PRICE_MA5_RATIO'].iloc[-1], 2),
            'price_ma10_ratio': round(kl_pd['PRICE_MA10_RATIO'].iloc[-1], 2),
            'price_ma20_ratio': round(kl_pd['PRICE_MA20_RATIO'].iloc[-1], 2),
            'price_ma60_ratio': round(kl_pd['PRICE_MA60_RATIO'].iloc[-1], 2),
            'price_ma120_ratio': round(kl_pd['PRICE_MA120_RATIO'].iloc[-1], 2),
            'total_days': len(kl_pd),
            'analysis_date': datetime.date.today().strftime("%Y-%m-%d")
        }

    def _analyze_cross_above_ma120(self, kl_pd):
        """
        分析突破120日均线的情况

        Args:
            kl_pd: 股票K线数据

        Returns:
            dict: 突破分析数据
        """
        cross_date = self._find_cross_above_ma120(kl_pd)

        if cross_date is not None:
            up_days, up_ratio = self._calculate_up_info(kl_pd, cross_date)

            # 计算突破后的详细数据
            cross_idx = kl_pd.index.get_loc(cross_date)
            cross_price = kl_pd['close'].iloc[cross_idx]

            # 计算突破后的最高价和最低价
            after_cross_data = kl_pd.iloc[cross_idx+1:]
            if len(after_cross_data) > 0:
                max_price = after_cross_data['close'].max()
                min_price = after_cross_data['close'].min()
                max_ratio = ((max_price - cross_price) / cross_price) * 100
                min_ratio = ((min_price - cross_price) / cross_price) * 100
            else:
                max_price = min_price = cross_price
                max_ratio = min_ratio = 0

            return {
                'cross_date': cross_date.strftime("%Y-%m-%d"),
                'cross_price': cross_price,
                'up_days': up_days,
                'up_ratio': round(up_ratio, 2),
                'max_price_after_cross': max_price,
                'min_price_after_cross': min_price,
                'max_ratio_after_cross': round(max_ratio, 2),
                'min_ratio_after_cross': round(min_ratio, 2),
                'has_crossed_ma120': True
            }
        else:
            return {
                'cross_date': None,
                'cross_price': None,
                'up_days': 0,
                'up_ratio': 0,
                'max_price_after_cross': None,
                'min_price_after_cross': None,
                'max_ratio_after_cross': 0,
                'min_ratio_after_cross': 0,
                'has_crossed_ma120': False
            }

    def _save_single_stock_to_csv(self, symbol, kl_pd, analysis_result):
        """
        保存单个股票分析结果到CSV

        Args:
            symbol: 股票代码
            kl_pd: 股票K线数据
            analysis_result: 分析结果
        """
        # 创建输出目录
        output_dir = "stock_analysis"
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        today = datetime.date.today().strftime("%Y%m%d")

        # 保存分析结果摘要
        summary_file = os.path.join(output_dir, f"{symbol}_summary_{today}.csv")
        summary_data = []
        for key, value in analysis_result.items():
            summary_data.append({'指标': key, '数值': value})

        summary_df = pd.DataFrame(summary_data)
        summary_df.to_csv(summary_file, index=False, encoding='utf-8-sig')

        # 保存K线数据和技术指标
        kl_data_file = os.path.join(output_dir, f"{symbol}_kl_data_{today}.csv")
        kl_pd.to_csv(kl_data_file, index=True, encoding='utf-8-sig')

        # 保存最近30个交易日的数据
        recent_file = os.path.join(output_dir, f"{symbol}_recent30_{today}.csv")
        recent_data = kl_pd.tail(30)[['close', 'volume', 'MA5', 'MA10', 'MA20', 'MA60', 'MA120',
                                     'PRICE_MA5_RATIO', 'PRICE_MA10_RATIO', 'PRICE_MA20_RATIO',
                                     'PRICE_MA60_RATIO', 'PRICE_MA120_RATIO']]
        recent_data.to_csv(recent_file, index=True, encoding='utf-8-sig')

        print(f"分析结果已保存到: {output_dir}/")
        print(f"  - 分析摘要: {summary_file}")
        print(f"  - K线数据: {kl_data_file}")
        print(f"  - 最近30日: {recent_file}")

    def _print_single_stock_analysis(self, symbol, result):
        """
        打印单个股票分析结果

        Args:
            symbol: 股票代码
            result: 分析结果
        """
        print(f"\n=== {symbol} 分析结果 ===")
        print(f"股票名称: {result['co_name']}")
        print(f"当前价格: {result['current_price']:.2f}")
        print(f"120日均线角度: {result['ma120_angle']}")
        print(f"120日均线价格: {result['ma120_price']:.2f}")
        print(f"相对120日均线: {result['price_ma120_ratio']}%")

        if result['has_crossed_ma120']:
            print(f"最后突破日期: {result['cross_date']}")
            print(f"最后突破价格: {result['cross_price']:.2f}")
            print(f"最后突破后天数: {result['up_days']}")
            print(f"累计涨幅: {result['up_ratio']}%")
            print(f"上涨天数: {result['up_count']}, 下跌天数: {result['down_count']}, 比率: {result['up_down_ratio']}")
            print(f"突破后最高价: {result['max_price_after_cross']:.2f} ({result['max_ratio_after_cross']}%)")
            print(f"突破后最低价: {result['min_price_after_cross']:.2f} ({result['min_ratio_after_cross']}%)")
        else:
            print("尚未突破120日均线")

        print(f"成交量: {result['current_volume']:.0f}")
        print(f"5日均量: {result['vol_ma5']:.0f}")
        print(f"10日均量: {result['vol_ma10']:.0f}")

    def cal_a_up_days(self, radio, price):
        """
        统计所有股票数据中120日均线的角度是大于0的，
        统计从价格超过120日均线开始的，涨幅天数和涨的幅度
        """
        # 设置环境 - 使用本地数据，不通过网络更新
        self._setup_environment()

        # 获取所有股票代码
        all_symbols = ABuMarket.all_symbol()
        print(f"总共获取到 {len(all_symbols)} 只股票")

        # 存储结果
        results = []

        for i, symbol in enumerate(all_symbols):
            try:
                print(f"正在处理第 {i+1}/{len(all_symbols)} 只股票: {symbol}")

                # 获取股票数据
                kl_pd = self.kl_pd_manager.get_pick_stock_kl_pd(symbol)
                if kl_pd is None or len(kl_pd) < 120:
                    print(f"股票 {symbol} 数据不足，跳过")
                    continue

                # 计算120日均线
                kl_pd['MA120'] = kl_pd['close'].rolling(window=120).mean()

                # 计算120日均线角度（使用最近30个交易日的数据）
                if len(kl_pd) >= 30:
                    recent_ma120 = kl_pd['MA120'].dropna().tail(30)
                    if len(recent_ma120) >= 10:  # 至少需要10个数据点计算角度
                        ma120_angle = ABuRegUtil.calc_regress_deg(recent_ma120, show=False)
                    else:
                        ma120_angle = 0
                else:
                    ma120_angle = 0

                # 只处理120日均线角度大于0的股票
                if ma120_angle > radio:
                    # 找到价格最后一次超过120日均线的位置
                    cross_above_ma120 = self._find_cross_above_ma120(kl_pd)

                    if cross_above_ma120 is not None:
                        # 计算从最后一次突破开始到现在的涨幅天数和幅度
                        up_days, up_ratio, up_count, down_count, up_down_ratio = self._calculate_up_info(kl_pd, cross_above_ma120)

                        # 获取股票基本信息
                        stock_info = self._get_stock_info(symbol)

                        if kl_pd['close'].iloc[-1] < price:
                            continue

                        result = {
                            'symbol': symbol,
                            'co_name': stock_info.get('co_name', ''),
                            'ma120_angle': round(ma120_angle, 3),
                            'cross_date': cross_above_ma120,
                            'up_days': up_days,
                            'up_ratio': round(up_ratio, 2),
                            'up_count': up_count,
                            'down_count': down_count,
                            'up_down_ratio': round(up_down_ratio, 2) if up_down_ratio != float('inf') else 'inf',
                            'current_price': kl_pd['close'].iloc[-1],
                            'ma120_price': kl_pd['MA120'].iloc[-1]
                        }
                        results.append(result)
                        print(f"股票 {symbol} 符合条件: 角度={ma120_angle:.3f}, 最后突破天数={up_days}, 涨幅={up_ratio:.2f}%, 上涨天数={up_count}, 下跌天数={down_count}, 比率={up_down_ratio:.2f}")

            except Exception as e:
                print(f"处理股票 {symbol} 时出错: {str(e)}")
                continue

        # 保存结果到文件
        self._save_results(results)

        # 打印统计信息
        self._print_statistics(results)

        return results

    def _find_cross_above_ma120(self, kl_pd):
        """
        找到价格最后一次超过120日均线的位置
        """
        # 确保有足够的数据
        if len(kl_pd) < 120:
            return None

        # 找到价格最后一次超过120日均线的位置
        last_cross = None
        for i in range(120, len(kl_pd)):
            if kl_pd['close'].iloc[i] > kl_pd['MA120'].iloc[i] and kl_pd['close'].iloc[i-1] <= kl_pd['MA120'].iloc[i-1]:
                last_cross = kl_pd.index[i]

        return last_cross

    def _calculate_up_info(self, kl_pd, cross_date):
        """
        计算从突破开始到现在的涨幅天数和幅度，以及上涨下跌天数统计
        """
        # 找到突破日期在数据中的位置
        cross_idx = kl_pd.index.get_loc(cross_date)
        cross_price = kl_pd['close'].iloc[cross_idx]
        current_price = kl_pd['close'].iloc[-1]

        # 计算涨幅天数
        up_days = len(kl_pd) - cross_idx - 1

        # 计算涨幅幅度
        up_ratio = ((current_price - cross_price) / cross_price) * 100

        # 统计上涨下跌天数
        up_count = 0
        down_count = 0

        # 从突破后一天开始统计
        for i in range(cross_idx + 1, len(kl_pd)):
            if i > 0:  # 确保有前一天的数据
                if kl_pd['close'].iloc[i] > kl_pd['close'].iloc[i-1]:
                    up_count += 1
                elif kl_pd['close'].iloc[i] < kl_pd['close'].iloc[i-1]:
                    down_count += 1
                # 如果价格相等，不计入任何一方

        # 计算上涨下跌比率
        up_down_ratio = up_count / down_count if down_count > 0 else float('inf')

        return up_days, up_ratio, up_count, down_count, up_down_ratio

    def _get_stock_info(self, symbol):
        """
        获取股票基本信息
        """
        try:
            # 这里可以添加获取股票基本信息的逻辑
            # 比如从股票代码中提取公司名称等
            return {'co_name': symbol}
        except:
            return {'co_name': symbol}

    def _save_results(self, results):
        """
        保存结果到文件，按市场分类保存
        """
        # 创建todolist目录（如果不存在）
        todolist_dir = "todolist"
        if not os.path.exists(todolist_dir):
            os.makedirs(todolist_dir)
            print(f"创建目录: {todolist_dir}")

        today = datetime.date.today().strftime("%Y%m%d")

        if results:
            # 保存总体结果
            all_file = os.path.join(todolist_dir, f"cal_up_days_all_{today}.csv")
            df_all = pd.DataFrame(results)
            df_all.to_csv(all_file, index=False, encoding='utf-8-sig')
            print(f"总体结果已保存到: {all_file}")
        else:
            print("没有找到符合条件的股票")

    def _print_statistics(self, results):
        """
        打印统计信息
        """
        if not results:
            print("没有找到符合条件的股票")
            return

        print(f"\n=== 统计结果 ===")
        print(f"符合条件的股票数量: {len(results)}")

        # 按涨幅排序
        results_sorted = sorted(results, key=lambda x: x['up_ratio'], reverse=True)

        print(f"\n涨幅前10名:")
        for i, result in enumerate(results_sorted[:10]):
            print(f"{i+1}. {result['symbol']} {result['co_name']} - 涨幅: {result['up_ratio']}%, 最后突破天数: {result['up_days']}, 上涨天数: {result['up_count']}, 下跌天数: {result['down_count']}, 比率: {result['up_down_ratio']}")

        # 按角度排序
        results_angle_sorted = sorted(results, key=lambda x: x['ma120_angle'], reverse=True)

        print(f"\n角度前10名:")
        for i, result in enumerate(results_angle_sorted[:10]):
            print(f"{i+1}. {result['symbol']} {result['co_name']} - 角度: {result['ma120_angle']}, 涨幅: {result['up_ratio']}%, 上涨下跌比率: {result['up_down_ratio']}")

        # 按上涨下跌比率排序
        results_ratio_sorted = sorted(results, key=lambda x: x['up_down_ratio'] if x['up_down_ratio'] != 'inf' else 0, reverse=True)

        print(f"\n上涨下跌比率前10名:")
        for i, result in enumerate(results_ratio_sorted[:10]):
            print(f"{i+1}. {result['symbol']} {result['co_name']} - 比率: {result['up_down_ratio']}, 上涨天数: {result['up_count']}, 下跌天数: {result['down_count']}, 涨幅: {result['up_ratio']}%")


if __name__ == '__main__':
    start_time = time.time()

    monitor = ALLAMonitorUpInfo()

    # 测试单个股票
    test_symbol = 'sz002779'  # 可以修改为任意股票代码
    # print(f"测试股票: {test_symbol}")
    result = monitor.test_single_stock(test_symbol)

    # 如果需要测试多只股票
    # test_symbols = ['000001', '000002', '600000']
    # for symbol in test_symbols:
    #     monitor.test_single_stock(symbol)

    # 1、更新所有数据（可选，如果本地已有数据可以注释掉）
    # monitor.update_all_a_data()

    # 2、使用本地数据进行统计（可选）
    # results = monitor.cal_a_up_days(5, 5)

    # 1、更新所有数据（可选，如果本地已有数据可以注释掉）
    # monitor.update_all_a_data()

    # 2、使用本地数据进行统计（可选）
    # results = monitor.cal_a_up_days()

    print(f"\n总耗时: {time.time() - start_time:.2f} 秒")