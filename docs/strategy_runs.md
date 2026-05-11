# 策略回测登记（Strategy Runs Log）

本表用于**追加记录**每次 abupy 回测或等价验证；请勿改写历史行，新实验请**新增一行**。

填写说明见 [abupy-strategy-validation.md](./abupy-strategy-validation.md) 第 6 节。

| run_id | date | strategy_id | git_commit | market | symbols / 池 | period | position | 收益摘要 | 回撤 | 胜率 | 笔数 | conclusion | artifacts |
|--------|------|-------------|------------|--------|----------------|--------|----------|----------|------|------|------|------------|-----------|
| _示例_ | 2026-05-06 | EXAMPLE_V1 | - | US | usTSLA | n_folds=2 | 默认ATR | - | - | - | - | 模板行，可删 | - |
