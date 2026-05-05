# -*- encoding:utf-8 -*-
"""
根据 RomDataBu 下的美股 Excel 上市列表更新 stock_code_US.csv。

- 表头与列顺序与 stock_code_US.csv 一致；Excel 为最新上市集合：不在 Excel 的代码从 CSV 移除；
  Excel 中有而 CSV 无的代码按 CSV 格式新增。
- Excel 能映射的列从 Excel 写入；co_site、co_intro、prospectus、co_tel、exchange、co_addr
  等 Excel 无字段：对已存在代码保留本地原值（非「-」时），新代码填「-」。
- 总市值、净利润等按旧版「万 / 亿」风格格式化；pe_s_d 用每股收益与 TTM 市盈率（Excel），形如 x/y。
"""

import os
import argparse
import pandas as pd

__author__ = 'abu_quant'

# 与 abupy.CoreBu.ABuEnv.g_project_rom_data_dir 一致：abu-master/abupy/RomDataBu（避免 import abupy 全链依赖）
_ROM_DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'abupy', 'RomDataBu')
)
_STOCK_CODE_US = os.path.join(_ROM_DATA_DIR, 'stock_code_US.csv')
_DEFAULT_EXCEL = os.path.join(_ROM_DATA_DIR, '4-25美股数据.xlsx')

# 与 stock_code_US.csv 数据列一致（不含文件首列索引）
US_CSV_COLUMNS = [
    'co_name',
    'symbol',
    'market',
    'asset',
    'co_site',
    'amplitude',
    'pe_s_d',
    'co_intro',
    'sc',
    'prospectus',
    'co_tel',
    'exchange',
    'co_addr',
    'mv',
    'equity',
    'industry',
    'turnover',
    'oo',
    'pb_MRQ',
]

# Excel 无对应列时，合并保留本地
_PRESERVE_LOCAL_COLS = frozenset(
    {'co_site', 'co_intro', 'prospectus', 'co_tel', 'exchange', 'co_addr'}
)

DEFAULT_EMPTY = '-'


class ABuStockCodeUSUpdater:
    """用美股 Excel 列表更新 stock_code_US.csv"""

    def __init__(self, excel_path=None):
        self.csv_path = _STOCK_CODE_US
        self.excel_path = excel_path or _DEFAULT_EXCEL

    @staticmethod
    def _cell_str(v):
        if v is None:
            return ''
        try:
            if pd.isna(v):
                return ''
        except Exception:
            pass
        return str(v).strip()

    @staticmethod
    def _norm_symbol(sym):
        s = str(sym or '').strip().upper()
        return s

    @staticmethod
    def _fmt_num_trim(v, nd=2):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return '-'
        try:
            x = float(v)
        except (TypeError, ValueError):
            return '-'
        if abs(x) < 1e-12:
            s = f'{x:.{nd}f}'
        else:
            s = f'{x:.{nd}f}'.rstrip('0').rstrip('.')
        return s if s not in ('', '-0') else '0'

    @classmethod
    def _fmt_usd_wan_yi(cls, v):
        """美元绝对值：旧版「万 / 亿」风格（亿=1e8 美元，万=1e4 美元）。"""
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return DEFAULT_EMPTY
        try:
            x = float(v)
        except (TypeError, ValueError):
            return DEFAULT_EMPTY
        neg = x < 0
        ax = abs(x)
        sign = '-' if neg else ''
        if ax >= 1e8 - 1e-6:
            return sign + f'{ax / 1e8:.2f}亿'
        if ax >= 1e4 - 1e-6:
            return sign + f'{ax / 1e4:.2f}万'
        if ax >= 1.0 - 1e-9:
            return sign + f'{ax:.2f}'
        return sign + cls._fmt_num_trim(x, nd=4)

    @classmethod
    def _fmt_pct_from_ratio(cls, v):
        """将 (0,1] 内比例转为「12.34%」；绝对值大于 1 视为已是百分数，仅加 %。"""
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return DEFAULT_EMPTY
        try:
            x = float(v)
        except (TypeError, ValueError):
            return DEFAULT_EMPTY
        ax = abs(x)
        if ax <= 1.0 + 1e-9:
            return f'{x * 100.0:.2f}%'
        return f'{x:.2f}%'

    @classmethod
    def _fmt_pct_direct(cls, v):
        """字段本身已是百分数（如机构持仓%）。"""
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return DEFAULT_EMPTY
        try:
            x = float(v)
        except (TypeError, ValueError):
            return DEFAULT_EMPTY
        return f'{x:.2f}%'

    @classmethod
    def _fmt_sc_from_change_ratio(cls, v):
        """涨幅：多数为比例（<=1 乘 100）；大于 1 视为已是百分数。"""
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return DEFAULT_EMPTY
        try:
            x = float(v)
        except (TypeError, ValueError):
            return DEFAULT_EMPTY
        ax = abs(x)
        if ax <= 1.0 + 1e-9:
            x = x * 100.0
        return f'{x:.2f}'.rstrip('0').rstrip('.')

    @classmethod
    def _fmt_pe_s_d(cls, row):
        """每股收益 / TTM市盈率，与 Excel 一致；缺省为 -/-。"""
        eps = row.get('每股收益')
        ttm = row.get('TTM市盈率')
        left = cls._fmt_num_trim(eps, nd=4) if not (eps is None or (isinstance(eps, float) and pd.isna(eps))) else '-'
        right = cls._fmt_num_trim(ttm, nd=4) if not (ttm is None or (isinstance(ttm, float) and pd.isna(ttm))) else '-'
        if left == '-':
            left = '-'
        if right == '-':
            right = '-'
        return f'{left}/{right}'

    def _read_excel(self):
        if not os.path.isfile(self.excel_path):
            raise FileNotFoundError(f'未找到 Excel: {self.excel_path}')
        df = pd.read_excel(self.excel_path, dtype=object)
        df.columns = [str(c).strip() for c in df.columns]
        need = {'代码', '名称'}
        miss = need - set(df.columns)
        if miss:
            raise ValueError(f'Excel 缺少列: {miss}，现有列: {list(df.columns)}')
        return df

    def _row_from_excel(self, row):
        """仅由 Excel 推导的各列（含 symbol）。"""
        sym = self._norm_symbol(row.get('代码'))
        name = self._cell_str(row.get('名称'))
        out = {c: DEFAULT_EMPTY for c in US_CSV_COLUMNS}
        out['symbol'] = sym if sym else DEFAULT_EMPTY
        out['co_name'] = name if name else DEFAULT_EMPTY
        out['market'] = 'US'
        out['asset'] = self._fmt_num_trim(row.get('现价'), nd=4)
        out['amplitude'] = self._fmt_pct_from_ratio(row.get('振幅'))
        out['pe_s_d'] = self._fmt_pe_s_d(row)
        out['sc'] = self._fmt_sc_from_change_ratio(row.get('涨幅'))
        out['industry'] = self._cell_str(row.get('所属行业')) or DEFAULT_EMPTY
        out['turnover'] = self._fmt_pct_from_ratio(row.get('换手'))
        out['oo'] = self._fmt_pct_direct(row.get('机构持仓%'))
        out['pb_MRQ'] = self._fmt_num_trim(row.get('市净率'), nd=4)

        mv_raw = row.get('总市值(＄)')
        if mv_raw is None or (isinstance(mv_raw, float) and pd.isna(mv_raw)):
            mv_raw = row.get('总市值($)')  # 备用 ASCII 美元符
        out['mv'] = self._fmt_usd_wan_yi(mv_raw)

        profit = row.get('净利润')
        if profit is None or (isinstance(profit, float) and pd.isna(profit)):
            out['equity'] = self._fmt_num_trim(row.get('每股净资产'), nd=4)
        else:
            out['equity'] = self._fmt_usd_wan_yi(profit)

        return out

    def _merge_preserve_local(self, old_row, excel_row):
        new = self._row_from_excel(excel_row)
        if old_row is None:
            return new
        for c in _PRESERVE_LOCAL_COLS:
            nv = self._cell_str(new.get(c, DEFAULT_EMPTY))
            ov = self._cell_str(old_row.get(c, DEFAULT_EMPTY))
            if (not nv or nv == DEFAULT_EMPTY) and ov and ov != DEFAULT_EMPTY:
                new[c] = ov
        return new

    def _load_local_csv(self):
        if not os.path.exists(self.csv_path):
            return pd.DataFrame(columns=US_CSV_COLUMNS)
        try:
            df = pd.read_csv(self.csv_path, index_col=0, dtype=str, encoding='utf-8-sig')
        except Exception as e:
            raise RuntimeError(f'读取 {self.csv_path} 失败: {e}') from e
        if 'symbol' not in df.columns:
            raise ValueError(f'CSV 缺少 symbol 列: {df.columns.tolist()}')
        for c in US_CSV_COLUMNS:
            if c not in df.columns:
                df[c] = DEFAULT_EMPTY
        return df[US_CSV_COLUMNS]

    def build_result(self, excel_df, local_df):
        local_df = local_df.copy()
        local_df['symbol'] = local_df['symbol'].astype(str).map(self._norm_symbol)
        local_df = local_df[local_df['symbol'].astype(str).str.len() > 0]
        local_df = local_df.drop_duplicates(subset=['symbol'], keep='first')
        loc_map = local_df.set_index('symbol', drop=False)

        merged_rows = []
        for _, er in excel_df.iterrows():
            sym = self._norm_symbol(er.get('代码'))
            if not sym:
                continue
            old = None
            if sym in loc_map.index:
                hit = loc_map.loc[sym]
                if isinstance(hit, pd.DataFrame):
                    hit = hit.iloc[0]
                old = hit.to_dict()
            merged_rows.append(self._merge_preserve_local(old, er))

        result = pd.DataFrame(merged_rows)
        if not result.empty:
            result['symbol'] = result['symbol'].astype(str)
            result = result.sort_values('symbol').reset_index(drop=True)
        return result

    def update(self, dry_run=False, excel_path=None):
        if excel_path:
            self.excel_path = excel_path

        excel_df = self._read_excel()
        local_df = self._load_local_csv()

        local_syms = set(local_df['symbol'].map(self._norm_symbol)) if not local_df.empty else set()
        excel_syms = {self._norm_symbol(x) for x in excel_df['代码'].tolist() if self._norm_symbol(x)}
        excel_syms.discard('')

        removed = len(local_syms - excel_syms)
        added = len(excel_syms - local_syms)
        updated = len(local_syms & excel_syms)

        result_df = self.build_result(excel_df, local_df)

        print(f'Excel: {self.excel_path}（行数 {len(excel_df)}）')
        print(f'本地 CSV 行数: {len(local_df)}')
        print(f'移除（不在 Excel 列表）: {removed}')
        print(f'新增（Excel 有、CSV 无）: {added}')
        print(f'保留并刷新（交集）: {updated}')
        print(f'更新后总行数: {len(result_df)}')

        if not dry_run and not result_df.empty:
            for col in US_CSV_COLUMNS:
                if col not in result_df.columns:
                    result_df[col] = DEFAULT_EMPTY
            result_df = result_df[US_CSV_COLUMNS]
            result_df = result_df.fillna(DEFAULT_EMPTY)
            for col in US_CSV_COLUMNS:
                result_df[col] = result_df[col].astype(str)
            os.makedirs(os.path.dirname(os.path.abspath(self.csv_path)), exist_ok=True)
            result_df.to_csv(self.csv_path, index=True, encoding='utf-8-sig')
            print(f'已保存至: {self.csv_path}')
        elif dry_run:
            print('(dry_run，未写入文件)')

        return removed, added, updated

    def run(self, dry_run=False, excel_path=None):
        return self.update(dry_run=dry_run, excel_path=excel_path)


def main():
    parser = argparse.ArgumentParser(description='用美股 Excel 更新 stock_code_US.csv')
    parser.add_argument('--dry-run', action='store_true', help='仅统计，不写 CSV')
    parser.add_argument(
        '--excel',
        type=str,
        default=None,
        help=f'Excel 路径，默认: {_DEFAULT_EXCEL}',
    )
    args = parser.parse_args()
    ABuStockCodeUSUpdater(excel_path=args.excel).update(dry_run=args.dry_run, excel_path=args.excel)


if __name__ == '__main__':
    main()
