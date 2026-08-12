from coin_selector.screeners import screen_tickers

TICKERS = {
    "A/USDT:USDT": {"symbol": "A/USDT:USDT", "quoteVolume": 1e8, "percentage": 2.0},
    "B/USDT:USDT": {"symbol": "B/USDT:USDT", "quoteVolume": 5e7, "percentage": 1.0},
    "C/USDT:USDT": {"symbol": "C/USDT:USDT", "quoteVolume": 2e7, "percentage": 0.5},
    "D/USDT:USDT": {"symbol": "D/USDT:USDT", "quoteVolume": 1e6, "percentage": 0.1},  # 低流动性
    "E/USDT:USDT": {"symbol": "E/USDT:USDT", "quoteVolume": 3e7, "percentage": 55.0},  # 极端暴涨
    "F/USDT:USDT": {"symbol": "F/USDT:USDT", "quoteVolume": 3e7, "percentage": -45.0},  # 极端暴跌
}


def test_screen_keeps_top_by_volume_and_drops_extremes():
    result = screen_tickers(TICKERS, min_volume=5e6, min_change=-40.0, max_change=40.0, top_n=3)
    # E(55) 超上界 / F(-45) 低于下界被剔除; D 被成交量剔除; 按 volume 取 top3 = A, B, C
    assert result == ["A/USDT:USDT", "B/USDT:USDT", "C/USDT:USDT"]


def test_screen_min_change_drops_losers():
    result = screen_tickers(TICKERS, min_volume=5e6, min_change=0.5, max_change=40.0, top_n=10)
    assert "B/USDT:USDT" in result  # B 涨 1.0 >= 0.5 保留
    assert "C/USDT:USDT" in result  # C=0.5 >= 0.5 保留
    assert "F/USDT:USDT" not in result  # F=-45.0 被 min_change 剔除 (loser)


def test_screen_insufficient_pool_warns_and_returns_what_it_has():
    result = screen_tickers(TICKERS, min_volume=1e9, top_n=10)
    assert result == []  # 全被过滤, 不抛异常
