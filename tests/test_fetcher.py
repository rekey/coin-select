from coin_selector.fetcher import Fetcher, rewrite_api_urls
from tests.conftest import FakeExchange, make_market


def test_rewrite_api_urls_replaces_host_keeps_path():
    ex = FakeExchange()
    ex.urls = {
        "api": {
            "public": "https://api.binance.com/api/v3",
            "fapiPublic": "https://fapi.binance.com/fapi/v1",
            "dapiPublic": "https://dapi.binance.com/dapi/v1",
        }
    }
    rewrite_api_urls(ex, "bapi.beasi.top")
    assert ex.urls["api"]["public"] == "https://bapi.beasi.top/api/v3"
    assert ex.urls["api"]["fapiPublic"] == "https://bapi.beasi.top/fapi/v1"
    assert ex.urls["api"]["dapiPublic"] == "https://bapi.beasi.top/dapi/v1"


def test_fetcher_api_base_applied_to_exchange():
    ex = FakeExchange()
    ex.urls = {
        "api": {
            "public": "https://api.binance.com/api/v3",
            "fapiPublic": "https://fapi.binance.com/fapi/v1",
        }
    }
    Fetcher(exchange=ex, api_base="bapi.beasi.top")
    assert ex.urls["api"]["public"].startswith("https://bapi.beasi.top/")


def test_fetcher_no_api_base_keeps_original():
    ex = FakeExchange()
    ex.urls = {"api": {"public": "https://api.binance.com/api/v3"}}
    Fetcher(exchange=ex)
    assert ex.urls["api"]["public"] == "https://api.binance.com/api/v3"


def test_fetch_tickers_returns_usdt_swap_only():
    ex = FakeExchange(
        markets={
            "BTC/USDT:USDT": make_market("BTC/USDT:USDT"),
            "ETH/USDT:USDT": make_market("ETH/USDT:USDT"),
            "BTC/USDC:USDC": make_market("BTC/USDC:USDC", quote="USDC"),
            "ETH/USDT": make_market("ETH/USDT", swap=False),
        },
        tickers={
            "BTC/USDT:USDT": {"symbol": "BTC/USDT:USDT", "quoteVolume": 1e9, "percentage": 2.0},
            "ETH/USDT:USDT": {"symbol": "ETH/USDT:USDT", "quoteVolume": 5e8, "percentage": 1.0},
            "BTC/USDC:USDC": {"symbol": "BTC/USDC:USDC", "quoteVolume": 1e8, "percentage": 3.0},
        },
    )
    f = Fetcher(exchange=ex)
    tickers = f.fetch_tickers()
    assert set(tickers.keys()) == {"BTC/USDT:USDT", "ETH/USDT:USDT"}
    assert f.rate_limit >= 0  # 属性存在


def test_fetch_ohlcv_batch_returns_dict():
    ex = FakeExchange()
    ex._ohlcv = {
        "A/USDT:USDT": [[1700000000000, 1, 2, 0.5, 1.5, 100]],
        "B/USDT:USDT": [[1700000000000, 10, 20, 5, 15, 1000]],
    }
    f = Fetcher(exchange=ex)
    frames = f.fetch_ohlcv_batch(["A/USDT:USDT", "B/USDT:USDT"], timeframe="30m", limit=500)
    assert set(frames.keys()) == {"A/USDT:USDT", "B/USDT:USDT"}
    assert frames["A/USDT:USDT"][0][4] == 1.5


def test_fetch_ohlcv_batch_skips_failures():
    class Flaky(FakeExchange):
        def fetch_ohlcv(self, pair, timeframe="30m", limit=None, since=None):
            if pair == "B/USDT:USDT":
                raise ConnectionError("timeout")
            return [[1700000000000, 1, 2, 0.5, 1.5, 100]]

    ex = Flaky()
    f = Fetcher(exchange=ex, max_retries=0)  # 不重试, 直接跳过
    frames = f.fetch_ohlcv_batch(["A/USDT:USDT", "B/USDT:USDT"])
    assert set(frames.keys()) == {"A/USDT:USDT"}
