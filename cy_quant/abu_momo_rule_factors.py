# -*- encoding:utf-8 -*-
"""
Abu 扩展：动量突破规则链（选股 + 择时 + 仓位 + 卖出）

将下列规则接入 abupy.run_loop_back：
  选股：大盘 MA200、个股 MA120、RS Top%、ATR20<ATR60（波动压缩）
  择时：20 日或 55 日收盘新高（含当日，二选一；与 AbuFactorBuyBreak 窗口口径一致）
  仓位：按初始资金固定比例估算「单笔风险」≈ risk_pct × read_cash / (stop_atr_mult × ATR)
  卖出：ATR 止损（与 AbuFactorAtrNStop 的 atr21+atr14 口径一致）+ 跌破前 20 日最低价

说明：
  - Abu 订单里的仓位默认使用 capital.read_cash（初始资金），非每日权益；若需「按当前权益 1%」
    需在仓位类中自行读取 capital.capital_pd（本模块提供 risk_basis 参数做简化近似）。
  - 大盘过滤默认与 AbuBenchmark 一致：使用 self.benchmark.kl_pd.name 拉取指数 K 线（如美股 us.IXIC、A 股 sh000001）。
    可选参数 bench_pick_symbol 仅用于显式覆盖（一般不必设）。
"""

from __future__ import print_function

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

from abupy.FactorBuyBu.ABuFactorBuyBase import AbuFactorBuyBase, BuyCallMixin
from abupy.FactorSellBu.ABuFactorSellBase import AbuFactorSellBase, ESupportDirection
from abupy.IndicatorBu.ABuNDAtr import calc_atr
from abupy.PickStockBu.ABuPickStockBase import AbuPickStockBase, reversed_result
from abupy.BetaBu.ABuPositionBase import AbuPositionBase


def _np_quantile_compat(arr, q):
    """
    分位数 q∈[0,1]。兼容 numpy<1.15 无 np.quantile 的环境（用 np.percentile）。
    """
    a = np.asarray(arr, dtype=float)
    if hasattr(np, "quantile"):
        return float(np.quantile(a, q))
    return float(np.percentile(a, q * 100.0))


def _resolve_bench_symbol_for_pick(benchmark, override):
    """
    与 run_loop_back 中 AbuCapital / AbuBenchmark 使用的基准一致。
    override 非空时优先（极少数需与回测基准不同的场景）。
    """
    if override is not None and str(override).strip() != "":
        return str(override).strip()
    if benchmark is None or getattr(benchmark, "kl_pd", None) is None:
        return None
    name = getattr(benchmark.kl_pd, "name", None)
    if name is None:
        return None
    return str(name)


def _ma_last(close_series, n):
    s = pd.to_numeric(close_series, errors="coerce")
    m = s.rolling(window=int(n), min_periods=int(n)).mean()
    if m.empty or np.isnan(m.iloc[-1]):
        return np.nan
    return float(m.iloc[-1])


def _atr_pair_last(high, low, close, n_short=20, n_long=60):
    """返回最后一根 K 线上的 ATR(n_short)、ATR(n_long)。"""
    h = pd.to_numeric(high, errors="coerce")
    l = pd.to_numeric(low, errors="coerce")
    c = pd.to_numeric(close, errors="coerce")
    a_s = calc_atr(h, l, c, n_short)
    a_l = calc_atr(h, l, c, n_long)
    if len(a_s) == 0 or np.isnan(a_s[-1]) or np.isnan(a_l[-1]):
        return np.nan, np.nan
    return float(a_s[-1]), float(a_l[-1])


def _last_trade_date_str(kl_pd):
    """K 线最后一行的日期（便于与行情软件核对）。"""
    if kl_pd is None or len(kl_pd) == 0:
        return "?"
    try:
        ts = kl_pd.index[-1]
        return str(ts)[:10] if ts is not None else str(kl_pd["date"].iloc[-1])
    except Exception:
        return "?"


def momentum_pick_diagnose_lines(
    symbol,
    bench_sym,
    mgr,
    pick_xd=252,
    bench_ma_n=120,
    stock_ma_n=120,
    rs_lookback_n=60,
    rs_top_pct=0.2,
    atr_short_n=20,
    atr_long_n=60,
):
    """
    按 ``AbuPickRuleMomentumBreakoutComp.fit_first_choice`` 的规则，对单标的输出可读的通过/失败原因。
    RS 最终「top 分位」是截面比较，此处只报告个股 rs_ret，无法单独复现是否进 pick 名单。

    **数据口径**：使用 ``get_pick_time_kl_pd``（与 ``run_loop_back`` 择时标尺一致，末端一般为本地回测区间
    的**最新交易日**）。``main_pick`` 内部仍用 ``get_pick_stock_kl_pd``，其窗口锚点不同，故与行情软件
    「全历史最后一根」对比时可能不一致——以本诊断打印的「末端日期」为准。
    """
    min_xd_bench = int(bench_ma_n) + 5
    min_xd_stock = max(
        int(stock_ma_n) + 5,
        int(rs_lookback_n) + 5,
        int(atr_long_n) + 5,
        130,
    )
    xd_use = max(int(pick_xd), min_xd_bench, min_xd_stock)
    out = []
    out.append("[选股条件] 标的=%s 基准=%s（参数 xd=%d 仅作说明；实际拉取见下）" % (symbol, bench_sym, xd_use))
    out.append(
        "… 数据口径: get_pick_time_kl_pd（与回测择时末端对齐），非 get_pick_stock_kl_pd 选股窗口"
    )

    bench_kl = mgr.get_pick_time_kl_pd(bench_sym)
    if bench_kl is None or len(bench_kl) < min_xd_bench:
        out.append(
            "× 大盘: K 线不足或未加载 len=%s 需要>=%d"
            % (0 if bench_kl is None else len(bench_kl), min_xd_bench)
        )
        return out

    out.append("… 大盘序列末端日期: %s" % _last_trade_date_str(bench_kl))

    bench_close = pd.to_numeric(bench_kl["close"], errors="coerce")
    b_last = float(bench_close.iloc[-1])
    b_ma = _ma_last(bench_close, bench_ma_n)
    if np.isnan(b_ma):
        out.append("× 大盘: MA%d 无法计算" % bench_ma_n)
        return out
    if b_last <= b_ma:
        out.append(
            "× 大盘过滤: 收盘 %.4f <= MA%d=%.4f（需收盘在指数均线之上）"
            % (b_last, bench_ma_n, b_ma)
        )
        return out
    out.append(
        "√ 大盘过滤: 收盘 %.4f > MA%d=%.4f"
        % (b_last, bench_ma_n, b_ma)
    )

    kl = mgr.get_pick_time_kl_pd(symbol)
    if kl is None or len(kl) < min_xd_stock:
        out.append(
            "× 个股: pick_time K 线不足 len=%s 需要>=%d"
            % (0 if kl is None else len(kl), min_xd_stock)
        )
        return out

    out.append("… 个股序列末端日期: %s（请与行情软件当前查看的日期对齐）" % _last_trade_date_str(kl))

    close = pd.to_numeric(kl["close"], errors="coerce")
    last_c = float(close.iloc[-1])
    ma_s = _ma_last(close, stock_ma_n)
    if np.isnan(ma_s):
        out.append("× 个股趋势: MA%d 无法计算" % stock_ma_n)
        return out
    if last_c <= ma_s:
        out.append(
            "× 个股趋势: 收盘 %.4f <= MA%d=%.4f（需在个股均线之上）"
            % (last_c, stock_ma_n, ma_s)
        )
        return out
    out.append(
        "√ 个股趋势: 收盘 %.4f > MA%d=%.4f"
        % (last_c, stock_ma_n, ma_s)
    )

    if rs_lookback_n > 0:
        lag_c = float(close.iloc[-1 - rs_lookback_n])
        if np.isnan(lag_c) or lag_c <= 0:
            out.append("× 相对强度: %d 日前收盘价无效" % rs_lookback_n)
            return out
        rs_ret = last_c / lag_c - 1.0
        out.append(
            "… 相对强度 RS: 相对「末端日期」前推 %d 根K 收 %.4f → 末端收 %.4f 涨幅=%.4f%%"
            "（是否 top%.0f%% 需全市场截面分位，单股无法判定）"
            % (rs_lookback_n, lag_c, last_c, rs_ret * 100.0, rs_top_pct * 100.0)
        )
    else:
        out.append("… 相对强度: rs_lookback_n=0 跳过")

    hi = kl["high"] if "high" in kl.columns else close
    lo = kl["low"] if "low" in kl.columns else close
    a_s, a_l = _atr_pair_last(hi, lo, close, atr_short_n, atr_long_n)
    if np.isnan(a_s) or np.isnan(a_l):
        out.append("× 波动压缩: ATR 无效")
        return out
    if not (a_s < a_l):
        out.append(
            "× 波动压缩: ATR(%d)=%.6f >= ATR(%d)=%.6f（需短 ATR < 长 ATR）"
            % (atr_short_n, a_s, atr_long_n, a_l)
        )
        return out
    out.append(
        "√ 波动压缩: ATR(%d)=%.6f < ATR(%d)=%.6f"
        % (atr_short_n, a_s, atr_long_n, a_l)
    )

    out.append(
        "小结: 截至最后一根 K，大盘+个股趋势+ATR 条件已满足；最终是否被 first_choice 选中还取决于 RS 在候选池中的分位。"
    )
    return out


def dual_high_break_diagnose_lines(symbol, mgr, pick_xd, xd_short, xd_long):
    """
    按 ``AbuFactorBuyDualHighBreak``，只看「最后一根 K」是否会在当日收盘后发出「次日买」
    （与回测中逐日扫描一致，此处是 end-of-sample 快照）。

    使用 ``get_pick_time_kl_pd`` 与回测择时序列一致。
    """
    need = max(int(xd_short), int(xd_long))
    min_xd = max(need + 5, 130)
    _ = pick_xd  # 与外部调用参数表一致；本函数以 pick_time 全序列为准
    out = []
    out.append("[择时条件 dual high] 标的=%s xd_short=%d xd_long=%d" % (symbol, xd_short, xd_long))

    kl = mgr.get_pick_time_kl_pd(symbol)
    if kl is None or len(kl) < min_xd:
        out.append(
            "× K 线不足 len=%s 需要>=%d"
            % (0 if kl is None else len(kl), min_xd)
        )
        return out

    out.append("… 择时序列末端日期: %s" % _last_trade_date_str(kl))

    close = pd.to_numeric(kl["close"], errors="coerce")
    today_ind = len(close) - 1
    if today_ind < need - 1:
        out.append("× 数据长度不足以判断新高")
        return out

    win_s = close.iloc[today_ind - xd_short + 1 : today_ind + 1]
    win_l = close.iloc[today_ind - xd_long + 1 : today_ind + 1]
    last_c = float(close.iloc[-1])
    max_s = float(win_s.max())
    max_l = float(win_l.max())
    short_ok = last_c == max_s
    long_ok = last_c == max_l
    if short_ok or long_ok:
        out.append(
            "√ 截至最后交易日: 触发买入信号（二选一） short_win=%d 内新高=%s | long_win=%d 内新高=%s"
            % (xd_short, short_ok, xd_long, long_ok)
        )
        out.append(
            "  收盘=%.4f | %d日窗口最高=%.4f | %d日窗口最高=%.4f"
            % (last_c, xd_short, max_s, xd_long, max_l)
        )
    else:
        out.append(
            "× 截至最后交易日: 未触发 dual high（收盘价非 %d / %d 日窗口最高价）"
            % (xd_short, xd_long)
        )
        out.append(
            "  收盘=%.4f | %d日窗口最高=%.4f | %d日窗口最高=%.4f"
            % (last_c, xd_short, max_s, xd_long, max_l)
        )
    out.append(
        "说明: 回测会逐日重算；若此处未触发仍可能有历史成交，请看 orders_pd。"
    )
    return out


class AbuPickRuleMomentumBreakoutComp(AbuPickStockBase):
    """
    组合选股（使用 fit_first_choice 做截面 RS），适合作为 stock_pickers 中唯一 first_choice 因子。

    大盘过滤默认使用 Abu 当前回测基准 self.benchmark（与 AbuBenchmark 一致，如 IXIC / 上证指数）。
    仅当传入 bench_pick_symbol 时才覆盖基准代码。
    """

    def _init_self(self, **kwargs):
        # None：在 fit_first_choice 中解析为 self.benchmark.kl_pd.name
        self.bench_pick_symbol = kwargs.get("bench_pick_symbol", None)
        self.bench_ma_n = int(kwargs.get("bench_ma_n", 200))
        self.stock_ma_n = int(kwargs.get("stock_ma_n", 120))
        self.rs_lookback_n = int(kwargs.get("rs_lookback_n", 60))
        self.rs_top_pct = float(kwargs.get("rs_top_pct", 0.2))
        self.atr_short_n = int(kwargs.get("atr_short_n", 20))
        self.atr_long_n = int(kwargs.get("atr_long_n", 60))
        self.min_xd_bench = int(kwargs.get("min_xd_bench", self.bench_ma_n + 5))
        self.min_xd_stock = int(
            kwargs.get(
                "min_xd_stock",
                max(self.stock_ma_n + 5, self.rs_lookback_n + 5, self.atr_long_n + 5, 130),
            )
        )
        self.progress_every = max(1, int(kwargs.get("progress_every", 200)))

    @reversed_result
    def fit_pick(self, kl_pd, target_symbol):
        """仅 first_choice 使用时不会被调用；满足抽象接口。"""
        return True

    def fit_first_choice(self, pick_worker, choice_symbols, *args, **kwargs):
        mgr = pick_worker.kl_pd_manager
        xd = max(self.xd, self.min_xd_bench, self.min_xd_stock)

        bench_sym = _resolve_bench_symbol_for_pick(self.benchmark, self.bench_pick_symbol)
        if not bench_sym:
            logger.warning(
                "[AbuPickRuleMomentumBreakoutComp] 无法解析基准代码（benchmark.kl_pd.name 为空），跳过选股"
            )
            return []

        n_in = len(choice_symbols) if choice_symbols else 0
        logger.info(
            "[AbuPickRuleMomentumBreakoutComp] 开始 first_choice：备选 %d 只，大盘(AbuBenchmark)=%s MA%d，"
            "个股 MA%d，RS 回看=%d top=%.0f%%，ATR %d/%d，progress 每 %d 只",
            n_in,
            bench_sym,
            self.bench_ma_n,
            self.stock_ma_n,
            self.rs_lookback_n,
            self.rs_top_pct * 100.0,
            self.atr_short_n,
            self.atr_long_n,
            self.progress_every,
        )

        bench_kl = mgr.get_pick_stock_kl_pd(bench_sym, xd, self.min_xd_bench)
        if bench_kl is None or len(bench_kl) < self.min_xd_bench:
            logger.warning(
                "[AbuPickRuleMomentumBreakoutComp] 大盘 K 线不足或未加载：%s len=%s",
                bench_sym,
                0 if bench_kl is None else len(bench_kl),
            )
            return []

        bench_close = pd.to_numeric(bench_kl["close"], errors="coerce")
        b_last = float(bench_close.iloc[-1])
        b_ma = _ma_last(bench_close, self.bench_ma_n)
        if np.isnan(b_ma) or b_last <= b_ma:
            logger.info(
                "[AbuPickRuleMomentumBreakoutComp] 大盘过滤未通过：close=%.4f MA%d=%.4f",
                b_last,
                self.bench_ma_n,
                b_ma if not np.isnan(b_ma) else float("nan"),
            )
            return []

        logger.info(
            "[AbuPickRuleMomentumBreakoutComp] 大盘过滤通过：close=%.4f > MA%d=%.4f",
            b_last,
            self.bench_ma_n,
            b_ma,
        )

        candidates = []
        syms = [s for s in choice_symbols if s != bench_sym]
        n_scan = len(syms)
        for i, sym in enumerate(syms, start=1):
            if i == 1 or i % self.progress_every == 0 or i == n_scan:
                logger.info(
                    "[AbuPickRuleMomentumBreakoutComp] 扫描进度 %d/%d，均线+ATR 压缩候选 %d 只",
                    i,
                    n_scan,
                    len(candidates),
                )
            kl = mgr.get_pick_stock_kl_pd(sym, xd, self.min_xd_stock)
            if kl is None or len(kl) < self.min_xd_stock:
                continue
            close = pd.to_numeric(kl["close"], errors="coerce")
            last_c = float(close.iloc[-1])
            ma_s = _ma_last(close, self.stock_ma_n)
            if np.isnan(ma_s) or last_c <= ma_s:
                continue

            if self.rs_lookback_n > 0:
                lag_c = float(close.iloc[-1 - self.rs_lookback_n])
                if np.isnan(lag_c) or lag_c <= 0:
                    continue
                rs_ret = last_c / lag_c - 1.0
            else:
                rs_ret = 0.0

            hi = kl["high"] if "high" in kl.columns else close
            lo = kl["low"] if "low" in kl.columns else close
            a_s, a_l = _atr_pair_last(hi, lo, close, self.atr_short_n, self.atr_long_n)
            if np.isnan(a_s) or np.isnan(a_l) or not (a_s < a_l):
                continue

            candidates.append({"sym": sym, "rs_ret": float(rs_ret)})

        if not candidates:
            logger.info(
                "[AbuPickRuleMomentumBreakoutComp] 无标的通过趋势+ATR 压缩（已扫 %d 只）",
                n_scan,
            )
            return []

        rs_arr = np.array([c["rs_ret"] for c in candidates], dtype=float)
        q = _np_quantile_compat(rs_arr, 1.0 - self.rs_top_pct)
        out = [c["sym"] for c in candidates if c["rs_ret"] >= q - 1e-12]
        logger.info(
            "[AbuPickRuleMomentumBreakoutComp] RS 分位阈值 ret>=%.6f，候选 %d -> 入选 %d",
            q,
            len(candidates),
            len(out),
        )
        if out:
            sym_line = ", ".join(out)
            logger.info(
                "[AbuPickRuleMomentumBreakoutComp] pick symbols (%d): %s",
                len(out),
                sym_line,
            )
            print("[AbuPickRuleMomentumBreakoutComp] pick symbols (%d): %s" % (len(out), sym_line))
        return out


class AbuFactorBuyDualHighBreak(AbuFactorBuyBase, BuyCallMixin):
    """
    双窗口收盘新高择时（二选一即可）：
    xd_short 日 **或** xd_long 日（均含当日）任一窗口内收盘为最高价，则信号成立，次日买入。
    """

    def _init_self(self, **kwargs):
        self.xd_short = int(kwargs["xd_short"])
        self.xd_long = int(kwargs["xd_long"])
        self.factor_name = "{}:{}|{}".format(
            self.__class__.__name__, self.xd_short, self.xd_long
        )

    def fit_day(self, today):
        need = max(self.xd_short, self.xd_long)
        if self.today_ind < need - 1:
            return None

        win_s = self.kl_pd.close[self.today_ind - self.xd_short + 1 : self.today_ind + 1]
        win_l = self.kl_pd.close[self.today_ind - self.xd_long + 1 : self.today_ind + 1]
        short_ok = today.close == win_s.max()
        long_ok = today.close == win_l.max()
        if short_ok or long_ok:
            self.skip_days = need
            return self.buy_tomorrow()
        return None


class AbuRiskPctAtrPosition(AbuPositionBase):
    """
    按「风险金额 / 每股风险」定仓：risk_amount = read_cash * risk_pct（或近似权益 × risk_pct）。
    每股风险 = stop_atr_mult × (atr21 + atr14)，与 AbuFactorAtrNStop 中 stop_base 一致。
    通过买入因子 position 参数注入：position={'class': AbuRiskPctAtrPosition, ...}

    继承 AbuPositionBase + MarketMixin，供 AbuOrder 解析 symbol_market（港股手数等）。
    """

    def _init_self(self, **kwargs):
        self.risk_pct = float(kwargs.pop("risk_pct", 0.01))
        self.stop_atr_mult = float(kwargs.pop("stop_atr_mult", 1.0))
        self.risk_basis = kwargs.pop("risk_basis", "initial")
        if kwargs:
            raise TypeError("unexpected kwargs: %s" % kwargs)

    def fit_position(self, factor_object):
        atr21 = float(self.kl_pd_buy["atr21"])
        atr14 = float(self.kl_pd_buy["atr14"])
        stop_dist = self.stop_atr_mult * (atr21 + atr14)
        if stop_dist <= 0 or np.isnan(stop_dist):
            return np.nan

        basis_cash = self.read_cash
        if self.risk_basis == "equity_approx":
            cap = factor_object.capital
            try:
                row = cap.capital_pd.loc[self.kl_pd_buy.name]
                cash = row.get("cash_blance", np.nan)
                stocks = row.get("stocks_blance", 0.0)
                if not np.isnan(cash):
                    basis_cash = float(cash) + float(stocks)
            except Exception:
                pass

        risk_dollars = basis_cash * self.risk_pct
        shares = risk_dollars / stop_dist
        max_shares = self.read_cash * self.pos_max * self.deposit_rate / self.bp
        shares = min(shares, max_shares)
        return shares


class AbuFactorSellTrendLowBreak(AbuFactorSellBase):
    """收盘跌破前 low_n 日最低价（不含当日，与常见「跌破 N 日平台」一致）。"""

    def _init_self(self, **kwargs):
        self.low_n = int(kwargs.get("low_n", 20))
        self.sell_type_extra = "{}:low_n={}".format(self.__class__.__name__, self.low_n)

    def support_direction(self):
        return [ESupportDirection.DIRECTION_CAll.value]

    def fit_day(self, today, orders):
        if self.today_ind < self.low_n:
            return
        floor_low = float(self.kl_pd.low.iloc[self.today_ind - self.low_n : self.today_ind].min())
        for order in orders:
            if today.close < floor_low:
                self.sell_tomorrow(order)
