

### 导入A股
python3.9 cy_ai/stock/import_cn_a_xlsx.py --file cy_ai/stock/4-25A股.xlsx

首次若表不存在：
python3.9 cy_ai/stock/import_cn_a_xlsx.py --file cy_ai/stock/4-25A股.xlsx --init-tables

指定参考日（仍按「该日最近周五」写 asof_date）：

python3.9 cy_ai/stock/import_cn_a_xlsx.py --ref-date 2026-04-25


# 港股（首次需建表时加 --init-tables，可与 A 股共用一次 init）
python3.9 cy_ai/stock/import_hk_xlsx.py --file cy_ai/stock/4-25港股.xlsx --init-tables

# 美股
python3.9 cy_ai/stock/import_us_xlsx.py --file cy_ai/stock/4-25美股数据.xlsx

# 指定参考日（仍写入该日对应的最近周五）
python3.9 cy_ai/stock/import_hk_xlsx.py --ref-date 2026-04-25


### 导入120日均线
导入前建表/迁移（建议先跑一次）
python3.9 -m cy_ai.main --init-db

python3.9 -m cy_ai.main --export-pool "你的分析结果.csv" --export-pool-output "todolist/ma120_pool_import.csv" --market A股

python3.9 -m cy_ai.main --import-pool "todolist/ma120_pool_import.csv"


python3.9 -m cy_ai.main --import-pool "hk.csv" --market 港股
python3.9 -m cy_ai.main --import-pool "todolist/sh_120ma_breakthrough_20260425.csv" --market A股

python3.9 -m cy_ai.main --import-pool "todolist/us_120ma_breakthrough_20260425.csv" --market 美股

python3.9 -m cy_ai.main --import-pool "todolist/hk_120ma_breakthrough_20260425.csv" --market 港股

说明：
- 导入会先将 stock_pool_ma120 全部标记为失效（status=0），再将本次文件命中的标的激活为有效（status=1）。
- 若数据库 stock_basic 缺少名称/行业，港股与美股会自动从以下文件回填：
  - abupy/RomDataBu/stock_code_HK.csv
  - abupy/RomDataBu/stock_code_US.csv
### 导入stock_basic 
python3.9 -m cy_ai.main --import-rom-basic