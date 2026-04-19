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

    SCORE_PROMPT = """你是严格的量化选股筛选器。你的任务是从候选股票中筛选出真正值得投资的标的。

## 核心原则
- 你是悲观主义者，倾向于说"不"
- 只有当股票明确满足所有好条件且没有一票否决问题时，才推荐"买入"
- 均线突破只是选股起点，不代表值得买入

## 评分标准

### 买入条件（必须同时满足）
1. 价格在MA120均线上方，乖离率 < 20%
2. 趋势向上：近20日涨幅 > 5%
3. 估值合理：PE < 行业平均的1.5倍
4. 基本面：ROE > 10% 或 净利润增速 > 15%

### 一票否决条件（满足任一即放弃）
1. PE > 行业平均2倍（估值泡沫）
2. 价格乖离MA120 > 30%（追高风险）
3. 近5日涨幅 > 20%（短期涨幅过大）
4. 净利润连续2季度下滑
5. 资产负债率 > 80%
6. 量比 > 3倍（异动风险）
7. ROE < 5%（盈利质量差）

## 评分规则
- 总分0-100，只给严格符合条件的股票打60分以上
- 大多数股票应该打30-50分
- 只有基本面优秀且估值合理的才给70+
- 满足一票否决的直接打10分以下

## 输出格式（严格JSON，不要markdown，不要任何其他内容）
{
  "score": 0-100整数,
  "action": "买入(60分+)|观察(30-59)|放弃(30分以下)",
  "trend_score": 0-100整数,
  "risk_score": 0-100整数,
  "quality_score": 0-100整数,
  "reason": "评分理由，不超过80字",
  "reject_reason": "如果放弃，说明具体哪个否决条件，不超过40字"
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
