import numpy as np
import pandas as pd
import pytest

from coin_selector.scorer import compute_factors, score_pool


def make_df(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    vols = volumes or [1000.0] * n
    idx = pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC")
    df = pd.DataFrame(
        {
            "date": idx,
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": vols,
        }
    )
    return df


def test_compute_factors_uptrend_has_positive_ema_slope():
    # 单调上涨 -> EMA20 > EMA50 -> 斜率为正; 波动小
    closes = [100 + i * 0.5 for i in range(100)]
    f = compute_factors(make_df(closes), lookback=100)
    assert f["ema_slope"] > 0
    assert f["roc"] > 0
    assert f["turnover"] > 0
    assert f["atr_pct"] > 0


def test_score_pool_ranks_higher_trend_first():
    rising = make_df([100 + i * 1.0 for i in range(100)], volumes=[2000.0] * 100)
    flat = make_df([100.0] * 100, volumes=[1000.0] * 100)
    scored = score_pool({"A/USDT:USDT": rising, "B/USDT:USDT": flat})
    assert scored.loc["A/USDT:USDT", "score"] > scored.loc["B/USDT:USDT", "score"]


def test_score_pool_volatility_inverted_u():
    # 波动极小与波动极大都应低于波动适中 (以中位数为锚)
    n = 100
    base = [100.0] * n
    low_vol = make_df(base, volumes=[1000.0] * n)
    med_vol = make_df([100 + (5 if i % 2 else -5) for i in range(n)], volumes=[1000.0] * n)
    high_vol = make_df([100 + (30 if i % 2 else -30) for i in range(n)], volumes=[1000.0] * n)
    scored = score_pool(
        {"L/USDT:USDT": low_vol, "M/USDT:USDT": med_vol, "H/USDT:USDT": high_vol},
        weights=(0.0, 0.0, 1.0),  # 只测波动因子
    )
    # 中位 ATR% 的币应得分最高 (倒 U)
    best = scored["score"].idxmax()
    assert best == "M/USDT:USDT"
