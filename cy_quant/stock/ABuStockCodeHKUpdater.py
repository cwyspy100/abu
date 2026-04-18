# -*- encoding:utf-8 -*-
"""
通过 tushare hk_basic 更新 stock_code_HK.csv

- 列顺序与历史 RomDataBu/stock_code_HK.csv 一致（20 列），见 stock_code_HK_field_notes.md
- symbol 固定 5 位字符串，前导 0 保留
- hk_basic 无法提供的列统一填 "-"
"""

import os
import json
import re
import pandas as pd
from abupy.CoreBu import ABuEnv

__author__ = 'abu_quant'

_STOCK_CODE_HK = os.path.join(ABuEnv.g_project_rom_data_dir, 'stock_code_HK.csv')

# 与 stock_code_HK.csv 标准表头顺序一致（含首列索引由 to_csv 写入）
HK_CSV_COLUMNS = [
    'co_name',
    'symbol',
    'market',
    'asset',
    'co_business',
    'amplitude',
    'pe_s_d',
    'co_intro',
    'sc',
    'hk_equity',
    'exchange',
    'mv',
    'pe_s',
    'pb_d',
    'equity',
    'ps',
    'industry',
    'turnover',
    'oo',
    'pb_MRQ',
]

DEFAULT_EMPTY = '-'


class ABuStockCodeHKUpdater:
    """通过 tushare hk_basic 更新 stock_code_HK.csv"""

    def __init__(self, token=None):
        self.token = token
        self.pro = None
        self.csv_path = _STOCK_CODE_HK

    def _init_tushare(self):
        if self.pro is not None:
            return
        token = self.token
        if token is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'todolist', 'config.json'
            )
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        token = config.get('token', '')
                except Exception as e:
                    print(f'读取配置文件失败: {e}')
        if not token:
            raise ValueError(
                'tushare token 未配置，请在 todolist/config.json 中设置 token 或传入 token 参数'
            )
        import tushare as ts
        ts.set_token(token)
        self.pro = ts.pro_api()

    @staticmethod
    def _normalize_hk_symbol(symbol, ts_code=''):
        """港股代码：仅数字部分，左补零至 5 位，保证前导 0（字符串）。"""
        s = str(symbol or '').strip()
        if not s and ts_code:
            s = ts_code.split('.')[0] if '.' in str(ts_code) else str(ts_code)
        digits = re.sub(r'\D', '', s)
        if not digits:
            return str(s).strip()
        return digits.zfill(5)

    @staticmethod
    def _cell_str(v):
        if v is None:
            return ''
        try:
            if pd.isnull(v):
                return ''
        except Exception:
            pass
        return str(v).strip()

    def _fetch_hk_basic_all(self):
        """拉取可交易港股：优先 list_status=L。"""
        self._init_tushare()
        df = None
        kwargs_used = {}
        for kwargs in ({'list_status': 'L'}, {}):
            kwargs_used = kwargs
            try:
                df = self.pro.hk_basic(**kwargs) if kwargs else self.pro.hk_basic()
            except Exception as e:
                print(f'hk_basic 调用失败 kwargs={kwargs}: {e}')
                df = None
            if df is not None and not df.empty:
                break
        if df is None or df.empty:
            raise RuntimeError('tushare hk_basic 返回空数据，请检查 token 与港股 hk_basic 权限')
        if not kwargs_used and 'list_status' in df.columns:
            df = df[df['list_status'].astype(str).str.upper() == 'L'].copy()
        if 'ts_code' in df.columns:
            df = df.drop_duplicates(subset=['ts_code'], keep='first')
        return df

    def _row_from_api(self, row):
        """仅 hk_basic 可映射字段；其余列占位 "-"。symbol 必为 str。"""
        ts_code = self._cell_str(row.get('ts_code', ''))
        sym = self._normalize_hk_symbol(row.get('symbol', ''), ts_code)
        name = self._cell_str(row.get('name', ''))
        market = self._cell_str(row.get('market', ''))
        fullname = self._cell_str(row.get('fullname', ''))
        out = {c: DEFAULT_EMPTY for c in HK_CSV_COLUMNS}
        out['co_name'] = name if name else DEFAULT_EMPTY
        out['symbol'] = sym
        out['market'] = market if market else DEFAULT_EMPTY
        out['co_intro'] = fullname if fullname else DEFAULT_EMPTY
        out['exchange'] = 'HK'
        return out

    def _build_rows(self, hk_df):
        rows = [self._row_from_api(row) for _, row in hk_df.iterrows()]
        result = pd.DataFrame(rows, dtype=object)
        if not result.empty:
            result['symbol'] = result['symbol'].astype(str)
            result = result.sort_values('symbol').reset_index(drop=True)
        return result

    def _merge_preserve_old_non_api(self, local_df, api_df):
        """
        对仍存在于本地的行：若 API 侧为 "-" 的列，本地原为非 "-" 则保留本地（旧爬虫/手工数据）。
        API 覆盖列：co_name, symbol, market, co_intro, exchange。
        """
        if local_df is None or local_df.empty:
            return api_df
        local_df = local_df.copy()
        for c in HK_CSV_COLUMNS:
            if c not in local_df.columns:
                local_df[c] = DEFAULT_EMPTY
        local_df['symbol'] = local_df['symbol'].astype(str).str.strip()
        api_df = api_df.copy()
        api_df['symbol'] = api_df['symbol'].astype(str).str.strip()
        loc_map = local_df.set_index('symbol', drop=False)
        api_cols = ['co_name', 'symbol', 'market', 'co_intro', 'exchange']
        preserve_cols = [c for c in HK_CSV_COLUMNS if c not in api_cols]
        merged = []
        for _, row in api_df.iterrows():
            sym = row['symbol']
            if sym in loc_map.index:
                old = loc_map.loc[sym]
                if isinstance(old, pd.DataFrame):
                    old = old.iloc[0]
                new = row.to_dict()
                for c in preserve_cols:
                    nv = new.get(c, DEFAULT_EMPTY)
                    ov = old.get(c, DEFAULT_EMPTY)
                    ovs = self._cell_str(ov) if ov is not None else DEFAULT_EMPTY
                    if (nv == DEFAULT_EMPTY or nv == '') and ovs not in ('', DEFAULT_EMPTY):
                        new[c] = ovs
                merged.append(new)
            else:
                merged.append(row.to_dict())
        return pd.DataFrame(merged)

    def _load_local_csv(self):
        if not os.path.exists(self.csv_path):
            return pd.DataFrame(columns=['symbol'])
        try:
            df = pd.read_csv(self.csv_path, index_col=0, dtype=str, encoding='utf-8-sig')
            if 'symbol' not in df.columns:
                raise ValueError(f'CSV 缺少 symbol 列: {df.columns.tolist()}')
            return df
        except Exception as e:
            raise RuntimeError(f'读取 {self.csv_path} 失败: {e}') from e

    def update(self, dry_run=False, preserve_old_filled=True):
        hk_raw = self._fetch_hk_basic_all()
        result_df = self._build_rows(hk_raw)
        local_df = self._load_local_csv()
        if preserve_old_filled and not local_df.empty and not result_df.empty:
            result_df = self._merge_preserve_old_non_api(local_df, result_df)

        local_syms = set(local_df['symbol'].astype(str).str.strip()) if not local_df.empty else set()
        new_syms = set(result_df['symbol'].astype(str).str.strip()) if not result_df.empty else set()
        removed = len(local_syms - new_syms)
        added = len(new_syms - local_syms)
        updated = len(local_syms & new_syms)

        print(f'本地记录数: {len(local_df)}')
        print(f'hk_basic 返回: {len(hk_raw)} 条（输出行数: {len(result_df)}）')
        print(f'移除（不在最新列表）: {removed}')
        print(f'新增: {added}')
        print(f'仍在列表中: {updated}')

        if not dry_run and not result_df.empty:
            for col in HK_CSV_COLUMNS:
                if col not in result_df.columns:
                    result_df[col] = DEFAULT_EMPTY
            result_df = result_df[HK_CSV_COLUMNS]
            result_df = result_df.fillna(DEFAULT_EMPTY)
            for col in HK_CSV_COLUMNS:
                result_df[col] = result_df[col].astype(str)
            os.makedirs(os.path.dirname(os.path.abspath(self.csv_path)), exist_ok=True)
            result_df.to_csv(self.csv_path, index=True, encoding='utf-8-sig')
            print(f'已保存至: {self.csv_path}')
        elif dry_run:
            print('(dry_run 模式，未写入文件)')

        return removed, added, updated

    def run(self, dry_run=False):
        return self.update(dry_run=dry_run)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='通过 tushare hk_basic 更新 stock_code_HK.csv')
    parser.add_argument('--dry-run', action='store_true', help='仅预览变更，不写入')
    parser.add_argument('--token', type=str, default=None, help='tushare token')
    parser.add_argument(
        '--no-preserve-old',
        action='store_true',
        help='不保留本地非 "-" 的旧列（默认会保留 mv/pe 等旧数据）',
    )
    args = parser.parse_args()

    updater = ABuStockCodeHKUpdater(token=args.token)
    updater.update(dry_run=args.dry_run, preserve_old_filled=not args.no_preserve_old)


if __name__ == '__main__':
    main()
