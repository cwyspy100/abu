# -*- encoding:utf-8 -*-
"""
Abu 数据模式：本地 ~/abu/data/csv 与「是否允许联网」切换。

- 本地模式：g_data_fetch_mode = E_DATA_FETCH_FORCE_LOCAL，只读缓存 CSV，缺失则返回 None（不请求网络）。
- 网络模式：g_data_fetch_mode = E_DATA_FETCH_NORMAL，本地不足时可拉网。

环境变量（可选，便于不传参运行）：
  ABU_DATA_SOURCE=local|network
  ABU_CSV_DIR=/path/to/csv   覆盖默认 abu 数据目录下的 csv 子目录
"""

from __future__ import print_function

import logging
import os

logger = logging.getLogger(__name__)

# 与 ABuEnv 中约定一致：~/abu/data/csv
_DEFAULT_CSV_SUBPATH = os.path.join("abu", "data", "csv")


def default_csv_dir():
    """展开为默认本地 K 线目录（与 abupy.env.g_project_kl_df_data_csv 初始化规则一致）。"""
    return os.path.expanduser(os.path.join("~", _DEFAULT_CSV_SUBPATH))


def configure_abu_data_source(
    local_csv_only=True,
    csv_dir=None,
    market_source=None,
    use_csv_cache=True,
):
    """
    在 import abupy 之后、run_loop_back / 拉 K 线之前调用。

    :param local_csv_only: True=强制本地；False=普通模式可联网补数
    :param csv_dir: 覆盖 CSV 根目录，默认 None 用 abupy 当前 g_project_kl_df_data_csv（~/abu/data/csv）
    :param market_source: 如 EMarketSourceType.E_MARKET_SOURCE_tx；None 表示不改写当前 g_market_source
    :param use_csv_cache: True 时设置 g_data_cache_type 为 E_DATA_CACHE_CSV
    """
    import abupy
    from abupy.CoreBu.ABuEnv import (
        EDataCacheType,
        EMarketDataFetchMode,
    )

    if use_csv_cache:
        abupy.env.g_data_cache_type = EDataCacheType.E_DATA_CACHE_CSV

    if local_csv_only:
        abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_FORCE_LOCAL
        mode_s = "FORCE_LOCAL"
    else:
        abupy.env.g_data_fetch_mode = EMarketDataFetchMode.E_DATA_FETCH_NORMAL
        mode_s = "NORMAL"

    if csv_dir is not None:
        root = os.path.expanduser(os.path.abspath(csv_dir))
        abupy.env.g_project_kl_df_data_csv = root
    else:
        root = abupy.env.g_project_kl_df_data_csv

    if market_source is not None:
        abupy.env.g_market_source = market_source

    n_files = 0
    try:
        if os.path.isdir(root):
            n_files = len([f for f in os.listdir(root) if f.endswith(".csv")])
    except OSError:
        pass

    logger.info(
        "abu data: mode=%s csv_root=%s n_csv=%s",
        mode_s,
        root,
        n_files,
    )
    if local_csv_only and n_files == 0:
        logger.warning(
            "csv dir empty or unreadable; FORCE_LOCAL may yield no data (run_kl_update or fix --csv-dir)."
        )

    return root


def configure_from_environ():
    """
    读取环境变量 ABU_DATA_SOURCE、ABU_CSV_DIR，返回 (local_csv_only, csv_dir_or_none)。
    未设置 ABU_DATA_SOURCE 时返回 (None, None) 表示调用方使用自己的默认。
    """
    src = os.environ.get("ABU_DATA_SOURCE", "").strip().lower()
    csv_override = os.environ.get("ABU_CSV_DIR", "").strip()
    csv_dir = csv_override if csv_override else None

    if src in ("local", "offline", "1", "true", "yes"):
        return True, csv_dir
    if src in ("network", "online", "0", "false", "no"):
        return False, csv_dir
    return None, csv_dir
