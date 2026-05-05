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
            stock_type VARCHAR(20) COMMENT '股票类别：A股/港股/美股',
            area VARCHAR(20) COMMENT '地区',
            list_date VARCHAR(20) COMMENT '上市日期',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_ts_code (ts_code),
            INDEX idx_stock_type (stock_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='全量股票基础信息表'
    """,
    "stock_pool_ma120": """
        CREATE TABLE IF NOT EXISTS stock_pool_ma120 (
            id INT AUTO_INCREMENT PRIMARY KEY,
            ts_code VARCHAR(20) NOT NULL COMMENT '股票代码',
            name VARCHAR(30) COMMENT '股票名称',
            industry VARCHAR(50) COMMENT '行业',
            market VARCHAR(10) DEFAULT 'A股' COMMENT '市场：A股/港股/美股',
            break_date DATE COMMENT '突破120日均线日期',
            status TINYINT DEFAULT 1 COMMENT '有效状态：0=失效，1=有效',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_ts_code_market (ts_code, market),
            INDEX idx_market (market),
            INDEX idx_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='120日均线突破股票池'
    """,
    "stock_ai_analysis": """
        CREATE TABLE IF NOT EXISTS stock_ai_analysis (
            id INT AUTO_INCREMENT PRIMARY KEY,
            ts_code VARCHAR(20) NOT NULL COMMENT '股票代码',
            name VARCHAR(50) COMMENT '股票名称',
            source_provider VARCHAR(20) DEFAULT 'qianwen' COMMENT 'AI来源:qianwen|aihubmix|minimax',
            source_model VARCHAR(50) COMMENT '具体模型名',
            analysis_stage VARCHAR(20) DEFAULT 'stage1' COMMENT '分析阶段:stage1初筛|stage2深度',
            raw_request TEXT COMMENT '原始请求JSON',
            raw_response TEXT COMMENT '原始响应JSON',
            stage1_score DECIMAL(5,2) COMMENT '阶段1评分0-100',
            stage1_action VARCHAR(20) COMMENT '阶段1动作:买入|观察|放弃',
            stage1_reason VARCHAR(200) COMMENT '阶段1理由',
            tech_score DECIMAL(5,2) COMMENT '技术面得分0-100',
            fina_score DECIMAL(5,2) COMMENT '财务面得分0-100',
            sentiment_score DECIMAL(5,2) COMMENT '市场情绪得分0-100',
            trend_score DECIMAL(5,2) COMMENT '趋势得分0-100',
            risk_score DECIMAL(5,2) COMMENT '风险得分0-100',
            quality_score DECIMAL(5,2) COMMENT '质量得分0-100',
            invest_status VARCHAR(50) COMMENT '投资状态:强烈推荐|值得投资|值得观察|暂不投资',
            valuation VARCHAR(20) COMMENT '估值:低估|合理|高估',
            tenbagger_potential_score DECIMAL(5,2) COMMENT '10倍股潜力评分0-100',
            buy_range VARCHAR(50) COMMENT '买入区间',
            sell_range VARCHAR(50) COMMENT '卖出区间',
            stop_loss DECIMAL(10,2) COMMENT '止损价',
            position VARCHAR(20) COMMENT '仓位:轻仓|中仓|重仓',
            holding_period VARCHAR(50) COMMENT '持有周期',
            reason VARCHAR(500) COMMENT '核心投资逻辑',
            tenbagger_logic VARCHAR(500) COMMENT '成长逻辑',
            risk_points VARCHAR(500) COMMENT '风险提示',
            industry_outlook VARCHAR(200) COMMENT '行业展望',
            competitiveness VARCHAR(200) COMMENT '竞争优势',
            action VARCHAR(20) DEFAULT '待分析' COMMENT '最终动作:买入|观察|放弃|待分析',
            reject_reason VARCHAR(200) COMMENT '放弃原因',
            final_score DECIMAL(5,2) COMMENT '综合评分0-100',
            analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '分析时间',
            is_latest TINYINT DEFAULT 1 COMMENT '是否最新分析:1是|0历史',
            UNIQUE KEY uk_code_analyzed (ts_code, analyzed_at),
            INDEX idx_ts_code (ts_code),
            INDEX idx_final_score (final_score),
            INDEX idx_action (action),
            INDEX idx_analyzed_at (analyzed_at),
            INDEX idx_is_latest (is_latest)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI股票分析结果'
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
    "stock_fina_indicator": """
        CREATE TABLE IF NOT EXISTS stock_fina_indicator (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            ts_code VARCHAR(20) NOT NULL COMMENT '股票代码',
            ann_date DATE COMMENT '公告日期',
            end_date DATE COMMENT '报告期',
            pe DECIMAL(10,2) COMMENT '市盈率',
            pb DECIMAL(10,2) COMMENT '市净率',
            ps DECIMAL(10,2) COMMENT '市销率',
            roe DECIMAL(10,2) COMMENT '净资产收益率%',
            roe_dt DECIMAL(10,2) COMMENT '扣非ROE%',
            gross_margin DECIMAL(10,2) COMMENT '毛利率%',
            net_margin DECIMAL(10,2) COMMENT '净利率%',
            netprofit_yoy DECIMAL(10,2) COMMENT '净利润增速%',
            revenue_yoy DECIMAL(10,2) COMMENT '营收增速%',
            op_yoy DECIMAL(10,2) COMMENT '营业利润增速%',
            debt_to_assets DECIMAL(10,2) COMMENT '资产负债率%',
            current_ratio DECIMAL(10,2) COMMENT '流动比率',
            quick_ratio DECIMAL(10,2) COMMENT '速动比率',
            eps DECIMAL(10,4) COMMENT '每股收益',
            bps DECIMAL(10,4) COMMENT '每股净资产',
            ocfps DECIMAL(10,4) COMMENT '每股经营现金流',
            ar_turn DECIMAL(10,2) COMMENT '应收账款周转率',
            inv_turn DECIMAL(10,2) COMMENT '存货周转率',
            assets_turn DECIMAL(10,2) COMMENT '资产周转率',
            ocf_to_or DECIMAL(10,2) COMMENT '经营现金流/营收%',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_code_date (ts_code, end_date),
            INDEX idx_ts_code (ts_code),
            INDEX idx_end_date (end_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='财务指标数据'
    """,
    "market_sentiment": """
        CREATE TABLE IF NOT EXISTS market_sentiment (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            trade_date DATE NOT NULL COMMENT '交易日期',
            north_net_inflow DECIMAL(20,2) COMMENT '北向资金净流入(万)',
            south_net_inflow DECIMAL(20,2) COMMENT '南向资金净流入(万)',
            main_net_inflow DECIMAL(20,2) COMMENT '主力净流入(万)',
            margin_balance DECIMAL(20,2) COMMENT '融资余额(万)',
            margin_balance_change DECIMAL(20,2) COMMENT '融资余额变化(万)',
            short_balance DECIMAL(20,2) COMMENT '融券余额(万)',
            limit_up_count INT COMMENT '涨停家数',
            limit_down_count INT COMMENT '跌停家数',
            advancing_count INT COMMENT '上涨家数',
            declining_count INT COMMENT '下跌家数',
            amplitude DECIMAL(10,2) COMMENT '市场振幅%',
            turnover_rate DECIMAL(10,2) COMMENT '市场换手率%',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_trade_date (trade_date),
            INDEX idx_trade_date (trade_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='市场情绪数据'
    """,
    "stock_analysis_task": """
        CREATE TABLE IF NOT EXISTS stock_analysis_task (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            ts_code VARCHAR(20) NOT NULL COMMENT '股票代码',
            name VARCHAR(50) COMMENT '股票名称',
            status VARCHAR(20) DEFAULT 'pending' COMMENT '状态:pending|running|completed|failed|skipped',
            error_message TEXT COMMENT '错误信息',
            skip_if_analyzed TINYINT DEFAULT 1 COMMENT '已分析过则跳过:1是|0否',
            last_analysis_date DATE COMMENT '上次分析日期',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            completed_at TIMESTAMP NULL COMMENT '完成时间',
            UNIQUE KEY uk_ts_code (ts_code),
            INDEX idx_status (status),
            INDEX idx_created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分析任务记录'
    """,
    "stock_cn_a_screen": """
        CREATE TABLE IF NOT EXISTS stock_cn_a_screen (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            asof_date DATE NOT NULL COMMENT '快照归属日(取最近周五)',
            ts_code VARCHAR(16) NOT NULL COMMENT '规范代码如 688808.SH',
            screen_rank DECIMAL(14,4) COMMENT '原表排序列',
            name VARCHAR(80) COMMENT '名称',
            pct_chg DECIMAL(14,6) COMMENT '涨幅',
            last_price DECIMAL(16,4) COMMENT '现价',
            change_amt DECIMAL(16,4) COMMENT '涨跌',
            bid_price DECIMAL(16,4) COMMENT '买价',
            ask_price DECIMAL(16,4) COMMENT '卖价',
            volume_hands BIGINT COMMENT '总手',
            amount DECIMAL(22,2) COMMENT '总金额',
            last_vol VARCHAR(32) COMMENT '现手',
            speed_1m DECIMAL(14,6) COMMENT '1分钟涨速',
            body_pct_chg DECIMAL(14,6) COMMENT '实体涨幅',
            vs_avg_pct DECIMAL(14,4) COMMENT '现均差%',
            turnover_rate DECIMAL(14,6) COMMENT '换手',
            bid_ask_ratio_pct DECIMAL(14,4) COMMENT '委比%',
            total_mv DECIMAL(22,2) COMMENT '总市值',
            float_mv DECIMAL(22,2) COMMENT '流通市值',
            float_ratio DECIMAL(14,6) COMMENT '流通比例',
            speed_4m DECIMAL(14,6) COMMENT '4分钟涨速',
            deviate_day VARCHAR(32) COMMENT '当日偏离值',
            deviate_abnormal VARCHAR(32) COMMENT '异动偏离值',
            deviate_10d VARCHAR(32) COMMENT '10日内偏离值',
            deviate_30d VARCHAR(32) COMMENT '30日内偏离值',
            abnormal_count_10d VARCHAR(32) COMMENT '10日异动次数',
            inner_vol BIGINT COMMENT '内盘',
            outer_vol BIGINT COMMENT '外盘',
            inner_outer_ratio DECIMAL(14,4) COMMENT '内外比',
            remark VARCHAR(32) COMMENT '备注',
            bad_news VARCHAR(32) COMMENT '利空',
            good_news VARCHAR(32) COMMENT '利好',
            main_net_ratio DECIMAL(14,4) COMMENT '主力净量',
            volume_ratio DECIMAL(14,4) COMMENT '量比',
            pe_ttm DECIMAL(16,4) COMMENT 'TTM市盈率',
            net_profit_raw VARCHAR(128) COMMENT '净利润(原文)',
            pb DECIMAL(16,4) COMMENT '市净率',
            eps DECIMAL(16,4) COMMENT '每股盈利',
            sub_industry VARCHAR(80) COMMENT '细分行业',
            industry VARCHAR(80) COMMENT '所属行业',
            pre_close DECIMAL(16,4) COMMENT '昨收',
            open_price DECIMAL(16,4) COMMENT '开盘',
            open_pct_chg DECIMAL(14,6) COMMENT '开盘涨幅',
            call_auction_turnover DECIMAL(14,6) COMMENT '竞价换手',
            high DECIMAL(16,4) COMMENT '最高',
            low DECIMAL(16,4) COMMENT '最低',
            pct_chg_5d VARCHAR(32) COMMENT '5日涨幅',
            pct_chg_10d VARCHAR(32) COMMENT '10日涨幅',
            pct_chg_20d VARCHAR(32) COMMENT '20日涨幅',
            ytd_pct_chg DECIMAL(14,6) COMMENT '年初至今',
            amplitude DECIMAL(14,6) COMMENT '振幅',
            bid_vol BIGINT COMMENT '买量',
            ask_vol BIGINT COMMENT '卖量',
            trade_count BIGINT COMMENT '笔数',
            contribution VARCHAR(64) COMMENT '贡献度',
            inst_flow VARCHAR(64) COMMENT '机构动向',
            abnormal_type VARCHAR(64) COMMENT '异动类型',
            total_shares BIGINT COMMENT '总股本',
            float_shares BIGINT COMMENT '流通股本',
            total_profit_raw VARCHAR(128) COMMENT '利润总额(原文)',
            net_profit_yoy VARCHAR(64) COMMENT '净利润增长率',
            bps DECIMAL(16,4) COMMENT '每股净资产',
            golden_cross_cnt INT COMMENT '金叉个数',
            retail_count_raw VARCHAR(64) COMMENT '散户数量(原文)',
            list_date DATE COMMENT '上市日期',
            source_file VARCHAR(255) COMMENT '来源xlsx路径',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_asof_ts (asof_date, ts_code),
            INDEX idx_asof_date (asof_date),
            INDEX idx_ts_code (ts_code),
            INDEX idx_industry (industry)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='A股行情/筛选Excel快照'
    """,
    "stock_hk_screen": """
        CREATE TABLE IF NOT EXISTS stock_hk_screen (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            asof_date DATE NOT NULL COMMENT '快照归属日(取最近周五)',
            ts_code VARCHAR(16) NOT NULL COMMENT '规范代码如 00499.HK',
            name VARCHAR(80) COMMENT '名称',
            screen_rank VARCHAR(32) COMMENT '原表排序列',
            pct_chg DECIMAL(14,6) COMMENT '涨幅',
            last_price DECIMAL(18,6) COMMENT '现价',
            change_amt DECIMAL(18,6) COMMENT '涨跌',
            volume_total BIGINT COMMENT '总量',
            amount DECIMAL(22,2) COMMENT '总金额',
            volume_ratio DECIMAL(14,4) COMMENT '量比',
            turnover_rate DECIMAL(14,6) COMMENT '换手',
            total_mv DECIMAL(22,2) COMMENT '总市值',
            float_mv DECIMAL(22,2) COMMENT '流通市值',
            net_profit_raw VARCHAR(128) COMMENT '净利润(原文)',
            pe_ttm DECIMAL(16,4) COMMENT 'TTM市盈率',
            pb DECIMAL(16,4) COMMENT '市净率',
            hk_connect_shares BIGINT COMMENT '港股通持股量',
            pct_h_share DECIMAL(14,6) COMMENT '占H股%',
            industry VARCHAR(80) COMMENT '所属行业',
            open_price DECIMAL(18,6) COMMENT '开盘',
            high DECIMAL(18,6) COMMENT '最高',
            low DECIMAL(18,6) COMMENT '最低',
            speed_1m DECIMAL(14,6) COMMENT '1分钟涨速',
            speed_5m DECIMAL(14,6) COMMENT '5分钟涨速',
            pre_close DECIMAL(18,6) COMMENT '昨收',
            source_file VARCHAR(255) COMMENT '来源xlsx路径',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_asof_ts (asof_date, ts_code),
            INDEX idx_asof_date (asof_date),
            INDEX idx_ts_code (ts_code),
            INDEX idx_industry (industry)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='港股行情/筛选Excel快照'
    """,
    "stock_us_screen": """
        CREATE TABLE IF NOT EXISTS stock_us_screen (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            asof_date DATE NOT NULL COMMENT '快照归属日(取最近周五)',
            ts_code VARCHAR(32) NOT NULL COMMENT '规范代码如 MXL.US',
            name VARCHAR(120) COMMENT '名称',
            pct_chg DECIMAL(14,6) COMMENT '涨幅',
            last_price DECIMAL(18,6) COMMENT '现价',
            change_amt DECIMAL(18,6) COMMENT '涨跌',
            pre_market_price DECIMAL(18,6) COMMENT '盘前价',
            pre_market_pct_chg DECIMAL(14,6) COMMENT '盘前涨幅',
            pre_market_change DECIMAL(18,6) COMMENT '盘前涨跌',
            post_market_price DECIMAL(18,6) COMMENT '盘后价',
            post_market_pct_chg DECIMAL(14,6) COMMENT '盘后涨幅',
            post_market_change DECIMAL(18,6) COMMENT '盘后涨跌',
            turnover_rate DECIMAL(14,6) COMMENT '换手',
            amplitude DECIMAL(14,6) COMMENT '振幅',
            volume_total BIGINT COMMENT '总量',
            amount_usd DECIMAL(22,2) COMMENT '金额美元',
            total_mv_usd DECIMAL(22,2) COMMENT '总市值美元',
            eps DECIMAL(18,6) COMMENT '每股收益',
            pe_ttm DECIMAL(16,4) COMMENT 'TTM市盈率',
            pb DECIMAL(16,4) COMMENT '市净率',
            net_profit_raw VARCHAR(128) COMMENT '净利润(原文)',
            bps DECIMAL(18,6) COMMENT '每股净资产',
            inst_hold_pct DECIMAL(14,6) COMMENT '机构持仓%',
            open_price DECIMAL(18,6) COMMENT '开盘',
            pre_close DECIMAL(18,6) COMMENT '昨收',
            high DECIMAL(18,6) COMMENT '最高',
            low DECIMAL(18,6) COMMENT '最低',
            high_52w DECIMAL(18,6) COMMENT '52周最高',
            low_52w DECIMAL(18,6) COMMENT '52周最低',
            industry VARCHAR(120) COMMENT '所属行业',
            source_file VARCHAR(255) COMMENT '来源xlsx路径',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_asof_ts (asof_date, ts_code),
            INDEX idx_asof_date (asof_date),
            INDEX idx_ts_code (ts_code),
            INDEX idx_industry (industry)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='美股行情/筛选Excel快照'
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

    # 兼容历史库：补充 stock_pool_ma120.market 与状态索引
    try:
        col = db.query_one(
            """
            SELECT 1
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'stock_pool_ma120'
              AND COLUMN_NAME = 'market'
            LIMIT 1
            """,
            (database_name,),
        )
        if not col:
            db.execute(
                """
                ALTER TABLE stock_pool_ma120
                ADD COLUMN market VARCHAR(10) DEFAULT 'A股' COMMENT '市场：A股/港股/美股'
                """
            )

        idx_market = db.query_one(
            """
            SELECT 1
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'stock_pool_ma120'
              AND INDEX_NAME = 'idx_market'
            LIMIT 1
            """,
            (database_name,),
        )
        if not idx_market:
            db.execute("CREATE INDEX idx_market ON stock_pool_ma120 (market)")

        idx_status = db.query_one(
            """
            SELECT 1
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'stock_pool_ma120'
              AND INDEX_NAME = 'idx_status'
            LIMIT 1
            """,
            (database_name,),
        )
        if not idx_status:
            db.execute("CREATE INDEX idx_status ON stock_pool_ma120 (status)")

        # 唯一键从 ts_code 升级为 (ts_code, market)
        uk_old = db.query_one(
            """
            SELECT 1
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'stock_pool_ma120'
              AND INDEX_NAME = 'uk_ts_code'
            LIMIT 1
            """,
            (database_name,),
        )
        if uk_old:
            db.execute("ALTER TABLE stock_pool_ma120 DROP INDEX uk_ts_code")

        uk_new = db.query_one(
            """
            SELECT 1
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'stock_pool_ma120'
              AND INDEX_NAME = 'uk_ts_code_market'
            LIMIT 1
            """,
            (database_name,),
        )
        if not uk_new:
            db.execute("ALTER TABLE stock_pool_ma120 ADD UNIQUE KEY uk_ts_code_market (ts_code, market)")

        db.commit()
    except Exception as e:
        logger.warning(f"stock_pool_ma120 兼容迁移跳过（可能已存在）: {e}")

    # 兼容历史库：补充 stock_basic.stock_type
    try:
        col = db.query_one(
            """
            SELECT 1
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'stock_basic'
              AND COLUMN_NAME = 'stock_type'
            LIMIT 1
            """,
            (database_name,),
        )
        if not col:
            db.execute(
                """
                ALTER TABLE stock_basic
                ADD COLUMN stock_type VARCHAR(20) COMMENT '股票类别：A股/港股/美股'
                """
            )

        idx = db.query_one(
            """
            SELECT 1
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'stock_basic'
              AND INDEX_NAME = 'idx_stock_type'
            LIMIT 1
            """,
            (database_name,),
        )
        if not idx:
            db.execute("CREATE INDEX idx_stock_type ON stock_basic (stock_type)")

        # 基于已有字段尽量回填
        db.execute(
            """
            UPDATE stock_basic
            SET stock_type = CASE
                WHEN ts_code LIKE '%.HK' OR area='港股' THEN '港股'
                WHEN ts_code LIKE '%.US' OR area='美股' THEN '美股'
                ELSE 'A股'
            END
            WHERE stock_type IS NULL OR TRIM(stock_type)=''
            """
        )
        db.commit()
    except Exception as e:
        logger.warning(f"stock_basic 兼容迁移跳过（可能已存在）: {e}")

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
