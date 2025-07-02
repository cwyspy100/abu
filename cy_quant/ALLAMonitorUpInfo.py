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
        
    def cal_a_up_days(self):
        """
        统计所有股票数据中120日均线的角度是大于0的，
        统计从价格超过120日均线开始的，涨幅天数和涨的幅度
        """
        # 设置环境 - 使用本地数据，不通过网络更新
        abupy.env.g_market_source = EMarketSourceType.E_MARKET_SOURCE_tx
        abupy.env.disable_example_env_ipython()
        abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_FORCE_LOCAL
        abupy.env.g_market_target = EMarketTargetType.E_MARKET_TARGET_CN

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
                if ma120_angle > 0:
                    # 找到价格首次超过120日均线的位置
                    cross_above_ma120 = self._find_cross_above_ma120(kl_pd)

                    if cross_above_ma120 is not None:
                        # 计算从突破开始到现在的涨幅天数和幅度
                        up_days, up_ratio = self._calculate_up_info(kl_pd, cross_above_ma120)

                        # 获取股票基本信息
                        stock_info = self._get_stock_info(symbol)

                        result = {
                            'symbol': symbol,
                            'co_name': stock_info.get('co_name', ''),
                            'ma120_angle': round(ma120_angle, 3),
                            'cross_date': cross_above_ma120,
                            'up_days': up_days,
                            'up_ratio': round(up_ratio, 2),
                            'current_price': kl_pd['close'].iloc[-1],
                            'ma120_price': kl_pd['MA120'].iloc[-1]
                        }
                        results.append(result)
                        print(f"股票 {symbol} 符合条件: 角度={ma120_angle:.3f}, 突破天数={up_days}, 涨幅={up_ratio:.2f}%")

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
        找到价格首次超过120日均线的位置
        """
        # 确保有足够的数据
        if len(kl_pd) < 120:
            return None

        # 找到价格首次超过120日均线的位置
        for i in range(120, len(kl_pd)):
            if kl_pd['close'].iloc[i] > kl_pd['MA120'].iloc[i] and kl_pd['close'].iloc[i-1] <= kl_pd['MA120'].iloc[i-1]:
                return kl_pd.index[i]

        return None

    def _calculate_up_info(self, kl_pd, cross_date):
        """
        计算从突破开始到现在的涨幅天数和幅度
        """
        # 找到突破日期在数据中的位置
        cross_idx = kl_pd.index.get_loc(cross_date)
        cross_price = kl_pd['close'].iloc[cross_idx]
        current_price = kl_pd['close'].iloc[-1]

        # 计算涨幅天数
        up_days = len(kl_pd) - cross_idx - 1

        # 计算涨幅幅度
        up_ratio = ((current_price - cross_price) / cross_price) * 100

        return up_days, up_ratio

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
        保存结果到文件
        """
        import os

        # 创建todolist目录（如果不存在）
        todolist_dir = "todolist"
        if not os.path.exists(todolist_dir):
            os.makedirs(todolist_dir)
            print(f"创建目录: {todolist_dir}")

        today = datetime.date.today().strftime("%Y%m%d")
        file_name = os.path.join(todolist_dir, f"cal_a_up_days_{today}.csv")

        if results:
            df = pd.DataFrame(results)
            df.to_csv(file_name, index=False, encoding='utf-8-sig')
            print(f"结果已保存到文件: {file_name}")
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
            print(f"{i+1}. {result['symbol']} {result['co_name']} - 涨幅: {result['up_ratio']}%, 天数: {result['up_days']}")

        # 按角度排序
        results_angle_sorted = sorted(results, key=lambda x: x['ma120_angle'], reverse=True)

        print(f"\n角度前10名:")
        for i, result in enumerate(results_angle_sorted[:10]):
            print(f"{i+1}. {result['symbol']} {result['co_name']} - 角度: {result['ma120_angle']}, 涨幅: {result['up_ratio']}%")


if __name__ == '__main__':
    start_time = time.time()
    
    monitor = ALLAMonitorUpInfo()
    
    # 1、更新所有数据（可选，如果本地已有数据可以注释掉）
    # monitor.update_all_a_data()
    
    # 2、使用本地数据进行统计
    results = monitor.cal_a_up_days()
    
    print(f"\n总耗时: {time.time() - start_time:.2f} 秒") 