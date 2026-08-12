from pathlib import Path

import pyarrow.feather as pfeather

from coin_selector.feather_writer import ohlcv_to_feather


def test_ohlcv_to_feather_futures_naming_and_schema(tmp_path: Path):
    raw = [
        [1700000000000, 100.0, 101.0, 99.0, 100.5, 1000.0],
        [1700000180000, 100.5, 102.0, 100.0, 101.0, 1200.0],
    ]
    out = ohlcv_to_feather(raw, "BTC/USDT:USDT", "30m", tmp_path)
    # 合约命名: base_quote_settle-30m-futures.feather
    expected = tmp_path / "binance" / "futures" / "BTC_USDT_USDT-30m-futures.feather"
    assert out == expected and expected.exists()

    t = pfeather.read_table(expected)
    cols = [f.name for f in t.schema]
    assert cols == ["date", "open", "high", "low", "close", "volume"]
    assert str(t.schema.field("date").type) == "timestamp[ms, tz=UTC]"
    assert t.num_rows == 2


def test_ohlcv_to_feather_empty_skips(tmp_path: Path):
    out = ohlcv_to_feather([], "BTC/USDT:USDT", "30m", tmp_path)
    assert out is None
