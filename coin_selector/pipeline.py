"""选币主流程: ticker 初筛 -> K 线打分 -> top N."""
import logging

import pandas as pd

from coin_selector.fetcher import Fetcher
from coin_selector.scorer import score_pool
from coin_selector.screeners import screen_tickers

logger = logging.getLogger(__name__)


def select_top(
    fetcher: Fetcher,
    top_n: int = 30,
    prescreen_size: int = 75,
    min_volume: float = 5e6,
    min_change: float | None = None,
    max_change: float | None = 40.0,
    timeframe: str = "30m",
    lookback: int = 500,
    weights: tuple[float, float, float] = (0.45, 0.30, 0.25),
) -> tuple[list[str], object]:
    """返回 (top N pairs, scored DataFrame)."""
    tickers = fetcher.fetch_tickers()
    logger.info(f"全市场 USDT 永续 ticker: {len(tickers)} 个")
    pool = screen_tickers(tickers, min_volume=min_volume, min_change=min_change,
                          max_change=max_change, top_n=prescreen_size)
    logger.info(f"初筛池: {len(pool)} 个")
    frames = fetcher.fetch_ohlcv_batch(pool, timeframe=timeframe, limit=lookback)
    if not frames:
        raise RuntimeError("候选池 K 线全部拉取失败, 中止")
    # raw OHLCV (list[list]) -> DataFrame (score_pool 只接受 DataFrame dict)
    # 跳过空 raw (K 线全空) 的 pair, 避免 compute_factors 对空 DataFrame 取 .iloc[-1] 抛 IndexError
    dframes = {
        pair: pd.DataFrame(
            raw,
            columns=["date", "open", "high", "low", "close", "volume"],
        )
        for pair, raw in frames.items()
        if raw
    }
    skipped = [p for p, raw in frames.items() if not raw]
    for pair in skipped:
        logger.warning(f"跳过 K 线为空的 pair: {pair}")
    if not dframes:
        raise RuntimeError("候选池 K 线全部为空或拉取失败, 中止")
    scored = score_pool(dframes, weights=weights, lookback=lookback)
    top = scored.head(top_n).index.tolist()
    return top, scored
