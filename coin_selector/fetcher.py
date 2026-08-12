"""ccxt 封装: 全市场 USDT 永续 ticker 与 OHLCV, 含限速与重试."""
import logging
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def rewrite_api_urls(exchange, api_base: str) -> None:
    """把 exchange 所有 API URL 的 host 替换为 api_base (保留协议与路径).

    用于通过反代域名访问币安 (如 bapi.beasi.top), 规避地域限制.
    """
    api = getattr(exchange, "urls", {}).get("api")
    if not api:
        return
    for key, url in api.items():
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            api[key] = f"{parsed.scheme}://{api_base}{parsed.path}"


class Fetcher:
    def __init__(self, exchange=None, rate_limit: float = 0.25, max_retries: int = 2,
                 api_base: str | None = None):
        if exchange is None:
            import ccxt

            exchange = ccxt.binance({"options": {"defaultType": "swap"}})
        self.exchange = exchange
        self.rate_limit = rate_limit
        self.max_retries = max_retries
        if api_base:
            rewrite_api_urls(exchange, api_base)
            logger.info(f"币安 API host 已替换为 {api_base}")

    def _usdt_swap_pairs(self) -> set[str]:
        markets = self.exchange.load_markets()
        return {
            s
            for s, m in markets.items()
            if m.get("quote") == "USDT" and m.get("swap") and m.get("active", True)
        }

    def fetch_tickers(self) -> dict[str, dict]:
        """返回全市场 ticker, 仅保留 USDT 永续合约."""
        tickers = self.exchange.fetch_tickers()
        keep = self._usdt_swap_pairs()
        return {k: v for k, v in tickers.items() if k in keep}

    def fetch_ohlcv(self, pair: str, timeframe: str = "30m", limit: int = 500) -> list[list]:
        """拉取单币 OHLCV, 失败重试 2 次 (退避 1s/3s), 每次调用间限速."""
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                data = self.exchange.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
                time.sleep(self.rate_limit)
                return data
            except Exception as e:  # noqa: BLE001 - ccxt 异常种类多
                last_err = e
                if attempt < self.max_retries:
                    time.sleep(1 + 2 * attempt)
        raise last_err

    def fetch_ohlcv_batch(
        self, pairs: list[str], timeframe: str = "30m", limit: int = 500
    ) -> dict[str, list[list]]:
        """逐币拉取 OHLCV; 单币失败跳过并记日志 (不中断整体)."""
        result: dict[str, list[list]] = {}
        for pair in pairs:
            try:
                result[pair] = self.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"拉取 {pair} OHLCV 失败, 跳过: {e}")
        return result
