"""
千问（通义千问）API 调用封装
支持批量初筛和深度分析，使用 prompts.json 管理提示词
"""

import json
import logging
import os
import time
from typing import Dict, Any, Optional

import requests

from .prompts import get_prompt, format_prompt_input

logger = logging.getLogger(__name__)


class QianwenConfig:
    """千问 API 配置"""

    API_URL = os.getenv(
        "QIANWEN_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )

    MODEL_FREE = os.getenv("QIANWEN_MODEL_FREE", "qwen-plus")
    MODEL_PLUS = os.getenv("QIANWEN_MODEL_PLUS", "qwen-plus")
    MODEL_STOCK = os.getenv("QIANWEN_MODEL_STOCK", "qwen-finance-stock-analysis-pro")

    _config_key = None
    try:
        _config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "todolist", "config.json")
        if os.path.exists(_config_path):
            with open(_config_path, "r") as _f:
                _cfg = json.load(_f)
                _config_key = _cfg.get("qianwen_api_key") or ""
    except Exception:
        pass

    API_KEY = os.getenv("QIANWEN_API_KEY", _config_key or "")

    TIMEOUT = 90
    MAX_RETRIES = 3
    RETRY_DELAY = 3


class QianwenAPI:
    """千问 API 调用封装类"""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        初始化千问 API

        :param api_key: API Key，默认从配置文件读取
        :param model: 模型名，默认 qwen-plus
        """
        self.api_key = api_key or QianwenConfig.API_KEY
        self.model = model or QianwenConfig.MODEL_PLUS
        self.api_url = QianwenConfig.API_URL

        if not self.api_key:
            raise ValueError(
                "千问 API Key 未设置，请设置环境变量 QIANWEN_API_KEY "
                "或在 todolist/config.json 中配置 qianwen_api_key"
            )

    def _call_api(self, messages: list, temperature: float = 0.0) -> Optional[str]:
        """调用千问 API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        for attempt in range(QianwenConfig.MAX_RETRIES):
            try:
                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=QianwenConfig.TIMEOUT
                )
                if response.status_code == 200:
                    data = response.json()
                    choices = data.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "")
                        return content
                else:
                    logger.warning(f"千问 API 返回错误 {response.status_code}: {response.text[:200]}")
            except Exception as e:
                logger.warning(f"千问 API 调用异常: {e}")
            if attempt < QianwenConfig.MAX_RETRIES - 1:
                time.sleep(QianwenConfig.RETRY_DELAY)
        return None

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """从响应中提取 JSON"""
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:] if lines[0].startswith("```") else lines)
            if text.endswith("```"):
                text = text[:-3]
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                return None
        return None

    def score_stock(self, stock_payload: Dict[str, Any], verbose: bool = False) -> Optional[Dict[str, Any]]:
        """
        对单只股票进行评分（阶段1初筛）

        :param stock_payload: 股票特征数据
        :param verbose: 是否打印详细信息
        :return: 评分结果
        """
        prompt_config = get_prompt("qianwen_score")
        system_prompt = prompt_config.get("system", "")

        input_text = format_prompt_input("qianwen_score", **stock_payload)

        if verbose:
            logger.info(f"[阶段1请求] 股票: {stock_payload.get('ts_code', 'unknown')}")
            logger.info(f"[阶段1输入]\n{input_text[:500]}...")

        user_message = system_prompt + "\n\n" + input_text
        messages = [{"role": "user", "content": user_message}]

        raw_response = self._call_api(messages, temperature=0.0)

        if verbose and raw_response:
            logger.info(f"[阶段1原始返回]\n{raw_response[:500]}...")

        if raw_response:
            result = self._extract_json(raw_response)
            if verbose and result:
                logger.info(f"[阶段1解析] score={result.get('score')}, action={result.get('action')}")
            return result
        return None

    def deep_analyze(self, stock_payload: Dict[str, Any], verbose: bool = False) -> Optional[Dict[str, Any]]:
        """
        对单只股票进行深度分析（阶段2）

        :param stock_payload: 股票特征数据（含阶段1结果）
        :param verbose: 是否打印详细信息
        :return: 深度分析结果
        """
        prompt_config = get_prompt("qianwen_deep")
        system_prompt = prompt_config.get("system", "")

        input_text = format_prompt_input("qianwen_deep", **stock_payload)

        if verbose:
            logger.info(f"[阶段2请求] 股票: {stock_payload.get('ts_code', 'unknown')}")
            logger.info(f"[阶段2输入]\n{input_text[:500]}...")

        user_message = system_prompt + "\n\n" + input_text
        messages = [{"role": "user", "content": user_message}]

        raw_response = self._call_api(messages, temperature=0.1)

        if verbose and raw_response:
            logger.info(f"[阶段2原始返回]\n{raw_response[:500]}...")

        if raw_response:
            result = self._extract_json(raw_response)
            if verbose and result:
                logger.info(f"[阶段2解析] invest_status={result.get('invest_status')}, buy_range={result.get('buy_range')}")
            return result
        return None

    def score_stocks_batch(self, stocks: list, delay: float = 0.5,
                          verbose: bool = False) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        批量评分股票

        :param stocks: 股票列表
        :param delay: 每次调用间隔（秒）
        :param verbose: 是否打印详细信息
        :return: {ts_code: result} 字典
        """
        results = {}
        for i, stock in enumerate(stocks, 1):
            ts_code = stock.get("ts_code", f"unknown_{i}")
            logger.info(f"千问初筛中 {i}/{len(stocks)}: {ts_code}")
            result = self.score_stock(stock, verbose=verbose)
            results[ts_code] = result
            if i < len(stocks) and result:
                time.sleep(delay)
        return results


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    try:
        api = QianwenAPI()

        test_stock = {
            "ts_code": "600036.SH",
            "name": "招商银行",
            "industry": "银行",
            "price": 35.50,
            "ma120": 32.50,
            "price_vs_ma120_pct": 9.2,
            "ret_5d": 1.5,
            "ret_20d": 6.8,
            "volume_ratio": 1.2,
            "atr14": 0.85,
            "trend_status": "多头排列",
            "pe": 5.8,
            "pb": 0.85,
            "roe": 11.2,
            "roe_dt": 10.5,
            "gross_margin": 35.5,
            "net_margin": 25.3,
            "netprofit_yoy": 15.3,
            "revenue_yoy": 8.5,
            "debt_to_assets": 72.5,
            "current_ratio": 1.5,
            "quick_ratio": 1.2,
            "eps": 1.85,
            "bps": 15.20,
            "ocf_to_or": 85.0,
            "north_net_inflow": 25000,
            "margin_balance_change": 5000,
            "limit_up_count": 80,
            "advancing_count": 2500,
        }

        print("=" * 60)
        print("千问批量初筛测试")
        print("=" * 60)
        result = api.score_stock(test_stock, verbose=True)
        print("\n初筛结果:", json.dumps(result, ensure_ascii=False, indent=2))

        print("\n" + "=" * 60)
        print("千问深度分析测试")
        print("=" * 60)

        # 添加阶段1结果到payload
        test_stock_deep = {
            **test_stock,
            "stage1_score": result.get("score", 0) if result else 0,
            "stage1_action": result.get("action", "") if result else "",
            "stage1_reason": result.get("reason", "") if result else "",
            "tech_score": result.get("tech_score", 0) if result else 0,
            "fina_score": result.get("fina_score", 0) if result else 0,
            "sentiment_score": result.get("sentiment_score", 0) if result else 0,
            "trend_score": result.get("trend_score", 0) if result else 0,
            "risk_score": result.get("risk_score", 0) if result else 0,
            "quality_score": result.get("quality_score", 0) if result else 0,
            "ma5": 34.0,
            "ma20": 34.20,
            "ma60": 33.80,
            "ps": 2.5,
            "ar_turn": 5.2,
            "inv_turn": 3.8,
            "declining_count": 1500,
        }

        result2 = api.deep_analyze(test_stock_deep, verbose=True)
        print("\n深度分析:", json.dumps(result2, ensure_ascii=False, indent=2))

    except ValueError as e:
        print(f"配置错误: {e}")
        print("\n请在 todolist/config.json 中添加 qianwen_api_key")
        print("或设置环境变量: export QIANWEN_API_KEY=your_key")
        sys.exit(1)
