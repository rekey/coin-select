import json
from pathlib import Path

from coin_selector.writer import DEFAULT_REFRESH_PERIOD, export_whitelist, write_pairlist, write_report


def test_write_pairlist_atomic_and_format(tmp_path: Path):
    pairs = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    out = write_pairlist(pairs, tmp_path / "pairlist.json")
    data = json.loads(out.read_text())
    assert data == {"pairs": pairs, "refresh_period": DEFAULT_REFRESH_PERIOD}


def test_write_pairlist_overwrites_previous(tmp_path: Path):
    f = tmp_path / "pairlist.json"
    write_pairlist(["A/USDT:USDT"], f)
    write_pairlist(["B/USDT:USDT"], f)
    assert json.loads(f.read_text())["pairs"] == ["B/USDT:USDT"]


def test_write_report_csv(tmp_path: Path):
    import pandas as pd

    df = pd.DataFrame({"pair": ["A/USDT:USDT"], "score": [0.9]})
    p = tmp_path / "report.csv"
    write_report(df, p)
    assert "A/USDT:USDT" in p.read_text()


def test_export_whitelist_updates_config(tmp_path: Path):
    cfg = tmp_path / "backtest-config.json"
    cfg.write_text(json.dumps({"strategy": "X", "exchange": {"pair_whitelist": [], "pair_blacklist": []}}))
    export_whitelist(["BTC/USDT:USDT"], cfg)
    data = json.loads(cfg.read_text())
    assert data["exchange"]["pair_whitelist"] == ["BTC/USDT:USDT"]
