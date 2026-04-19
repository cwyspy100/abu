"""
Tushare 数据获取与缓存
支持财务指标、利润表、资产负债表、现金流量表
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class TushareFetcher:
    """Tushare 数据获取 + 本地缓存"""

    CACHE_DIR = "data/tushare_cache"
    RATE_LIMIT_DELAY = 1.0  # 秒，防止超过限制

    def __init__(self, token: Optional[str] = None):
        """
        初始化 Tushare fetcher

        :param token: Tushare token，默认从配置文件读取
        """
        if token is None:
            token = self._load_token()

        if not token:
            logger.warning("Tushare token 未设置，财务数据获取将不可用")

        try:
            import tushare as ts
            self.api = ts.pro_api(token) if token else None
            self.has_tushare = True
        except ImportError:
            logger.warning("Tushare 未安装，财务数据获取将不可用")
            self.api = None
            self.has_tushare = False

        os.makedirs(self.CACHE_DIR, exist_ok=True)

    def _load_token(self) -> str:
        """从配置文件加载 token"""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(root, "todolist", "config.json")

        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    return config.get("tushare_token", "") or config.get("token", "")
            except Exception as e:
                logger.error(f"读取配置文件失败: {e}")

        return os.getenv("TUSHARE_TOKEN", "")

    def _cache_path(self, table: str, ts_code: str) -> str:
        """获取缓存文件路径"""
        return os.path.join(self.CACHE_DIR, table, f"{ts_code}.csv")

    def _cache_valid(self, cache_file: str, days: int = 30) -> bool:
        """检查缓存是否有效"""
        if not os.path.exists(cache_file):
            return False

        # 检查文件修改时间
        mtime = datetime.fromtimestamp(os.path.getmtime(cache_file))
        age = (datetime.now() - mtime).days

        return age < days

    def _save_cache(self, df: pd.DataFrame, table: str, ts_code: str):
        """保存数据到缓存"""
        cache_dir = os.path.join(self.CACHE_DIR, table)
        os.makedirs(cache_dir, exist_ok=True)

        cache_file = self._cache_path(table, ts_code)
        # 使用 CSV 格式，避免 pyarrow 依赖
        df.to_csv(cache_file, index=False)
        logger.info(f"缓存已保存: {cache_file}")

    def _load_cache(self, table: str, ts_code: str) -> Optional[pd.DataFrame]:
        """从缓存加载数据"""
        cache_file = self._cache_path(table, ts_code)

        if not os.path.exists(cache_file):
            return None

        try:
            # 尝试 CSV 格式
            df = pd.read_csv(cache_file)
            logger.info(f"从缓存加载: {cache_file}")
            return df
        except Exception as e:
            logger.warning(f"缓存读取失败: {e}")
            return None

    def _call_api(self, table: str, func, ts_code: str = "unknown", days: int = 30) -> Optional[pd.DataFrame]:
        """
        调用 Tushare API，带限流和缓存

        :param table: 缓存表名（用于区分不同 API）
        :param func: Tushare API 函数
        :param ts_code: 股票代码（用于缓存路径）
        :param days: 缓存有效期
        :return: DataFrame
        """
        if not self.api:
            logger.warning("Tushare API 不可用")
            return None

        # 检查缓存
        cache_file = self._cache_path(table, ts_code)
        if self._cache_valid(cache_file, days):
            return self._load_cache(table, ts_code)

        # 调用 API（带限流）
        time.sleep(self.RATE_LIMIT_DELAY)

        try:
            df = func()

            if df is not None and not df.empty:
                self._save_cache(df, table, ts_code)

            return df
        except Exception as e:
            logger.error(f"Tushare API 调用失败: {e}")
            return None

    def fetch_fina_indicator(self, ts_code: str, start_date: str = "20180101",
                            end_date: Optional[str] = None, days: int = 30) -> Optional[pd.DataFrame]:
        """
        获取财务指标数据

        :param ts_code: 股票代码
        :param start_date: 开始日期
        :param end_date: 结束日期
        :param days: 缓存有效期（天）
        :return: 财务指标 DataFrame
        """
        if not self.has_tushare:
            return None

        import tushare as ts
        pro = self.api

        end_date = end_date or datetime.now().strftime("%Y%m%d")

        def _fetch():
            return pro.fina_indicator(ts_code=ts_code, start_date=start_date, end_date=end_date)

        df = self._call_api("fina_indicator", _fetch, ts_code=ts_code, days=days)

        if df is not None and not df.empty:
            # 按报告期排序，取最新
            df = df.sort_values("end_date", ascending=False).reset_index(drop=True)

        return df

    def fetch_income(self, ts_code: str, start_date: str = "20180101",
                     end_date: Optional[str] = None, days: int = 30) -> Optional[pd.DataFrame]:
        """
        获取利润表数据

        :param ts_code: 股票代码
        :param start_date: 开始日期
        :param end_date: 结束日期
        :param days: 缓存有效期（天）
        :return: 利润表 DataFrame
        """
        if not self.has_tushare:
            return None

        pro = self.api
        end_date = end_date or datetime.now().strftime("%Y%m%d")

        def _fetch():
            return pro.income(ts_code=ts_code, start_date=start_date, end_date=end_date)

        df = self._call_api("income", _fetch, ts_code=ts_code, days=days)

        if df is not None and not df.empty:
            df = df.sort_values("end_date", ascending=False).reset_index(drop=True)

        return df

    def fetch_balancesheet(self, ts_code: str, start_date: str = "20180101",
                           end_date: Optional[str] = None, days: int = 30) -> Optional[pd.DataFrame]:
        """
        获取资产负债表数据

        :param ts_code: 股票代码
        :param start_date: 开始日期
        :param end_date: 结束日期
        :param days: 缓存有效期（天）
        :return: 资产负债表 DataFrame
        """
        if not self.has_tushare:
            return None

        pro = self.api
        end_date = end_date or datetime.now().strftime("%Y%m%d")

        def _fetch():
            return pro.balancesheet(ts_code=ts_code, start_date=start_date, end_date=end_date)

        df = self._call_api("balancesheet", _fetch, ts_code=ts_code, days=days)

        if df is not None and not df.empty:
            df = df.sort_values("end_date", ascending=False).reset_index(drop=True)

        return df

    def fetch_cashflow(self, ts_code: str, start_date: str = "20180101",
                       end_date: Optional[str] = None, days: int = 30) -> Optional[pd.DataFrame]:
        """
        获取现金流量表数据

        :param ts_code: 股票代码
        :param start_date: 开始日期
        :param end_date: 结束日期
        :param days: 缓存有效期（天）
        :return: 现金流量表 DataFrame
        """
        if not self.has_tushare:
            return None

        pro = self.api
        end_date = end_date or datetime.now().strftime("%Y%m%d")

        def _fetch():
            return pro.cashflow(ts_code=ts_code, start_date=start_date, end_date=end_date)

        df = self._call_api("cashflow", _fetch, ts_code=ts_code, days=days)

        if df is not None and not df.empty:
            df = df.sort_values("end_date", ascending=False).reset_index(drop=True)

        return df

    def fetch_daily_basic(self, ts_code: str, trade_date: str = None, days: int = 30) -> Optional[pd.DataFrame]:
        """
        获取每日行情指标（包含 PE、PB、PS 等）

        :param ts_code: 股票代码
        :param trade_date: 交易日期，默认最新
        :param days: 缓存有效期（天）
        :return: 每日行情 DataFrame
        """
        if not self.has_tushare:
            return None

        pro = self.api
        trade_date = trade_date or datetime.now().strftime("%Y%m%d")

        def _fetch():
            return pro.daily_basic(ts_code=ts_code, end_date=trade_date,
                                  fields='ts_code,trade_date,close,pe,pb,ps,total_mv,circ_mv')

        df = self._call_api("daily_basic", _fetch, ts_code=ts_code, days=days)

        if df is not None and not df.empty:
            df = df.sort_values("trade_date", ascending=False).reset_index(drop=True)

        return df

    def fetch_all_financial(self, ts_code: str, days: int = 30) -> Dict[str, Any]:
        """
        获取所有财务数据，合并为一个字典

        :param ts_code: 股票代码
        :param days: 缓存有效期
        :return: 财务数据字典
        """
        result = {}

        # 获取财务指标
        fina_df = self.fetch_fina_indicator(ts_code, days=days)
        if fina_df is not None and not fina_df.empty:
            result["fina_indicator"] = fina_df.iloc[0].to_dict()

        # 获取利润表
        income_df = self.fetch_income(ts_code, days=days)
        if income_df is not None and not income_df.empty:
            result["income"] = income_df.iloc[0].to_dict()

        # 获取资产负债表
        bs_df = self.fetch_balancesheet(ts_code, days=days)
        if bs_df is not None and not bs_df.empty:
            result["balancesheet"] = bs_df.iloc[0].to_dict()

        # 获取现金流量表
        cf_df = self.fetch_cashflow(ts_code, days=days)
        if cf_df is not None and not cf_df.empty:
            result["cashflow"] = cf_df.iloc[0].to_dict()

        return result

    def get_latest_financial_summary(self, ts_code: str) -> Dict[str, Any]:
        """
        获取最新财务数据摘要，用于 AI 分析

        :param ts_code: 股票代码
        :return: 财务摘要字典
        """
        fina_df = self.fetch_fina_indicator(ts_code, days=30)

        if fina_df is None or fina_df.empty:
            logger.warning(f"未获取到 {ts_code} 的财务数据")
            return {}

        latest = fina_df.iloc[0]

        # 从 daily_basic 获取 PE/PB/PS
        pe_val, pb_val, ps_val = None, None, None
        basic_df = self.fetch_daily_basic(ts_code, days=30)
        if basic_df is not None and not basic_df.empty:
            basic_latest = basic_df.iloc[0]
            pe_val = self._safe_float(basic_latest.get("pe"))
            pb_val = self._safe_float(basic_latest.get("pb"))
            ps_val = self._safe_float(basic_latest.get("ps"))

        # grossprofit_margin 在 fina_indicator 中
        gross_margin = self._safe_float(latest.get("grossprofit_margin"))

        # 提取关键字段
        summary = {
            "pe": pe_val,
            "pb": pb_val,
            "ps": ps_val,
            "roe": self._safe_float(latest.get("roe")),
            "roe_dt": self._safe_float(latest.get("roe_dt")),
            "gross_margin": gross_margin,
            "net_margin": self._safe_float(latest.get("netprofit_margin")),
            "netprofit_yoy": self._safe_float(latest.get("netprofit_yoy")),
            "revenue_yoy": self._safe_float(latest.get("tr_yoy")) or self._safe_float(latest.get("or_yoy")),
            "op_yoy": self._safe_float(latest.get("op_yoy")),
            "debt_to_assets": self._safe_float(latest.get("debt_to_assets")),
            "current_ratio": self._safe_float(latest.get("current_ratio")),
            "quick_ratio": self._safe_float(latest.get("quick_ratio")),
            "eps": self._safe_float(latest.get("eps")),
            "bps": self._safe_float(latest.get("bps")),
            "ocfps": self._safe_float(latest.get("ocfps")),
            "ar_turn": self._safe_float(latest.get("ar_turn")),
            "inv_turn": self._safe_float(latest.get("inv_turn")),
            "assets_turn": self._safe_float(latest.get("assets_turn")),
            "ocf_to_or": self._safe_float(latest.get("ocf_to_or")),
            "ann_date": str(latest.get("ann_date", "")),
            "end_date": str(latest.get("end_date", "")),
        }

        return summary

    @staticmethod
    def _safe_float(value, default: float = None) -> Optional[float]:
        """安全转换为浮点数"""
        if value is None or pd.isna(value):
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    fetcher = TushareFetcher()

    # 测试获取财务数据
    ts_code = "600036.SH"

    print("=" * 50)
    print(f"获取 {ts_code} 财务数据")
    print("=" * 50)

    summary = fetcher.get_latest_financial_summary(ts_code)

    if summary:
        print(f"财务摘要:")
        for k, v in summary.items():
            print(f"  {k}: {v}")
    else:
        print("未获取到财务数据，请检查 Tushare Token")
