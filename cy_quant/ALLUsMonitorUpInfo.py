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


class ALLUsMonitorUpInfo:
    def __init__(self):
        self.benchmark = AbuBenchmark()
        self.capital = AbuCapital(1000000, self.benchmark)
        self.kl_pd_manager = AbuKLManager(self.benchmark, self.capital)

    def update_all_us_data(self):
        """
        更新所有美股数据到本地
        """
        abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_tx
        abupy.env.g_data_cache_type = EDataCacheType.E_DATA_CACHE_CSV
        abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_US
        abu.run_kl_update(n_folds=1, market=EMarketTargetType.E_MARKET_TARGET_US, n_jobs=2)

    def _setup_environment(self):
        """
        设置分析环境
        """
        abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_tx
        abupy.env.disable_example_env_ipython()
        abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_FORCE_LOCAL
        abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_US

    def _get_stock_info(self, symbol):
        """
        获取股票基本信息
        """
        try:
            return {'co_name': symbol}
        except:
            return {'co_name': symbol}

    def _find_cross_above_ma120(self, kl_pd):
        """
        找到价格最后一次超过120日均线的位置
        """
        if len(kl_pd) < 120:
            return None

        last_cross = None
        for i in range(120, len(kl_pd)):
            if kl_pd['close'].iloc[i] > kl_pd['MA120'].iloc[i] and kl_pd['close'].iloc[i-1] <= kl_pd['MA120'].iloc[i-1]:
                last_cross = kl_pd.index[i]

        return last_cross

    def _calculate_up_info(self, kl_pd, cross_date):
        """
        计算从突破开始到现在的涨幅天数和幅度，以及上涨下跌天数统计
        """
        cross_idx = kl_pd.index.get_loc(cross_date)
        cross_price = kl_pd['close'].iloc[cross_idx]
        current_price = kl_pd['close'].iloc[-1]

        up_days = len(kl_pd) - cross_idx - 1
        up_ratio = ((current_price - cross_price) / cross_price) * 100

        up_count = 0
        down_count = 0

        for i in range(cross_idx + 1, len(kl_pd)):
            if i > 0:
                if kl_pd['close'].iloc[i] > kl_pd['close'].iloc[i-1]:
                    up_count += 1
                elif kl_pd['close'].iloc[i] < kl_pd['close'].iloc[i-1]:
                    down_count += 1

        up_down_ratio = up_count / down_count if down_count > 0 else float('inf')

        return up_days, up_ratio, up_count, down_count, up_down_ratio

    def cal_us_up_days(self, radio, price):
        """
        统计所有美股数据中120日均线的角度是大于0的
        """
        self._setup_environment()

        all_symbols = ABuMarket.all_symbol()
        print(f"总共获取到 {len(all_symbols)} 只美股")

        results = []

        for i, symbol in enumerate(all_symbols):
            try:
                print(f"正在处理第 {i+1}/{len(all_symbols)} 只美股: {symbol}")

                kl_pd = self.kl_pd_manager.get_pick_stock_kl_pd(symbol)
                if kl_pd is None or len(kl_pd) < 120:
                    print(f"美股 {symbol} 数据不足，跳过")
                    continue

                kl_pd['MA120'] = kl_pd['close'].rolling(window=120).mean()

                if len(kl_pd) >= 30:
                    recent_ma120 = kl_pd['MA120'].dropna().tail(30)
                    if len(recent_ma120) >= 10:
                        ma120_angle = ABuRegUtil.calc_regress_deg(recent_ma120, show=False)
                    else:
                        ma120_angle = 0
                else:
                    ma120_angle = 0

                if ma120_angle > radio:
                    cross_above_ma120 = self._find_cross_above_ma120(kl_pd)

                    if cross_above_ma120 is not None:
                        up_days, up_ratio, up_count, down_count, up_down_ratio = self._calculate_up_info(kl_pd, cross_above_ma120)

                        stock_info = self._get_stock_info(symbol)

                        if kl_pd['close'].iloc[-1] < price:
                            continue

                        result = {
                            'symbol': symbol,
                            'co_name': stock_info.get('co_name', ''),
                            'market_type': '美股',
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
                        print(f"美股 {symbol} 符合条件: 角度={ma120_angle:.3f}, 最后突破天数={up_days}, 涨幅={up_ratio:.2f}%, 上涨天数={up_count}, 下跌天数={down_count}, 比率={up_down_ratio:.2f}")

            except Exception as e:
                print(f"处理美股 {symbol} 时出错: {str(e)}")
                continue

        self._save_results(results)
        self._print_statistics(results)

        return results

    def _save_results(self, results):
        """
        保存结果到文件
        """
        todolist_dir = "todolist"
        if not os.path.exists(todolist_dir):
            os.makedirs(todolist_dir)
            print(f"创建目录: {todolist_dir}")

        today = datetime.date.today().strftime("%Y%m%d")

        if results:
            us_file = os.path.join(todolist_dir, f"cal_up_days_美股_{today}.csv")
            df_us = pd.DataFrame(results)
            df_us.to_csv(us_file, index=False, encoding='utf-8-sig')
            print(f"美股结果已保存到: {us_file}")
        else:
            print("没有找到符合条件的美股")

    def _print_statistics(self, results):
        """
        打印统计信息
        """
        if not results:
            print("没有找到符合条件的美股")
            return

        print(f"\n=== 美股统计结果 ===")
        print(f"符合条件的美股数量: {len(results)}")

        results_sorted = sorted(results, key=lambda x: x['up_ratio'], reverse=True)

        print(f"\n涨幅前10名:")
        for i, result in enumerate(results_sorted[:10]):
            print(f"{i+1}. {result['symbol']} {result['co_name']} - 涨幅: {result['up_ratio']}%, 最后突破天数: {result['up_days']}, 上涨天数: {result['up_count']}, 下跌天数: {result['down_count']}, 比率: {result['up_down_ratio']}")


if __name__ == '__main__':
    start_time = time.time()

    monitor = ALLUsMonitorUpInfo()

    # 测试单个美股
    test_symbol = 'AAPL'  # 可以修改为任意美股代码
    # print(f"测试美股: {test_symbol}")
    # result = monitor.test_single_stock(test_symbol)

    # 1、更新所有数据（可选，如果本地已有数据可以注释掉）
    # monitor.update_all_us_data()

    # 2、使用本地数据进行统计
    results = monitor.cal_us_up_days(5,5)

    print(f"\n总耗时: {time.time() - start_time:.2f} 秒")