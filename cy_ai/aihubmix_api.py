"""
AIHubMix API 调用封装
用于低成本批量股票初筛
"""

import json
import logging
import os
import time
from typing import Dict, Any, Optional

import requests

logger = logging.getLogger(__name__)


class AIHubMixConfig:
    """AIHubMix API 配置"""

    API_URL = os.getenv(
        "AIHUBMIX_BASE_URL",
        "https://aihubmix.com/v1/chat/completions"
    )
    MODEL = os.getenv("AIHUBMIX_MODEL", "glm-4-flash")

    # 尝试从配置文件读取
    _config_key = None
    try:
        _config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "todolist", "config.json")
        if os.path.exists(_config_path):
            with open(_config_path, "r") as _f:
                _cfg = json.load(_f)
                _config_key = _cfg.get("aihubmix_api_key") or _cfg.get("aihubmix_api_key", "").strip()
    except Exception:
        pass

    API_KEY = os.getenv("AIHUBMIX_API_KEY", _config_key or "")

    TIMEOUT = 60
    MAX_RETRIES = 3
    RETRY_DELAY = 3


class AIHubMixAPI:
    """AIHubMix API 调用封装类"""

    SCORE_PROMPT = """你是量化选股打分助手。请根据股票特征数据给出评分。

评分维度：
- 趋势得分(0-100)：均线多头排列、趋势向上、成交量配合
- 风险得分(0-100)：估值高低、基本面风险、技术面风险
- 质量得分(0-100)：ROE、盈利能力、成长性

最终动作：买入/观察/放弃

严格输出JSON（不要markdown，不要任何其他内容）：
{
  "score": 0-100整数,
  "trend_score": 0-100整数,
  "risk_score": 0-100整数,
  "quality_score": 0-100整数,
  "action": "买入|观察|放弃",
  "short_reason": "不超过60字"
}"""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or AIHubMixConfig.API_KEY
        self.model = model or AIHubMixConfig.MODEL
        self.api_url = AIHubMixConfig.API_URL

        if not self.api_key:
            raise ValueError("AIHubMix API Key 未设置，请设置环境变量 AIHUBMIX_API_KEY 或在 todolist/config.json 中配置 aihubmix_api_key")

    def _call_api(self, messages: list, temperature: float = 0.0) -> Optional[str]:
        """调用 AIHubMix API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        for attempt in range(AIHubMixConfig.MAX_RETRIES):
            try:
                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=AIHubMixConfig.TIMEOUT
                )
                if response.status_code == 200:
                    data = response.json()
                    choices = data.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "")
                        return content
                else:
                    logger.warning(f"API 返回错误 {response.status_code}: {response.text[:200]}")
            except Exception as e:
                logger.warning(f"API 调用异常: {e}")
            if attempt < AIHubMixConfig.MAX_RETRIES - 1:
                time.sleep(AIHubMixConfig.RETRY_DELAY)
        return None

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """从响应中提取 JSON"""
        if not text:
            return None
        text = text.strip()
        # 移除 markdown 代码块
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:] if lines[0].startswith("```") else lines)
            if text.endswith("```"):
                text = text[:-3]
        # 找 JSON 对象
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                return None
        return None

    def score_stock(self, stock_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        对单只股票进行评分

        :param stock_payload: 股票特征数据
        :return: 评分结果
        """
        user_message = self.SCORE_PROMPT + "\n\n股票数据:\n" + json.dumps(stock_payload, ensure_ascii=False)
        messages = [{"role": "user", "content": user_message}]

        content = self._call_api(messages, temperature=0.0)
        if content:
            return self._extract_json(content)
        return None

    def score_stocks_batch(self, stocks: list, delay: float = 1.0) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        批量评分股票

        :param stocks: 股票列表
        :param delay: 每次调用间隔（秒）
        :return: {ts_code: result} 字典
        """
        results = {}
        for i, stock in enumerate(stocks, 1):
            ts_code = stock.get("ts_code", f"unknown_{i}")
            logger.info(f"评分中 {i}/{len(stocks)}: {ts_code}")
            result = self.score_stock(stock)
            results[ts_code] = result
            if i < len(stocks) and result:
                time.sleep(delay)
        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    api = AIHubMixAPI()
    test_stock = {
        "ts_code": "600036",
        "name": "招商银行",
        "industry": "银行",
        "price": 35.50,
        "ma20": 34.20,
        "ma60": 33.80,
        "ma120": 32.50,
        "price_vs_ma120": "+9.2%",
        "ret_5d": 2.3,
        "ret_20d": 8.5,
        "volume_ratio": 1.35,
        "pe": 5.8,
        "pb": 0.65,
        "roe": 11.2,
    }
    result = api.score_stock(test_stock)
    print("评分结果:", json.dumps(result, ensure_ascii=False, indent=2))
