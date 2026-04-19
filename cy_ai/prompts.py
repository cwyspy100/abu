"""
提示词加载器
从 prompts.json 加载所有提示词配置
"""

import json
import logging
import os
from typing import Dict, Any

logger = logging.getLogger(__name__)


class PromptLoader:
    """提示词加载器单例"""

    _instance = None
    _prompts: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_prompts()
        return cls._instance

    def _load_prompts(self):
        """从 prompts.json 加载提示词"""
        prompts_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts.json")

        if not os.path.exists(prompts_path):
            logger.error(f"提示词配置文件不存在: {prompts_path}")
            return

        try:
            with open(prompts_path, "r", encoding="utf-8") as f:
                self._prompts = json.load(f)
            logger.info(f"成功加载 {len(self._prompts)} 个提示词配置")
        except Exception as e:
            logger.error(f"加载提示词失败: {e}")

    def get(self, name: str) -> Dict[str, Any]:
        """获取指定提示词配置"""
        if name not in self._prompts:
            logger.warning(f"提示词 '{name}' 不存在")
            return {}
        return self._prompts.get(name, {})

    def get_system(self, name: str) -> str:
        """获取提示词 system 部分"""
        prompt = self.get(name)
        return prompt.get("system", "")

    def get_input_template(self, name: str) -> str:
        """获取提示词输入模板"""
        prompt = self.get(name)
        return prompt.get("input_template", "")

    def get_output_schema(self, name: str) -> Dict[str, str]:
        """获取提示词输出 schema"""
        prompt = self.get(name)
        return prompt.get("output_schema", {})

    def format_input(self, name: str, **kwargs) -> str:
        """
        格式化输入模板

        Usage:
            loader.format_input("qianwen_score",
                                ts_code="600036",
                                name="招商银行",
                                pe=5.8)
        """
        template = self.get_input_template(name)
        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.error(f"格式化提示词 '{name}' 失败，缺少参数: {e}")
            return template

    def reload(self):
        """重新加载提示词"""
        self._prompts = {}
        self._load_prompts()


# 全局单例
_loader = None

def get_loader() -> PromptLoader:
    """获取提示词加载器单例"""
    global _loader
    if _loader is None:
        _loader = PromptLoader()
    return _loader


def get_prompt(name: str) -> Dict[str, Any]:
    """获取指定提示词"""
    return get_loader().get(name)


def get_system_prompt(name: str) -> str:
    """获取 system prompt"""
    return get_loader().get_system(name)


def format_prompt_input(name: str, **kwargs) -> str:
    """格式化输入"""
    return get_loader().format_input(name, **kwargs)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    loader = get_loader()

    # 测试获取
    score_prompt = loader.get("qianwen_score")
    print(f"加载的提示词: {list(loader._prompts.keys())}")
    print(f"qianwen_score system 长度: {len(score_prompt.get('system', ''))}")

    # 测试格式化
    input_text = loader.format_input(
        "qianwen_score",
        ts_code="600036",
        name="招商银行",
        industry="银行",
        price=35.50,
        ma120=32.50,
        pe=5.8,
        roe=11.2
    )
    print("\n格式化后的输入:")
    print(input_text[:500])
