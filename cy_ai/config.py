"""
统一配置加载模块
从 todolist/config.json 读取所有配置
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class Config:
    """统一配置类"""

    _instance: Optional['Config'] = None
    _config: dict = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        """从配置文件加载配置"""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "todolist",
            "config.json"
        )

        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
                logger.info(f"配置加载成功: {config_path}")
            except Exception as e:
                logger.error(f"配置加载失败: {e}")
                self._config = {}
        else:
            logger.warning(f"配置文件不存在: {config_path}")
            self._config = {}

    def get(self, key: str, default: str = "") -> str:
        """
        获取配置值
        优先级：环境变量 > 配置文件 > 默认值
        """
        # 先尝试环境变量
        env_value = os.getenv(key.upper())
        if env_value:
            return env_value

        # 再尝试配置文件
        config_key = key.lower()
        if config_key in self._config:
            value = self._config[config_key]
            if value:
                return str(value)

        return default

    @property
    def aihubmix_api_key(self) -> str:
        return self.get("aihubmix_api_key", "")

    @property
    def aihubmix_model(self) -> str:
        return self.get("aihubmix_model", "glm-4-flash")

    @property
    def aihubmix_base_url(self) -> str:
        return self.get("aihubmix_base_url", "https://aihubmix.com/v1/chat/completions")

    @property
    def minimax_api_key(self) -> str:
        return self.get("minimax_api_key", "")

    @property
    def minimax_api_url(self) -> str:
        return self.get("minimax_api_url", "https://api.minimaxi.com/v1/text/chatcompletion_v2")

    @property
    def minimax_model(self) -> str:
        return self.get("minimax_model", "MiniMax-M2.5")

    @property
    def deepseek_api_key(self) -> str:
        return self.get("deepseek_api_key", "")

    @property
    def doubao_api_key(self) -> str:
        return self.get("doubao_api_key", "")

    @property
    def feishu_webhook_url(self) -> str:
        return self.get("feishu_webhook_url", "")

    @property
    def ma120_pool_csv(self) -> str:
        return self.get("ma120_pool_csv", "")

    @property
    def monitor_interval_minutes(self) -> int:
        try:
            return int(self.get("monitor_interval_minutes", "30"))
        except ValueError:
            return 30


# 全局配置实例
_config = None


def get_config() -> Config:
    """获取配置单例"""
    global _config
    if _config is None:
        _config = Config()
    return _config
