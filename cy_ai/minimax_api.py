"""
MiniMax API 调用封装模块
负责调用 MiniMax 大模型进行股票投资价值分析
"""

import json
import logging
import os
import time
from typing import Optional, Dict, Any

import requests

logger = logging.getLogger(__name__)


class MiniMaxConfig:
    """MiniMax API 配置"""

    # API 配置（从环境变量或配置文件读取）
    API_URL = os.getenv(
        "MINIMAX_API_URL",
        "https://api.minimaxi.com/v1/text/chatcompletion_v2",
    )
    MODEL_NAME = os.getenv("MINIMAX_MODEL", "MiniMax-M2.5")

    # 尝试从配置文件读取
    _config_key = None
    try:
        import json as _json
        _config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "todolist", "config.json")
        if os.path.exists(_config_path):
            with open(_config_path, "r") as _f:
                _cfg = _json.load(_f)
                _config_key = _cfg.get("minimax_api_key") or _cfg.get("minimax_api_key", "").strip()
    except Exception:
        pass

    API_KEY = os.getenv("MINIMAX_API_KEY", _config_key or "")

    # 请求配置
    MAX_RETRIES = 3
    RETRY_DELAY = 5  # 秒
    REQUEST_TIMEOUT = 120  # 秒


class MiniMaxAPIError(Exception):
    """MiniMax API 调用异常"""

    pass


class MiniMaxAPI:
    """MiniMax API 调用封装类"""

    # 10 倍股分析提示词
    ANALYSIS_PROMPT = """你是专业的 A 股投资分析师。你的任务是分析股票是否具备 10 倍上涨潜力。

【分析背景】
- 该股票当前已突破 120 日均线，视为趋势启动起点
- 我们需要从中挖掘未来具备 10 倍上涨潜力的成长股

【10 倍潜力股的核心特征】
1. 处于长坡厚雪的高成长赛道（政策支持、市场空间大）
2. 公司为细分行业龙头，具备竞争壁垒
3. 业绩持续增长，ROE 优秀（>15%）
4. 估值处于历史中低位或合理区间
5. 筹码集中，机构关注度提升
6. 技术形态健康，沿均线稳步攀升

【分析要求】
请严格按以下 JSON 格式输出分析结果，不要输出任何其他内容：

```json
{
    "invest_status": "强烈推荐(10倍潜力)",
    "valuation": "低估",
    "tenbagger_potential_score": 92,
    "buy_range": "XX.XX ~ XX.XX",
    "sell_range": "XX.XX ~ XX.XX",
    "reason": "核心投资逻辑（100字以内）",
    "tenbagger_logic": "10倍潜力的关键逻辑（200字以内）",
    "risk_points": "主要风险点（100字以内）"
}
```

【输出说明】
- invest_status：枚举值
  - 强烈推荐(10倍潜力)：打分 85~100 分
  - 值得投资：打分 60~84 分
  - 值得观察：打分 30~59 分
  - 暂不投资：打分 0~29 分
- valuation：枚举值，低估/合理/高估
- tenbagger_potential_score：0~100 的整数评分
- buy_range：建议买入区间，格式 "最低价 ~ 最高价"
- sell_range：建议目标/卖出区间，格式 "最低价 ~ 最高价"
- reason：核心投资逻辑，简明扼要
- tenbagger_logic：重点阐述为何有 10 倍潜力，逻辑要硬
- risk_points：明确提示主要风险

【输出格式要求】
- 必须严格 JSON 格式，不要包含 markdown 代码块标记
- 不要输出任何解释性文字
- 字段值不要包含换行符或特殊转义字符
"""

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        """
        初始化 MiniMax API

        :param api_key: API 密钥，为 None 时从环境变量读取
        :param model_name: 模型名称，为 None 时使用默认值
        """
        self.api_key = api_key or MiniMaxConfig.API_KEY
        self.model_name = model_name or MiniMaxConfig.MODEL_NAME
        self.api_url = MiniMaxConfig.API_URL

        if not self.api_key:
            raise ValueError("MiniMax API Key 未设置，请设置环境变量 MINIMAX_API_KEY 或传入 api_key 参数")

    def _build_request_payload(self, stock_info: Dict[str, Any]) -> dict:
        """
        构建请求 payload

        :param stock_info: 股票信息字典
        :return: 请求 payload
        """
        ts_code = stock_info.get("ts_code", "")
        name = stock_info.get("name", "")
        industry = stock_info.get("industry", "")
        break_date = stock_info.get("break_date", "")

        # 构建用户消息
        user_message = f"""请分析以下股票的投资价值：

股票代码：{ts_code}
股票名称：{name}
所属行业：{industry}
突破120日均线日期：{break_date}

{self.ANALYSIS_PROMPT}"""

        return {
            "model": self.model_name,
            "messages": [
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.3,  # 较低温度，保持输出稳定性
        }

    def _parse_response(self, response_text: str) -> Optional[Dict[str, Any]]:
        """
        解析 API 响应，提取 JSON 结果

        :param response_text: API 响应文本
        :return: 解析后的字典，解析失败返回 None
        """
        import re

        # 尝试提取 JSON 块
        json_patterns = [
            r"```json\s*(\{.*?\})\s*```",
            r"```\s*(\{.*?\})\s*```",
            r"\{[^{}]*\"invest_status\"[^{}]*\}",
            r"(\{.*\})",
        ]

        for pattern in json_patterns:
            matches = re.findall(pattern, response_text, re.DOTALL)
            for match in matches:
                try:
                    result = json.loads(match)
                    # 验证必要字段
                    if "invest_status" in result and "tenbagger_potential_score" in result:
                        # 确保 tenbagger_potential_score 是整数
                        score = result.get("tenbagger_potential_score")
                        if isinstance(score, str):
                            # 尝试提取数字
                            score_match = re.search(r"\d+", score)
                            if score_match:
                                result["tenbagger_potential_score"] = int(score_match.group())
                            else:
                                result["tenbagger_potential_score"] = 0
                        elif not isinstance(score, int):
                            result["tenbagger_potential_score"] = 0

                        return result
                except (json.JSONDecodeError, re.error):
                    continue

        return None

    def analyze_stock(self, stock_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        分析单只股票的投资价值

        :param stock_info: 股票信息，包含 ts_code, name, industry, break_date
        :return: 分析结果字典，失败返回 None
        """
        if not self.api_key:
            logger.error("MiniMax API Key 未设置")
            return None

        ts_code = stock_info.get("ts_code", "unknown")
        payload = self._build_request_payload(stock_info)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(MiniMaxConfig.MAX_RETRIES):
            try:
                logger.info(f"正在分析股票 {ts_code}（第 {attempt + 1} 次尝试）...")

                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=MiniMaxConfig.REQUEST_TIMEOUT,
                )

                if response.status_code == 200:
                    result = response.json()

                    # 提取 assistant 的回复
                    choices = result.get("choices", [])
                    if choices and len(choices) > 0:
                        message = choices[0].get("message", {})
                        content = message.get("content", "")

                        # 解析 JSON 结果
                        parsed = self._parse_response(content)

                        if parsed:
                            logger.info(
                                f"股票 {ts_code} 分析完成，评分: {parsed.get('tenbagger_potential_score', 0)}"
                            )
                            return parsed
                        else:
                            logger.warning(f"股票 {ts_code} 响应解析失败: {content[:200]}")
                else:
                    logger.warning(
                        f"API 返回错误状态码 {response.status_code}: {response.text[:200]}"
                    )

            except requests.exceptions.Timeout:
                logger.warning(f"股票 {ts_code} API 请求超时")
            except requests.exceptions.RequestException as e:
                logger.warning(f"股票 {ts_code} API 请求异常: {e}")
            except Exception as e:
                logger.error(f"股票 {ts_code} 分析过程异常: {e}")

            # 重试前等待
            if attempt < MiniMaxConfig.MAX_RETRIES - 1:
                time.sleep(MiniMaxConfig.RETRY_DELAY)

        logger.error(f"股票 {ts_code} 分析失败，已达到最大重试次数")
        return None

    def analyze_stocks_batch(
        self, stocks: list, delay_between: float = 3.0
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        批量分析股票

        :param stocks: 股票信息列表
        :param delay_between: 每次分析间隔（秒），防止 API 限流
        :return: {ts_code: analysis_result} 字典
        """
        results = {}

        for i, stock in enumerate(stocks, 1):
            ts_code = stock.get("ts_code", f"unknown_{i}")
            logger.info(f"正在分析 {i}/{len(stocks)}: {ts_code}")

            result = self.analyze_stock(stock)
            results[ts_code] = result

            # 间隔一段时间后再发送下一个请求
            if i < len(stocks) and result is not None:
                time.sleep(delay_between)

        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # 测试 API 调用（需要配置 API Key）
    api = MiniMaxAPI()

    test_stock = {
        "ts_code": "600036.SH",
        "name": "招商银行",
        "industry": "银行",
        "break_date": "2024-01-15",
    }

    result = api.analyze_stock(test_stock)
    if result:
        print("分析结果:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("分析失败")
