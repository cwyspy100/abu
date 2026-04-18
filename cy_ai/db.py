"""
数据库连接与建表模块
提供 MySQL 连接管理和自动建表功能
"""

import os
import logging
from datetime import datetime
from typing import Optional

import pymysql
from pymysql.cursors import DictCursor

logger = logging.getLogger(__name__)


class DatabaseConfig:
    """数据库配置"""

    DEFAULT_CONFIG = {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "root1234",
        "database": "stock_analysis",
        "charset": "utf8mb4",
    }

    @classmethod
    def from_env(cls) -> dict:
        """从环境变量读取配置"""
        return {
            "host": os.getenv("DB_HOST", cls.DEFAULT_CONFIG["host"]),
            "port": int(os.getenv("DB_PORT", cls.DEFAULT_CONFIG["port"])),
            "user": os.getenv("DB_USER", cls.DEFAULT_CONFIG["user"]),
            "password": os.getenv("DB_PASSWORD", cls.DEFAULT_CONFIG["password"]),
            "database": os.getenv("DB_DATABASE", cls.DEFAULT_CONFIG["database"]),
            "charset": cls.DEFAULT_CONFIG["charset"],
        }


class Database:
    """MySQL 数据库管理类"""

    def __init__(self, config: Optional[dict] = None):
        """
        初始化数据库连接

        :param config: 数据库配置字典，为 None 时从环境变量或默认值读取
        """
        self.config = config or DatabaseConfig.from_env()
        self._connection: Optional[pymysql.Connection] = None

    def connect(self) -> pymysql.Connection:
        """建立数据库连接"""
        if self._connection is None or not self._connection.open:
            self._connection = pymysql.connect(**self.config, cursorclass=DictCursor)
        return self._connection

    def close(self):
        """关闭数据库连接"""
        if self._connection and self._connection.open:
            self._connection.close()
            self._connection = None

    def execute(self, sql: str, params: tuple = None) -> int:
        """
        执行 SQL 语句

        :param sql: SQL 语句
        :param params: 参数元组
        :return: 受影响的行数
        """
        conn = self.connect()
        with conn.cursor() as cursor:
            return cursor.execute(sql, params)

    def query_one(self, sql: str, params: tuple = None) -> Optional[dict]:
        """查询单条记录"""
        conn = self.connect()
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()

    def query_all(self, sql: str, params: tuple = None) -> list:
        """查询多条记录"""
        conn = self.connect()
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def commit(self):
        """提交事务"""
        if self._connection:
            self._connection.commit()

    def rollback(self):
        """回滚事务"""
        if self._connection:
            self._connection.rollback()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        self.close()
        return False


# 建表 SQL 语句
TABLE_SCHEMAS = {
    "stock_basic": """
        CREATE TABLE IF NOT EXISTS stock_basic (
            id INT AUTO_INCREMENT PRIMARY KEY,
            ts_code VARCHAR(20) NOT NULL COMMENT '股票代码，如 600036.SH',
            symbol VARCHAR(10) COMMENT '纯数字代码',
            name VARCHAR(30) COMMENT '股票名称',
            industry VARCHAR(50) COMMENT '行业',
            area VARCHAR(20) COMMENT '地区',
            list_date VARCHAR(20) COMMENT '上市日期',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_ts_code (ts_code)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='全量股票基础信息表'
    """,
    "stock_pool_ma120": """
        CREATE TABLE IF NOT EXISTS stock_pool_ma120 (
            id INT AUTO_INCREMENT PRIMARY KEY,
            ts_code VARCHAR(20) NOT NULL COMMENT '股票代码',
            name VARCHAR(30) COMMENT '股票名称',
            industry VARCHAR(50) COMMENT '行业',
            break_date DATE COMMENT '突破120日均线日期',
            status TINYINT DEFAULT 0 COMMENT '分析状态：0=未分析，1=已分析',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_ts_code (ts_code)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='120日均线突破股票池'
    """,
    "stock_ai_analysis": """
        CREATE TABLE IF NOT EXISTS stock_ai_analysis (
            id INT AUTO_INCREMENT PRIMARY KEY,
            ts_code VARCHAR(20) NOT NULL COMMENT '股票代码',
            name VARCHAR(30) COMMENT '股票名称',
            industry VARCHAR(50) COMMENT '行业',
            invest_status VARCHAR(30) COMMENT '投资状态：强烈推荐(10倍潜力)/值得投资/值得观察/暂不投资',
            valuation VARCHAR(10) COMMENT '估值：低估/合理/高估',
            tenbagger_potential_score INT DEFAULT 0 COMMENT '10倍潜力打分 0~100',
            buy_range VARCHAR(50) COMMENT '建议买入区间',
            sell_range VARCHAR(50) COMMENT '建议目标/卖出区间',
            reason TEXT COMMENT '核心投资逻辑',
            tenbagger_logic TEXT COMMENT '10倍潜力核心逻辑',
            risk_points TEXT COMMENT '风险点',
            analyzed_at DATETIME COMMENT '分析时间',
            is_valid TINYINT DEFAULT 1 COMMENT '是否有效',
            analysis_stage TINYINT DEFAULT 1 COMMENT '分析阶段：1=初筛，2=深度',
            stage1_score INT COMMENT '阶段1评分',
            stage1_action VARCHAR(20) COMMENT '阶段1动作：买入/观察/放弃',
            trend_score INT COMMENT '趋势评分0-100',
            risk_score INT COMMENT '风险评分0-100',
            quality_score INT COMMENT '质量评分0-100',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_ts_code (ts_code)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI分析结果表'
    """,
    "stock_watch_pool": """
        CREATE TABLE IF NOT EXISTS stock_watch_pool (
            id INT AUTO_INCREMENT PRIMARY KEY,
            ts_code VARCHAR(20) NOT NULL COMMENT '股票代码',
            name VARCHAR(50) COMMENT '股票名称',
            industry VARCHAR(50) COMMENT '行业',
            market VARCHAR(10) COMMENT '市场：A股/港股/美股',

            ai_verdict VARCHAR(20) COMMENT 'AI评级：强烈推荐/推荐/观望',
            ai_confidence INT COMMENT 'AI置信度0-100',
            ai_summary TEXT COMMENT 'AI一句话总结',

            buy_zone_low DECIMAL(10,2) COMMENT '建议买入价下限',
            buy_zone_high DECIMAL(10,2) COMMENT '建议买入价上限',
            buy_zone_ideal DECIMAL(10,2) COMMENT '理想买入价',

            sell_zone_conservative DECIMAL(10,2) COMMENT '保守目标价',
            sell_zone_aggressive DECIMAL(10,2) COMMENT '激进目标价',
            stop_loss DECIMAL(10,2) COMMENT '止损价',

            alert_config JSON COMMENT '告警配置',
            current_price DECIMAL(10,2) COMMENT '最新价格',
            price_updated_at DATETIME COMMENT '价格更新时间',
            watch_status VARCHAR(20) DEFAULT 'active' COMMENT '监控状态：active/paused/removed',

            buy_signal_sent TINYINT DEFAULT 0 COMMENT '是否已发送买入提醒',
            sell_signal_sent TINYINT DEFAULT 0 COMMENT '是否已发送卖出提醒',
            last_alert_at DATETIME COMMENT '最后提醒时间',

            added_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '入池时间',
            added_source VARCHAR(20) COMMENT '入池来源：manual/ai_analysis',
            recheck_date DATE COMMENT 'AI建议复查日期',
            analyzed_at DATETIME COMMENT 'AI分析时间',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

            UNIQUE KEY uk_ts_code (ts_code),
            INDEX idx_watch_status (watch_status),
            INDEX idx_recheck_date (recheck_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='股票监控池'
    """,
}


def init_tables(db: Database):
    """
    初始化所有数据库表

    :param db: Database 实例
    """
    logger.info("正在初始化数据库表...")

    # 先连接时不指定数据库，先创建数据库
    config = db.config.copy()
    database_name = config.pop("database", "stock_analysis")

    # 连接到 MySQL 服务器（不指定数据库）
    import pymysql
    from pymysql.cursors import DictCursor
    temp_conn = pymysql.connect(**config, cursorclass=DictCursor)

    try:
        with temp_conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {database_name}")
        temp_conn.commit()
        logger.info(f"数据库 {database_name} 创建/检查完成")
    finally:
        temp_conn.close()

    # 重新连接，指定数据库
    db.config["database"] = database_name
    db._connection = None  # 重置连接

    for table_name, schema in TABLE_SCHEMAS.items():
        try:
            db.execute(schema)
            db.commit()
            logger.info(f"表 {table_name} 创建/检查完成")
        except Exception as e:
            logger.error(f"创建表 {table_name} 失败: {e}")
            raise

    logger.info("所有数据库表初始化完成")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    db = Database()
    try:
        init_tables(db)
        print("数据库表初始化成功！")
    except Exception as e:
        print(f"初始化失败: {e}")
    finally:
        db.close()
