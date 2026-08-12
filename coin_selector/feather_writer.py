"""ccxt OHLCV ([[ts,o,h,l,c,v],...]) -> freqtrade feather 文件 (与 scripts/export_pgsql.py 同格式)."""
from pathlib import Path

import pyarrow as pa
import pyarrow.feather as pfeather


def _pair_to_names(pair: str) -> tuple[str, str, str]:
    """ccxt 合约 pair 'BTC/USDT:USDT' -> (base, quote, settle)."""
    base_quote, settle = pair.split(":")
    base, quote = base_quote.split("/")
    return base, quote, settle


def ohlcv_to_feather(raw: list[list], pair: str, interval: str, out_dir: Path) -> Path | None:
    """写 freqtrade feather; 返回输出路径, 空数据返回 None."""
    if not raw:
        return None
    base, quote, settle = _pair_to_names(pair)
    timestamps = pa.array([int(r[0]) for r in raw], type=pa.timestamp("ms", tz="UTC"))
    out = pa.table(
        {
            "date": timestamps,
            "open": pa.array([r[1] for r in raw], type=pa.float64()),
            "high": pa.array([r[2] for r in raw], type=pa.float64()),
            "low": pa.array([r[3] for r in raw], type=pa.float64()),
            "close": pa.array([r[4] for r in raw], type=pa.float64()),
            "volume": pa.array([r[5] for r in raw], type=pa.float64()),
        }
    )
    out_path = (
        Path(out_dir) / "binance" / "futures" / f"{base}_{quote}_{settle}-{interval}-futures.feather"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pfeather.write_feather(out, str(out_path))
    return out_path
