# -*- encoding:utf-8 -*-
"""
通过 tushare 接口更新 stock_code_CN.csv
- 不在 tushare 列表中的股票（退市等）移除
- 新增的股票添加
- 保留原有列结构，tushare 无的字段用 "-" 填充
"""

import os
import json
import pandas as pd
from abupy.CoreBu import ABuEnv

__author__ = 'abu_quant'

# stock_code_CN.csv 路径（g_project_rom_data_dir 已指向 RomDataBu）
_STOCK_CODE_CN = os.path.join(ABuEnv.g_project_rom_data_dir, 'stock_code_CN.csv')

# CSV 列定义（与原有结构一致）
CSV_COLUMNS = [
    'co_name', 'symbol', 'market', 'asset', 'co_business', 'cc', 'amplitude',
    'pe_s_d', 'co_intro', 'exchange', 'mv', 'pb_d', 'ps_d', 'equity', 'industry'
]

# tushare 无的字段默认值
DEFAULT_EMPTY = '-'


class ABuStockCodeCNUpdater:
    """通过 tushare 更新 stock_code_CN.csv"""

    def __init__(self, token=None):
        """
        :param token: tushare token，None 时从 todolist/config.json 读取
        """
        self.token = token
        self.pro = None
        self.csv_path = _STOCK_CODE_CN

    def _init_tushare(self):
        """初始化 tushare pro"""
        if self.pro is not None:
            return
        token = self.token
        if token is None:
            # 计算配置文件路径：从 cy_quant/ABuStockCodeCNUpdater.py -> abu-master/todolist/config.json
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'todolist', 'config.json'
            )
            print(f'尝试读取配置文件: {config_path}')
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        token = config.get('token', '')
                        print(f'从配置文件读取到 token: {token[:10]}...' if token else '配置文件中没有找到 token')
                except Exception as e:
                    print(f'读取配置文件失败: {e}')
            else:
                print(f'配置文件不存在: {config_path}')
        if not token:
            raise ValueError('tushare token 未配置，请在 todolist/config.json 中设置 token 或传入 token 参数，或直接在代码中传入 token 参数')
        import tushare as ts
        ts.set_token(token)
        self.pro = ts.pro_api()

    def _load_local_csv(self):
        """加载本地 stock_code_CN.csv"""
        if not os.path.exists(self.csv_path):
            return pd.DataFrame(columns=CSV_COLUMNS)
        try:
            df = pd.read_csv(self.csv_path, index_col=0, dtype=str, encoding='utf-8-sig')
            if 'symbol' not in df.columns:
                raise ValueError(f'CSV 缺少 symbol 列，现有列: {df.columns.tolist()}')
            if 'exchange' not in df.columns:
                # 从 symbol 推断：6 开头为 SH，其余为 SZ
                df['exchange'] = df['symbol'].apply(
                    lambda x: 'SH' if str(x).startswith('6') else 'SZ'
                )
            return df
        except Exception as e:
            raise RuntimeError(f'读取 {self.csv_path} 失败: {e}') from e

    def _fetch_tushare_stock_list(self):
        """
        从 tushare 获取 A 股上市股票列表
        :return: DataFrame，含 ts_code, symbol, name, market, industry, list_date 等
        """
        self._init_tushare()
        fields = 'ts_code,symbol,name,market,industry,list_date,exchange'
        df = self.pro.stock_basic(
            exchange='',
            list_status='L',
            fields=fields
        )
        if df is None or df.empty:
            raise RuntimeError('tushare stock_basic 返回空数据')
        return df

    def _ts_code_to_exchange(self, ts_code):
        """ts_code 如 000001.SZ -> SZ, 600000.SH -> SH, 430047.BJ -> BJ"""
        if '.' in ts_code:
            return ts_code.split('.')[-1].upper()
        return ''

    def _build_tushare_df_for_merge(self, ts_df):
        """
        将 tushare 数据转换为与 CSV 兼容的格式
        """
        rows = []
        for _, row in ts_df.iterrows():
            ts_code = row.get('ts_code', '')
            symbol = row.get('symbol', ts_code.split('.')[0] if '.' in ts_code else '')
            name = row.get('name', '')
            market = row.get('market', '')
            industry = row.get('industry', '') or DEFAULT_EMPTY
            exchange = self._ts_code_to_exchange(ts_code)
            if not exchange:
                exchange = 'SH' if symbol.startswith('6') else 'SZ'
            rows.append({
                'co_name': name,
                'symbol': symbol,
                'market': market or exchange,
                'asset': DEFAULT_EMPTY,
                'co_business': DEFAULT_EMPTY,
                'cc': DEFAULT_EMPTY,
                'amplitude': DEFAULT_EMPTY,
                'pe_s_d': DEFAULT_EMPTY,
                'co_intro': DEFAULT_EMPTY,
                'exchange': exchange,
                'mv': DEFAULT_EMPTY,
                'pb_d': DEFAULT_EMPTY,
                'ps_d': DEFAULT_EMPTY,
                'equity': DEFAULT_EMPTY,
                'industry': industry,
            })
        return pd.DataFrame(rows)

    def _merge_preserve_old_data(self, local_df, ts_df):
        """
        合并逻辑：
        - 在 tushare 中存在的：保留本地已有数据（asset, co_business 等），用 tushare 更新 name/industry
        - 不在 tushare 中的：移除
        - 新增的：用 tushare 数据，无的字段填 "-"
        """
        # 用 symbol+exchange 作为唯一键（兼容不同市场同代码）
        local_df = local_df.copy()
        ts_df = ts_df.copy()
        local_df['_key'] = local_df['symbol'].astype(str) + '_' + local_df['exchange'].astype(str)
        ts_df['_key'] = ts_df['symbol'].astype(str) + '_' + ts_df['exchange'].astype(str)

        ts_keys = set(ts_df['_key'].tolist())
        local_keys = set(local_df['_key'].tolist())

        to_remove = local_keys - ts_keys
        to_add = ts_keys - local_keys
        to_update = local_keys & ts_keys

        # 构建结果
        result_rows = []
        for _, local_row in local_df.iterrows():
            key = local_row['_key']
            if key in to_remove:
                continue
            if key in to_update:
                ts_row = ts_df[ts_df['_key'] == key].iloc[0]
                # 保留本地有值的列，用 tushare 更新 name、industry
                merged = {k: v for k, v in local_row.items() if k != '_key'}
                merged['co_name'] = ts_row['co_name']
                merged['industry'] = ts_row['industry'] if (ts_row['industry'] and ts_row['industry'] != DEFAULT_EMPTY) else merged.get('industry', DEFAULT_EMPTY)
                merged['market'] = ts_row['market'] or merged.get('market', '')
                merged['exchange'] = ts_row['exchange']
                result_rows.append(merged)

        for _, ts_row in ts_df.iterrows():
            key = ts_row['_key']
            if key in to_add:
                row_dict = {k: v for k, v in ts_row.items() if k != '_key'}
                result_rows.append(row_dict)

        result_df = pd.DataFrame(result_rows)
        if not result_df.empty:
            # 按 exchange, symbol 排序
            result_df = result_df.sort_values(['exchange', 'symbol']).reset_index(drop=True)
        return result_df, len(to_remove), len(to_add), len(to_update)

    def update(self, dry_run=False):
        """
        执行更新
        :param dry_run: True 时只打印变更，不写入文件
        :return: (removed_count, added_count, updated_count)
        """
        local_df = self._load_local_csv()
        ts_df = self._fetch_tushare_stock_list()
        ts_for_merge = self._build_tushare_df_for_merge(ts_df)

        result_df, removed, added, updated = self._merge_preserve_old_data(
            local_df, ts_for_merge
        )

        print(f'本地股票数: {len(local_df)}')
        print(f'tushare 股票数: {len(ts_df)}')
        print(f'移除（退市等）: {removed}')
        print(f'新增: {added}')
        print(f'更新（保留）: {updated}')
        print(f'更新后总数: {len(result_df)}')

        if not dry_run and not result_df.empty:
            # 确保列顺序和完整性
            for col in CSV_COLUMNS:
                if col not in result_df.columns:
                    result_df[col] = DEFAULT_EMPTY
            result_df = result_df[CSV_COLUMNS]
            result_df = result_df.fillna(DEFAULT_EMPTY)
            result_df.to_csv(self.csv_path, index=True, encoding='utf-8-sig')
            print(f'已保存至: {self.csv_path}')
        elif dry_run:
            print('(dry_run 模式，未写入文件)')

        return removed, added, updated

    def run(self, dry_run=False):
        """别名，便于调用"""
        return self.update(dry_run=dry_run)


def main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser(description='通过 tushare 更新 stock_code_CN.csv')
    parser.add_argument('--dry-run', action='store_true', help='仅预览变更，不写入')
    parser.add_argument('--token', type=str, default=None, help='tushare token')
    args = parser.parse_args()

    updater = ABuStockCodeCNUpdater(token=args.token)
    updater.update(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
