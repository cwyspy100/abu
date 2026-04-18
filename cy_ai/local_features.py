"""
本地股票特征提取：从 ~/abu/data/csv 的个股文件中提取最近技术特征
"""

import glob
import os
from typing import Dict, Any, Optional

import pandas as pd


class LocalFeatureBuilder:
    def __init__(self, csv_dir: Optional[str] = None):
        self.csv_dir = csv_dir or os.path.expanduser("~/abu/data/csv")

    @staticmethod
    def _prefix_candidates(ts_code: str):
        code = str(ts_code).zfill(6)
        return ["sh%s" % code, "sz%s" % code, "hk%s" % code, "us%s" % code]

    def _latest_file(self, ts_code: str) -> Optional[str]:
        files = []
        for p in self._prefix_candidates(ts_code):
            files.extend(glob.glob(os.path.join(self.csv_dir, "%s_*" % p)))
            files.extend(glob.glob(os.path.join(self.csv_dir, "%s_*.csv" % p)))
        if not files:
            return None
        files = sorted(set(files))
        return files[-1]

    def _read_df(self, path: str) -> Optional[pd.DataFrame]:
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                df = pd.read_csv(path, encoding=enc)
                if not df.empty:
                    return df
            except Exception:
                continue
        return None

    def build(self, ts_code: str) -> Dict[str, Any]:
        path = self._latest_file(ts_code)
        if not path:
            return {}
        df = self._read_df(path)
        if df is None or df.empty or "close" not in df.columns:
            return {}

        if "trade_date" not in df.columns and "date" in df.columns:
            df = df.rename(columns={"date": "trade_date"})
        if "trade_date" in df.columns:
            df = df.sort_values("trade_date").reset_index(drop=True)
        else:
            df = df.reset_index(drop=True)

        close = pd.to_numeric(df["close"], errors="coerce")
        if close.isnull().all():
            return {}

        last_close = float(close.iloc[-1])
        ma20 = float(close.rolling(20, min_periods=1).mean().iloc[-1])
        ma60 = float(close.rolling(60, min_periods=1).mean().iloc[-1])
        ret_5 = float((close.iloc[-1] / close.iloc[-5] - 1) * 100) if len(close) >= 5 and close.iloc[-5] else 0.0
        ret_20 = float((close.iloc[-1] / close.iloc[-20] - 1) * 100) if len(close) >= 20 and close.iloc[-20] else 0.0

        volume_ratio = None
        if "volume" in df.columns:
            vol = pd.to_numeric(df["volume"], errors="coerce")
            ma_vol20 = vol.rolling(20, min_periods=1).mean().iloc[-1]
            if ma_vol20 and not pd.isnull(ma_vol20):
                volume_ratio = float(vol.iloc[-1] / ma_vol20)

        atr21 = None
        if "atr21" in df.columns:
            atr21 = pd.to_numeric(df["atr21"], errors="coerce").iloc[-1]
            atr21 = float(atr21) if not pd.isnull(atr21) else None

        return {
            "latest_file": os.path.basename(path),
            "last_close": round(last_close, 4),
            "ma20": round(ma20, 4),
            "ma60": round(ma60, 4),
            "ret_5d_pct": round(ret_5, 2),
            "ret_20d_pct": round(ret_20, 2),
            "volume_ratio_20": round(volume_ratio, 4) if volume_ratio is not None else None,
            "atr21": round(atr21, 4) if atr21 is not None else None,
        }

    def build_with_financial(self, ts_code: str, financial_data: Optional[dict] = None) -> Dict[str, Any]:
        """
        构建带财务数据的完整特征

        :param ts_code: 股票代码
        :param financial_data: 财务数据字典，如果为 None 则尝试从本地获取
        :return: 完整特征字典
        """
        tech_features = self.build(ts_code)

        if financial_data is None:
            financial_data = self._get_financial_from_local(ts_code)

        result = {
            "ts_code": ts_code,
            "technical": tech_features,
            "financial": financial_data,
        }

        if tech_features.get("ma120"):
            price = tech_features.get("last_close", 0)
            ma120 = tech_features.get("ma120", 0)
            if ma120 > 0:
                result["price_position"] = {
                    "vs_ma120": f"{(price/ma120 - 1)*100:+.1f}%",
                }

        return result

    def _get_financial_from_local(self, ts_code: str) -> dict:
        """
        从本地数据获取财务特征

        :param ts_code: 股票代码
        :return: 财务特征字典
        """
        # TODO: 实现从本地 Tushare 数据文件读取财务数据
        # 目前返回空字典，后续可扩展
        return {}

    def build_full_payload(self, ts_code: str, name: str, industry: str,
                          financial_data: Optional[dict] = None) -> Dict[str, Any]:
        """
        构建完整的 AI 分析输入

        :param ts_code: 股票代码
        :param name: 股票名称
        :param industry: 行业
        :param financial_data: 财务数据
        :return: 完整的 payload
        """
        features = self.build_with_financial(ts_code, financial_data)

        return {
            "ts_code": ts_code,
            "name": name,
            "industry": industry,
            **features
        }
