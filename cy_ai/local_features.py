"""
本地股票特征提取：从 ~/abu/data/csv 的个股文件中提取最近技术特征
"""

import glob
import os
from typing import Dict, Any, Optional

import pandas as pd


class LocalFeatureBuilder:
    """本地K线特征提取器"""

    def __init__(self, csv_dir: Optional[str] = None):
        base_dir = csv_dir or os.path.expanduser("~/abu/data/csv")
        # A股在 astock 子目录，港股美股在根目录
        self.csv_dirs = [
            os.path.join(base_dir, "astock"),  # A股
            base_dir,  # 港股、美股
        ]

    @staticmethod
    def _prefix_candidates(ts_code: str):
        """生成可能的文件名前缀"""
        # 提取纯数字代码
        digits = ''.join(filter(str.isdigit, str(ts_code)))
        pure_code = digits.zfill(6)
        return ["sh%s" % pure_code, "sz%s" % pure_code, "hk%s" % pure_code, "us%s" % pure_code]

    def _latest_file(self, ts_code: str) -> Optional[str]:
        """查找本地CSV文件，匹配 sh600036_20240126_20260418 格式"""
        files = []

        # 确保 ts_code 是字符串
        ts_code = str(ts_code)
        # 提取纯数字代码
        digits = ''.join(filter(str.isdigit, ts_code))
        pure_code = digits.zfill(6)

        # 判断市场前缀
        ts_upper = ts_code.upper()
        if ts_upper.endswith(".SH") or ts_upper.endswith(".SZ"):
            prefixes = ["sh", "sz"]
        elif ts_upper.endswith(".HK"):
            prefixes = ["hk"]
        elif ts_upper.endswith(".US"):
            prefixes = ["us"]
        else:
            prefixes = ["sh", "sz", "hk", "us"]

        # 在多个目录中搜索
        for csv_dir in self.csv_dirs:
            if not os.path.exists(csv_dir):
                continue
            for prefix in prefixes:
                # 匹配 sh600036_ 开头的文件（有无.csv后缀都匹配）
                pattern1 = os.path.join(csv_dir, "%s%s_*" % (prefix, pure_code))
                pattern2 = os.path.join(csv_dir, "%s%s_*.csv" % (prefix, pure_code))
                files.extend(glob.glob(pattern1))
                files.extend(glob.glob(pattern2))

        if not files:
            return None

        # 按修改时间排序，返回最新的
        files = sorted(set(files), key=lambda f: os.path.getmtime(f))
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
        """
        从本地CSV提取技术特征

        :param ts_code: 股票代码
        :return: 技术特征字典
        """
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
        ma5 = float(close.rolling(5, min_periods=1).mean().iloc[-1])
        ma20 = float(close.rolling(20, min_periods=1).mean().iloc[-1])
        ma60 = float(close.rolling(60, min_periods=1).mean().iloc[-1])
        ma120 = float(close.rolling(120, min_periods=1).mean().iloc[-1])

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

        atr14 = None
        if "atr14" in df.columns:
            atr14 = pd.to_numeric(df["atr14"], errors="coerce").iloc[-1]
            atr14 = float(atr14) if not pd.isnull(atr14) else None
        elif atr21 is not None:
            atr14 = atr21 * 0.9

        # 判断趋势状态
        trend_status = self._judge_trend(ma5, ma20, ma60, ma120)

        # 计算价格相对MA120偏离
        price_vs_ma120_pct = None
        if ma120 > 0:
            price_vs_ma120_pct = round((last_close / ma120 - 1) * 100, 2)

        return {
            "latest_file": os.path.basename(path),
            "price": round(last_close, 2),
            "ma5": round(ma5, 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "ma120": round(ma120, 2),
            "price_vs_ma120_pct": price_vs_ma120_pct,
            "ret_5d": round(ret_5, 2),
            "ret_20d": round(ret_20, 2),
            "volume_ratio": round(volume_ratio, 2) if volume_ratio is not None else None,
            "atr14": round(atr14, 4) if atr14 is not None else None,
            "atr21": round(atr21, 4) if atr21 is not None else None,
            "trend_status": trend_status,
        }

    @staticmethod
    def _judge_trend(ma5: float, ma20: float, ma60: float, ma120: float) -> str:
        """判断趋势状态"""
        if ma5 > ma20 > ma60 > ma120:
            return "多头排列"
        elif ma5 < ma20 < ma60 < ma120:
            return "空头排列"
        else:
            return "震荡"

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
            **tech_features,
            "financial": financial_data,
        }

        return result

    def _get_financial_from_local(self, ts_code: str) -> dict:
        """
        从本地数据获取财务特征

        :param ts_code: 股票代码
        :return: 财务特征字典
        """
        return {}

    def build_full_payload(self, ts_code: str, name: str, industry: str,
                          financial_data: Optional[dict] = None,
                          sentiment_data: Optional[dict] = None) -> Dict[str, Any]:
        """
        构建完整的 AI 分析输入

        :param ts_code: 股票代码
        :param name: 股票名称
        :param industry: 行业
        :param financial_data: 财务数据
        :param sentiment_data: 市场情绪数据
        :return: 完整的 payload
        """
        features = self.build_with_financial(ts_code, financial_data)

        # 合并市场情绪数据（如果有）
        if sentiment_data:
            features.update(sentiment_data)

        return {
            "ts_code": ts_code,
            "name": name,
            "industry": industry,
            **features
        }


# 全局实例
_feature_builder = None

def get_feature_builder() -> LocalFeatureBuilder:
    """获取特征构建器单例"""
    global _feature_builder
    if _feature_builder is None:
        _feature_builder = LocalFeatureBuilder()
    return _feature_builder


def build_stock_features(ts_code: str, name: str = "", industry: str = "",
                        financial_data: Optional[dict] = None,
                        sentiment_data: Optional[dict] = None) -> Dict[str, Any]:
    """
    便捷函数：构建股票完整特征

    :param ts_code: 股票代码
    :param name: 股票名称
    :param industry: 行业
    :param financial_data: 财务数据
    :param sentiment_data: 市场情绪数据
    :return: 完整特征字典
    """
    builder = get_feature_builder()
    return builder.build_full_payload(ts_code, name, industry, financial_data, sentiment_data)
