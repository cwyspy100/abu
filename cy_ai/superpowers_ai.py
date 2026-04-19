"""
superpowers 两阶段 AI 分析：
1) 批量低成本打分（cheap model）
2) 前 N 只深度分析（strong model）：估值 + 投资计划
"""

import json
import logging
import os
import time
from typing import Dict, Any, Optional

import requests

logger = logging.getLogger(__name__)


def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class SuperpowersConfig:
    """从 todolist 读取模型与 key 配置。"""

    def __init__(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg_main = _load_json(os.path.join(root, "todolist", "config.json"))
        cfg_ai = _load_json(os.path.join(root, "todolist", "llm_config.json"))

        # 可在 llm_config.json 中配置默认 provider/model
        self.cheap_provider = cfg_ai.get("cheap_provider", "aihubmix")
        self.cheap_model = cfg_ai.get("cheap_model", "glm-4-flash")
        self.strong_provider = cfg_ai.get("strong_provider", "aihubmix")
        self.strong_model = cfg_ai.get("strong_model", "glm-4-flash")

        self.timeout = int(cfg_ai.get("timeout", 90))
        self.max_retries = int(cfg_ai.get("max_retries", 3))
        self.retry_delay = float(cfg_ai.get("retry_delay", 3))

        # API key：优先环境变量，其次 config.json
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", (cfg_main.get("deepseek_api_key") or "").strip())
        self.doubao_api_key = os.getenv("DOUBAO_API_KEY", (cfg_main.get("doubao_api_key") or "").strip())
        self.minimax_api_key = os.getenv("MINIMAX_API_KEY", (cfg_main.get("minimax_api_key") or "").strip())
        self.aihubmix_api_key = os.getenv("AIHUBMIX_API_KEY", (cfg_main.get("aihubmix_api_key") or "").strip())
        self.qianwen_api_key = os.getenv("QIANWEN_API_KEY", (cfg_main.get("qianwen_api_key") or "").strip())

        # endpoint 可在 llm_config.json 覆盖
        self.endpoints = {
            "deepseek": cfg_ai.get("deepseek_base_url", "https://api.deepseek.com/v1/chat/completions"),
            "doubao": cfg_ai.get("doubao_base_url", "https://ark.cn-beijing.volces.com/api/v3/chat/completions"),
            "minimax": cfg_ai.get("minimax_base_url", "https://api.minimaxi.com/v1/text/chatcompletion_v2"),
            "aihubmix": cfg_ai.get("aihubmix_base_url", "https://aihubmix.com/v1/chat/completions"),
            "qianwen": cfg_ai.get("qianwen_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"),
        }

        # 若所选 provider 未配置 key，则自动回退到 aihubmix（若可用）
        if not self.get_api_key(self.cheap_provider) and self.aihubmix_api_key:
            self.cheap_provider = "aihubmix"
            self.cheap_model = "glm-4-flash"
        if not self.get_api_key(self.strong_provider) and self.aihubmix_api_key:
            self.strong_provider = "aihubmix"
            self.strong_model = "glm-4-flash"

    def get_api_key(self, provider: str) -> str:
        if provider == "deepseek":
            return self.deepseek_api_key
        if provider == "doubao":
            return self.doubao_api_key
        if provider == "minimax":
            return self.minimax_api_key
        if provider == "aihubmix":
            return self.aihubmix_api_key
        if provider == "qianwen":
            return self.qianwen_api_key
        return ""

    def get_endpoint(self, provider: str) -> str:
        return self.endpoints.get(provider, "")


class SuperpowersAI:
    """两阶段分析客户端"""

    SCORE_PROMPT = """你是量化选股打分助手。请根据提供的结构化特征给出评分。
严格输出 JSON：
{
  "score": 0-100整数,
  "trend_score": 0-100整数,
  "risk_score": 0-100整数,
  "quality_score": 0-100整数,
  "action": "买入|观察|放弃",
  "short_reason": "不超过80字"
}
注意：只输出 JSON，不要 markdown。"""

    DEEP_PROMPT = """你是资深投资分析师，请对候选股给出估值与投资计划。
严格输出 JSON：
{
  "invest_status": "强烈推荐(10倍潜力)|值得投资|值得观察|暂不投资",
  "valuation": "低估|合理|高估",
  "tenbagger_potential_score": 0-100整数,
  "buy_range": "xx~xx",
  "sell_range": "xx~xx",
  "reason": "核心逻辑，不超过120字",
  "tenbagger_logic": "成长逻辑，不超过200字",
  "risk_points": "关键风险，不超过120字",
  "plan": {
    "position": "轻仓|中仓|重仓",
    "add_condition": "加仓条件",
    "stop_loss": "止损规则",
    "holding_period": "建议持有周期"
  }
}
注意：只输出 JSON，不要 markdown。"""

    def __init__(self):
        self.cfg = SuperpowersConfig()

    def _call_chat(self, provider: str, model: str, user_content: str, temperature: float = 0.1) -> Optional[str]:
        api_key = self.cfg.get_api_key(provider)
        url = self.cfg.get_endpoint(provider)
        if not api_key or not url:
            logger.error("模型配置缺失: provider=%s", provider)
            return None

        headers = {
            "Authorization": "Bearer %s" % api_key,
            "Content-Type": "application/json",
        }
        if provider == "minimax":
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": user_content}],
                "temperature": temperature,
            }
        else:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": user_content}],
                "temperature": temperature,
            }

        for i in range(self.cfg.max_retries):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=self.cfg.timeout)
                if resp.status_code == 200:
                    data = None
                    try:
                        data = resp.json()
                    except Exception:
                        txt = (resp.text or "").strip()
                        # 兼容某些网关返回多行 JSON，取最后一行可解析对象
                        for line in reversed([x.strip() for x in txt.splitlines() if x.strip()]):
                            if line.startswith("{") and line.endswith("}"):
                                try:
                                    data = json.loads(line)
                                    break
                                except Exception:
                                    continue
                    if not isinstance(data, dict):
                        logger.warning("LLM返回非JSON，body=%s", (resp.text or "")[:300])
                        continue
                    choices = data.get("choices") or []
                    if choices:
                        msg = choices[0].get("message", {})
                        return msg.get("content")
                    # 一些接口可能直接返回文本字段
                    if "reply" in data:
                        return data.get("reply")
                    if "output_text" in data:
                        return data.get("output_text")
                logger.warning("LLM调用失败 status=%s body=%s", resp.status_code, resp.text[:300])
            except Exception as e:
                logger.warning("LLM调用异常: %s", e)
            if i < self.cfg.max_retries - 1:
                time.sleep(self.cfg.retry_delay)
        return None

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.replace("json", "", 1).strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                return None
        return None

    def score_stock(self, stock_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        prompt = self.SCORE_PROMPT + "\n\n股票数据:\n" + json.dumps(stock_payload, ensure_ascii=False)
        text = self._call_chat(
            provider=self.cfg.cheap_provider,
            model=self.cfg.cheap_model,
            user_content=prompt,
            temperature=0.0,
        )
        return self._extract_json(text or "")

    def deep_analyze(self, stock_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        prompt = self.DEEP_PROMPT + "\n\n股票数据:\n" + json.dumps(stock_payload, ensure_ascii=False)
        text = self._call_chat(
            provider=self.cfg.strong_provider,
            model=self.cfg.strong_model,
            user_content=prompt,
            temperature=0.1,
        )
        return self._extract_json(text or "")
