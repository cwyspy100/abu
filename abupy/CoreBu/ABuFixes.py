# -*- encoding:utf-8 -*-
"""
    对各个依赖库不同版本，不同系统的规范进行统一以及问题修正模块
    Python 3.9 版本
"""

import functools
import numbers
import sys

import matplotlib
import numpy as np
import pandas as pd
import scipy
import sklearn as skl

__author__ = '阿布'
__weixin__ = 'abu_quant'


def _parse_version(version_string):
    """
    根据库中的__version__字段，转换为tuple，eg. '1.11.3'->(1, 11, 3)
    :param version_string: __version__字符串对象
    :return: tuple 对象
    """
    version = []
    for x in version_string.split('.'):
        try:
            version.append(int(x))
        except ValueError:
            version.append(x)
    return tuple(version)


"""numpy 版本号tuple"""
np_version = _parse_version(np.__version__)
"""sklearn 版本号tuple"""
skl_version = _parse_version(skl.__version__)
"""pandas 版本号tuple"""
pd_version = _parse_version(pd.__version__)
"""scipy 版本号tuple"""
sp_version = _parse_version(scipy.__version__)
"""matplotlib 版本号tuple"""
mpl_version = _parse_version(matplotlib.__version__)

# Python 3.9 内置 inspect.signature
from inspect import signature, Parameter

# Python 3.9 内置 concurrent.futures
from concurrent.futures import ThreadPoolExecutor

# Python 3.9 内置函数，无需导入
# zip, range, map, filter 都是内置函数
# 为了保持向后兼容，导出这些内置函数
zip = zip
range = range
map = map
filter = filter
# reduce 需要从 functools 导入
from functools import reduce

# Python 3.9 统一使用 pickle
import pickle
from pickle import Unpickler, Pickler

def as_bytes(s):
    """将字符串转换为 bytes"""
    if isinstance(s, bytes):
        return s
    if isinstance(s, str):
        return s.encode('latin1')
    raise TypeError(f"Expected str or bytes, got {type(s)}")

# Python 3.9 内置 functools.lru_cache
from functools import lru_cache

try:
    from itertools import combinations_with_replacement
except ImportError:
    # Backport of itertools.combinations_with_replacement for Python 2.6,
    # from Python 3.4 documentation (http://tinyurl.com/comb-w-r), copyright
    # Python Software Foundation (https://docs.python.org/3/license.html)
    def combinations_with_replacement(iterable, r):
        # combinations_with_replacement('ABC', 2) --> AA AB AC BB BC CC
        pool = tuple(iterable)
        n = len(pool)
        if not n and r:
            return
        indices = [0] * r
        yield tuple(pool[i] for i in indices)
        while True:
            for i in reversed(range(r)):
                if indices[i] != n - 1:
                    break
            else:
                return
            indices[i:] = [indices[i] + 1] * (r - i)
            yield tuple(pool[i] for i in indices)

# Python 3.9 内置 functools.partial
from functools import partial

"""
    matplotlib fixes
"""
# 先别加了，用的地方内部try吧，不然waring太多
# try:
#     # noinspection PyUnresolvedReferences, PyDeprecation
#     import matplotlib.finance as mpf
# except ImportError:
#     # 2.2 才会有
#     # noinspection PyUnresolvedReferences, PyDeprecation
#     import matplotlib.mpl_finance as mpf

"""
    urlencode
"""
# Python 3.9 统一使用 urllib.parse
from urllib.parse import urlencode

"""
    scikit-learn fixes
    Python 3.9 + scikit-learn >= 0.24.0: 统一使用 sklearn.model_selection API
"""


# noinspection PyProtectedMember,PyUnresolvedReferences
def check_random_state(seed):
    if seed is None or seed is np.random:
        return np.random.mtrand._rand
    if isinstance(seed, (numbers.Integral, np.integer)):
        return np.random.RandomState(seed)
    if isinstance(seed, np.random.RandomState):
        return seed
    raise ValueError('%r cannot be used to seed a numpy.random.RandomState'
                     ' instance' % seed)


# Python 3.9 + scikit-learn >= 0.24.0: 统一使用新 API
# 旧版本 API (sklearn.cross_validation, sklearn.learning_curve, sklearn.grid_search) 已移除
mean_squared_error_scorer = 'neg_mean_squared_error'
mean_absolute_error_scorer = 'neg_mean_absolute_error'
median_absolute_error_scorer = 'neg_median_absolute_error'
log_loss = 'neg_log_loss'

# 统一使用 sklearn.model_selection
from sklearn.model_selection import train_test_split
from sklearn.model_selection import learning_curve
from sklearn.model_selection import cross_val_score
from sklearn.model_selection import GridSearchCV
# noinspection PyPep8Naming
from sklearn.mixture import GaussianMixture as GMM


class KFold(object):
    """
        scikit-learn 将 KFold 移动到了 model_selection，而且改变了用法，暂时不需要
        这么复杂的功能，将 scikit-learn 中关键代码简单实现，不 from sklearn.model_selection import KFold
    """

    def __init__(self, n, n_folds=3, shuffle=False, random_state=None):
        if abs(n - int(n)) >= np.finfo('f').eps:
            raise ValueError("n must be an integer")
        self.n = int(n)

        if abs(n_folds - int(n_folds)) >= np.finfo('f').eps:
            raise ValueError("n_folds must be an integer")
        self.n_folds = n_folds = int(n_folds)

        if n_folds <= 1:
            raise ValueError(
                "k-fold cross validation requires at least one"
                " train / test split by setting n_folds=2 or more,"
                " got n_folds={0}.".format(n_folds))
        if n_folds > self.n:
            raise ValueError(
                ("Cannot have number of folds n_folds={0} greater"
                 " than the number of samples: {1}.").format(n_folds, n))

        if not isinstance(shuffle, bool):
            raise TypeError("shuffle must be True or False;"
                            " got {0}".format(shuffle))
        self.shuffle = shuffle
        self.random_state = random_state

        self.idxs = np.arange(n)
        if shuffle:
            rng = check_random_state(self.random_state)
            rng.shuffle(self.idxs)

    def __iter__(self):
        ind = np.arange(self.n)
        for test_index in self._iter_test_masks():
            train_index = np.logical_not(test_index)
            train_index = ind[train_index]
            test_index = ind[test_index]
            yield train_index, test_index

    def _iter_test_masks(self):
        for test_index in self._iter_test_indices():
            test_mask = self._empty_mask()
            test_mask[test_index] = True
            yield test_mask

    def _empty_mask(self):
        return np.zeros(self.n, dtype=bool)

    def _iter_test_indices(self):
        n = self.n
        n_folds = self.n_folds
        fold_sizes = (n // n_folds) * np.ones(n_folds, dtype=int)
        fold_sizes[:n % n_folds] += 1
        current = 0
        for fold_size in fold_sizes:
            start, stop = current, current + fold_size
            yield self.idxs[start:stop]
            current = stop

    def __repr__(self):
        return '%s.%s(n=%i, n_folds=%i, shuffle=%s, random_state=%s)' % (
            self.__class__.__module__,
            self.__class__.__name__,
            self.n,
            self.n_folds,
            self.shuffle,
            self.random_state,
        )

    def __len__(self):
        return self.n_folds

# Python 3.9 + NumPy 1.19+ 直接使用内置函数
from numpy import array_equal

# Python 3.9 + SciPy 1.7+ 直接使用内置函数
from scipy.stats import rankdata
