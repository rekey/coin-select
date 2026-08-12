"""第一级初筛: 基于 24h ticker 数据过滤全市场."""
import logging

logger = logging.getLogger(__name__)


def screen_tickers(
    tickers: dict[str, dict],
    min_volume: float = 5e6,
    min_change: float | None = None,
    max_change: float | None = None,
    top_n: int = 75,
) -> list[str]:
    """按 24h quoteVolume 降序取前 top_n; 涨跌幅越界与低成交量剔除.

    min_change/max_change 为 None 表示不启用该侧过滤 (默认仅剔极端, max_change=40).
    """
    candidates: list[tuple[str, dict]] = []
    for pair, t in tickers.items():
        vol = t.get("quoteVolume")
        pct = t.get("percentage")
        if vol is None or vol < min_volume:
            continue
        if pct is not None and min_change is not None and pct < min_change:
            continue
        if pct is not None and max_change is not None and pct > max_change:
            continue
        candidates.append((pair, t))

    candidates.sort(key=lambda kv: kv[1].get("quoteVolume") or 0.0, reverse=True)
    result = [pair for pair, _ in candidates[:top_n]]
    if len(result) < top_n:
        logger.warning(f"初筛池不足 {top_n}: 仅 {len(result)} 个 (可放宽 --min-volume)")
    return result
