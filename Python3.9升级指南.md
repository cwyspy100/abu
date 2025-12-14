# abupy 升级到 Python 3.9 指南

## 📋 概述

本文档梳理了将 abupy 代码库从 Python 2/3 兼容版本升级到 Python 3.9 所需的依赖更新和代码修改。

## 🔍 代码库分析

### 当前状态
- **版本**: abupy 0.4.0
- **Python 兼容性**: Python 2.7 + Python 3.x（通过 six 库兼容）
- **主要依赖**: numpy, pandas, scipy, sklearn, matplotlib, seaborn
- **兼容性库**: six, funcsigs, futures (内置在 ExtBu 目录)

### 代码特点
1. 大量使用 `from __future__ import` 确保 Python 2/3 兼容
2. 使用 `six` 库处理 Python 2/3 差异
3. 内置了兼容性库（ExtBu 目录）
4. 使用 `ABuFixes.py` 统一处理依赖库版本差异

## 📦 依赖包升级方案

### 核心依赖包

| 包名 | 当前版本要求 | Python 3.9 推荐版本 | 说明 |
|------|------------|-------------------|------|
| **numpy** | >= 1.8.1 | >= 1.19.0 | Python 3.9 最低要求 1.19.0 |
| **pandas** | 未明确 | >= 1.3.0 | Python 3.9 支持，注意 API 变化 |
| **scipy** | >= 0.13.0 | >= 1.7.0 | Python 3.9 支持 |
| **scikit-learn** | >= 0.18.0 | >= 0.24.0 | 旧版本 API 已废弃 |
| **matplotlib** | 未明确 | >= 3.3.0 | Python 3.9 支持 |
| **seaborn** | 未明确 | >= 0.11.0 | 依赖 matplotlib |

### 可选依赖包

| 包名 | 用途 | Python 3.9 推荐版本 |
|------|------|-------------------|
| **psutil** | CPU 计数 | >= 5.8.0 |
| **joblib** | 并行处理 | >= 1.0.0 |
| **h5py** | HDF5 支持 | >= 3.1.0 |

### 兼容性库（可移除）

| 包名 | 状态 | 说明 |
|------|------|------|
| **six** | 可移除 | Python 3.9 不需要 |
| **funcsigs** | 可移除 | Python 3.9 内置 inspect.signature |
| **futures** | 可移除 | Python 3.9 内置 concurrent.futures |
| **functools32** | 可移除 | Python 3.9 内置 functools.lru_cache |

## 🔧 代码修改清单

### 1. 移除 Python 2 兼容代码

#### 1.1 移除 `from __future__` 导入
**文件**: 所有 `.py` 文件
```python
# 删除这些行
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
```

#### 1.2 移除 `six` 库依赖
**文件**: `abupy/CoreBu/ABuFixes.py`, `abupy/CoreBu/ABuEnv.py` 等

**修改前**:
```python
from ..CoreBu.ABuFixes import six
g_is_py3 = six.PY3
```

**修改后**:
```python
# 直接使用 Python 3 特性
g_is_py3 = True  # Python 3.9 始终为 True
```

#### 1.3 移除 `reload()` 函数
**文件**: `abupy/CoreBu/ABuEnv.py:498`

**修改前**:
```python
if g_is_ipython and not g_is_py3:
    reload(logging)
```

**修改后**:
```python
# Python 3.9 使用 importlib.reload
from importlib import reload
if g_is_ipython:
    reload(logging)
```

### 2. 修复废弃的 API

#### 2.1 collections.Iterable
**文件**: `abupy/CoreBu/ABuPdHelper.py:11`

**修改前**:
```python
from collections import Iterable
```

**修改后**:
```python
from collections.abc import Iterable
```

#### 2.2 NumPy 类型别名
**文件**: `abupy/CoreBu/ABuFixes.py:275, 280`

**修改前**:
```python
dtype=np.bool
dtype=np.int
```

**修改后**:
```python
dtype=bool  # 或 np.bool_
dtype=int   # 或 np.int_
```

#### 2.3 sklearn API 变化
**文件**: `abupy/CoreBu/ABuFixes.py`

**问题**: sklearn 0.24+ 移除了 `sklearn.cross_validation` 和 `sklearn.learning_curve`

**修改**: 代码中已有兼容处理，但需要确保使用新 API：
```python
# 确保使用新 API
from sklearn.model_selection import train_test_split
from sklearn.model_selection import learning_curve
from sklearn.model_selection import cross_val_score
from sklearn.model_selection import GridSearchCV
```

### 3. 更新 ABuFixes.py

#### 3.1 移除 six 相关代码
```python
# 删除
try:
    from ..ExtBu import six
except ImportError:
    import six as six

# 删除
from ..ExtBu.six.moves import zip, xrange, range, reduce, map, filter
```

#### 3.2 简化 Python 版本检查
```python
# 修改前
if six.PY3:
    from functools import lru_cache
else:
    from functools32 import lru_cache

# 修改后
from functools import lru_cache
```

#### 3.3 简化 pickle 处理
```python
# 修改前
if six.PY3:
    Unpickler = pickle._Unpickler
    Pickler = pickle._Pickler
else:
    Unpickler = pickle.Unpickler
    Pickler = pickle.Pickler

# 修改后
from pickle import Unpickler, Pickler
```

### 4. 更新字符串处理

#### 4.1 移除 bytes/str 转换函数
**文件**: `abupy/CoreBu/ABuFixes.py:97-103`

**修改前**:
```python
if six.PY3:
    def as_bytes(s):
        if isinstance(s, bytes):
            return s
        return s.encode('latin1')
else:
    as_bytes = str
```

**修改后**:
```python
def as_bytes(s):
    if isinstance(s, bytes):
        return s
    return s.encode('latin1')
```

### 5. 更新 urllib 导入

**文件**: `abupy/CoreBu/ABuFixes.py:180-185`

**修改前**:
```python
if six.PY3:
    from urllib.parse import urlencode
else:
    from urllib import urlencode
```

**修改后**:
```python
from urllib.parse import urlencode
```

### 6. 移除 xrange

**文件**: 所有使用 `xrange` 的文件

**修改前**:
```python
from abupy import xrange
for i in xrange(10):
    pass
```

**修改后**:
```python
for i in range(10):
    pass
```

## 📝 依赖文件创建

### requirements.txt
```txt
# Python 3.9 依赖
numpy>=1.19.0,<2.0.0
pandas>=1.3.0,<2.0.0
scipy>=1.7.0
scikit-learn>=0.24.0
matplotlib>=3.3.0
seaborn>=0.11.0
psutil>=5.8.0
joblib>=1.0.0
h5py>=3.1.0  # 可选，用于 HDF5 支持
```

### setup.py (如果不存在)
```python
from setuptools import setup, find_packages

setup(
    name='abupy',
    version='0.4.0',
    python_requires='>=3.9',
    install_requires=[
        'numpy>=1.19.0',
        'pandas>=1.3.0',
        'scipy>=1.7.0',
        'scikit-learn>=0.24.0',
        'matplotlib>=3.3.0',
        'seaborn>=0.11.0',
        'psutil>=5.8.0',
        'joblib>=1.0.0',
    ],
    extras_require={
        'hdf5': ['h5py>=3.1.0'],
    },
    packages=find_packages(),
)
```

## ✅ 测试检查清单

### 1. 语法检查
```bash
python -m py_compile abupy/**/*.py
```

### 2. 导入测试
```python
import abupy
from abupy import *
```

### 3. 功能测试
- [ ] 数据获取功能
- [ ] 回测功能
- [ ] 机器学习功能
- [ ] 可视化功能

### 4. 依赖版本检查
```python
import numpy as np
import pandas as pd
import scipy
import sklearn
import matplotlib
print(f"numpy: {np.__version__}")
print(f"pandas: {pd.__version__}")
print(f"scipy: {scipy.__version__}")
print(f"sklearn: {sklearn.__version__}")
print(f"matplotlib: {matplotlib.__version__}")
```

## ⚠️ 注意事项

### 1. 向后兼容性
- 移除 Python 2 支持后，代码将不再兼容 Python 2.7
- 建议在升级前备份代码

### 2. 测试覆盖
- 升级后需要全面测试所有功能模块
- 特别注意数据读取、处理和存储功能

### 3. 性能优化
- Python 3.9 性能优于 Python 2.7
- 可以考虑移除不必要的兼容性代码以提高性能

### 4. 文档更新
- 更新 README.md 中的 Python 版本要求
- 更新安装说明

## 🔄 升级步骤

1. **创建新分支**
   ```bash
   git checkout -b python3.9-upgrade
   ```

2. **更新依赖**
   ```bash
   pip install -r requirements.txt
   ```

3. **逐步修改代码**
   - 先修改 `ABuFixes.py`
   - 再修改其他核心文件
   - 最后修改业务逻辑文件

4. **运行测试**
   ```bash
   python -m pytest tests/  # 如果有测试
   ```

5. **验证功能**
   - 运行示例代码
   - 检查日志输出
   - 验证数据读写

## 📚 参考资源

- [Python 3.9 新特性](https://docs.python.org/3/whatsnew/3.9.html)
- [NumPy 1.19 迁移指南](https://numpy.org/devdocs/release/1.19.0-notes.html)
- [Pandas 1.3 迁移指南](https://pandas.pydata.org/docs/whatsnew/v1.3.0.html)
- [scikit-learn 0.24 迁移指南](https://scikit-learn.org/stable/whats_new/v0.24.html)

## 📊 影响范围评估

### 高影响文件（需要重点修改）
- `abupy/CoreBu/ABuFixes.py` - 核心兼容性文件
- `abupy/CoreBu/ABuEnv.py` - 环境配置
- `abupy/CoreBu/ABuPdHelper.py` - pandas 兼容性

### 中影响文件（需要检查）
- `abupy/MarketBu/*` - 数据获取模块
- `abupy/MLBu/*` - 机器学习模块
- `abupy/MetricsBu/*` - 指标计算模块

### 低影响文件（可能不需要修改）
- 业务逻辑文件（大部分应该自动兼容）

## 🎯 总结

升级到 Python 3.9 的主要工作：
1. ✅ 移除 Python 2 兼容代码
2. ✅ 更新废弃的 API 调用
3. ✅ 升级依赖包版本
4. ✅ 移除不必要的兼容性库
5. ✅ 全面测试验证

预计工作量：**中等**（2-3 天）
风险评估：**中等**（需要充分测试）

