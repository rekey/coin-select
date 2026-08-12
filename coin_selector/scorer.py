"""第二级打分: 30m K 线三因子 (趋势/流动性/波动率) 加权综合分."""
import numpy as np
import pandas as pd

DEFAULT_WEIGHTS = (0.45, 0.30, 0.25)  # 趋势/动量, 流动性/成交额, 波动率


def compute_factors(df: pd.DataFrame, lookback: int = 500) -> dict[str, float]:
    """单币因子: ema_slope, roc, turnover, atr_pct."""
    close = df["close"].astype(float)
    high, low = df["high"].astype(float), df["low"].astype(float)
    vol = df["volume"].astype(float)

    ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    ema_slope = ema20 / ema50 - 1.0 if ema50 != 0 else 0.0

    roc_n = min(24, len(close) - 1)
    roc = close.iloc[-1] / close.iloc[-1 - roc_n] - 1.0 if close.iloc[-1 - roc_n] != 0 else 0.0

    turnover = float((close * vol).tail(lookback).sum())

    # ATR(14) 百分比
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean().iloc[-1]
    atr_pct = atr / close.iloc[-1] if close.iloc[-1] != 0 else 0.0

    return {
        "ema_slope": float(ema_slope),
        "roc": float(roc),
        "turnover": turnover,
        "atr_pct": float(atr_pct),
    }


def _minmax(s: pd.Series) -> pd.Series:
    rng = s.max() - s.min()
    if rng == 0 or np.isnan(rng):
        return pd.Series(0.5, index=s.index)
    return (s - s.min()) / rng


def _inverted_u(s: pd.Series) -> pd.Series:
    """以中位数为锚, 偏离越远分越低, 输出 [0,1]."""
    med = s.median()
    spread = s.max() - s.min()
    if spread == 0 or np.isnan(spread):
        return pd.Series(0.5, index=s.index)
    return 1.0 - (s - med).abs() / spread


def score_pool(
    frames: dict[str, pd.DataFrame],
    weights: tuple[float, float, float] = DEFAULT_WEIGHTS,
    lookback: int = 500,
) -> pd.DataFrame:
    """跨候选池: 因子归一化 -> 加权综合分 -> 排序 DataFrame (index=pair)."""
    w_trend, w_liq, w_vol = weights
    rows = {pair: compute_factors(df, lookback) for pair, df in frames.items()}
    out = pd.DataFrame.from_dict(rows, orient="index")

    trend = _minmax(out["ema_slope"]) * 0.5 + _minmax(out["roc"]) * 0.5  # 组内动量合成
    liq = _minmax(out["turnover"])
    vol = _inverted_u(out["atr_pct"])

    out["z_trend"], out["z_liq"], out["z_vol"] = trend, liq, vol
    out["score"] = w_trend * trend + w_liq * liq + w_vol * vol
    return out.sort_values("score", ascending=False)
