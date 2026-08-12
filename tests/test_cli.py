import json
from pathlib import Path

from coin_selector.cli import main


def test_cli_select_top_writes_pairlist(tmp_path: Path, monkeypatch):
    # 用 FakeExchange 注入, 避免真实网络请求
    from coin_selector.fetcher import Fetcher
    from tests.conftest import FakeExchange, make_market

    ex = FakeExchange(
        markets={"A/USDT:USDT": make_market("A/USDT:USDT")},
        tickers={"A/USDT:USDT": {"symbol": "A/USDT:USDT", "quoteVolume": 1e9, "percentage": 1.0}},
    )
    ex._ohlcv = {"A/USDT:USDT": [[1700000000000, 100, 101, 99, 100.5, 1000.0] * 1]}
    # 500 根合成数据
    import pandas as pd

    closes = [100 + i * 0.1 for i in range(500)]
    ex._ohlcv = {
        "A/USDT:USDT": [
            [1700000000000 + i * 1_800_000, closes[i], closes[i] * 1.01, closes[i] * 0.99, closes[i], 1000.0]
            for i in range(500)
        ]
    }
    monkeypatch.setattr(Fetcher, "__init__", lambda self, exchange=None, rate_limit=0.0, max_retries=0: (setattr(self, "exchange", ex), setattr(self, "rate_limit", 0.0), setattr(self, "max_retries", 0))[2])

    out_dir = tmp_path / "out"
    rc = main(
        [
            "--top", "1",
            "--out", str(out_dir),
            "--report", str(tmp_path / "report.csv"),
        ]
    )
    assert rc == 0
    data = json.loads((out_dir / "pairlist.json").read_text())
    assert len(data["pairs"]) == 1
    assert (tmp_path / "report.csv").exists()


def test_cli_export_whitelist(tmp_path: Path):
    pl = tmp_path / "pairlist.json"
    pl.write_text(json.dumps({"pairs": ["BTC/USDT:USDT"]}))
    cfg = tmp_path / "backtest-config.json"
    cfg.write_text(json.dumps({"exchange": {"pair_whitelist": []}}))
    rc = main(["--pairs-file", str(pl), "export-whitelist", "--config", str(cfg)])
    assert rc == 0
    assert json.loads(cfg.read_text())["exchange"]["pair_whitelist"] == ["BTC/USDT:USDT"]


def test_cli_export_data_writes_feather(tmp_path: Path, monkeypatch):
    from coin_selector.fetcher import Fetcher
    from tests.conftest import FakeExchange, make_market

    closes = [100.0 + i * 0.1 for i in range(5)]
    ex = FakeExchange(
        markets={"A/USDT:USDT": make_market("A/USDT:USDT")},
        tickers={"A/USDT:USDT": {"symbol": "A/USDT:USDT", "quoteVolume": 1e9, "percentage": 1.0}},
    )
    ex._ohlcv = {
        "A/USDT:USDT": [
            [1700000000000 + i * 1_800_000, closes[i], closes[i] * 1.01, closes[i] * 0.99, closes[i], 1000.0]
            for i in range(5)
        ]
    }
    monkeypatch.setattr(
        Fetcher, "__init__",
        lambda self, exchange=None, rate_limit=0.0, max_retries=0: (
            setattr(self, "exchange", ex),
            setattr(self, "rate_limit", 0.0),
            setattr(self, "max_retries", 0),
        )[2],
    )

    pl = tmp_path / "pairlist.json"
    pl.write_text(json.dumps({"pairs": ["A/USDT:USDT"]}))
    data_dir = tmp_path / "data"
    rc = main(["--pairs-file", str(pl), "export-data", "--data-dir", str(data_dir), "--interval", "30m", "--limit", "5"])
    assert rc == 0
    feather = data_dir / "binance" / "futures" / "A_USDT_USDT-30m-futures.feather"
    assert feather.exists()


def test_cli_refresh_period_flag(tmp_path: Path, monkeypatch):
    # 注入 FakeExchange, 验证 --refresh-period 写入 pairlist.json
    from coin_selector.fetcher import Fetcher
    from tests.conftest import FakeExchange, make_market

    closes = [100 + i * 0.1 for i in range(500)]
    ex = FakeExchange(
        markets={"A/USDT:USDT": make_market("A/USDT:USDT")},
        tickers={"A/USDT:USDT": {"symbol": "A/USDT:USDT", "quoteVolume": 1e9, "percentage": 1.0}},
    )
    ex._ohlcv = {
        "A/USDT:USDT": [
            [1700000000000 + i * 1_800_000, closes[i], closes[i] * 1.01, closes[i] * 0.99, closes[i], 1000.0]
            for i in range(500)
        ]
    }
    monkeypatch.setattr(
        Fetcher, "__init__",
        lambda self, exchange=None, rate_limit=0.0, max_retries=0: (
            setattr(self, "exchange", ex),
            setattr(self, "rate_limit", 0.0),
            setattr(self, "max_retries", 0),
        )[2],
    )

    out_dir = tmp_path / "out"
    rc = main(["--top", "1", "--out", str(out_dir), "--refresh-period", "600"])
    assert rc == 0
    data = json.loads((out_dir / "pairlist.json").read_text())
    assert data["refresh_period"] == 600
