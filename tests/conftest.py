"""FakeExchange: 模拟 ccxt binance swap 的 fetch_tickers / fetch_ohlcv / load_markets."""


class FakeExchange:
    def __init__(self, tickers: dict | None = None, markets: dict | None = None):
        self._tickers = tickers or {}
        self._markets = markets or {}
        self._ohlcv = {}
        self._calls: list[str] = []

    def load_markets(self):
        return self._markets

    def fetch_tickers(self):
        self._calls.append("fetch_tickers")
        return self._tickers

    def fetch_ohlcv(self, pair, timeframe="30m", limit=None, since=None):
        self._calls.append(f"fetch_ohlcv:{pair}")
        return self._ohlcv.get(pair, [])


def make_market(symbol: str, quote: str = "USDT", active: bool = True, swap: bool = True) -> dict:
    return {"symbol": symbol, "quote": quote, "active": active, "swap": swap, "type": "swap" if swap else "spot"}
