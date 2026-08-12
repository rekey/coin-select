"""输出: RemotePairList 格式 pairlist.json (原子写) / selection_report.csv / 回测 whitelist."""
import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_REFRESH_PERIOD = 300  # 与 GitHub Actions 每 5 分钟选币节奏匹配


def write_pairlist(pairs: list[str], out_path: Path, refresh_period: int = DEFAULT_REFRESH_PERIOD) -> Path:
    """原子写 pairlist.json (先写临时文件再 rename), 失败保留旧文件."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"pairs": pairs, "refresh_period": refresh_period}
    fd, tmp = tempfile.mkstemp(dir=str(out_path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, out_path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    logger.info(f"已写出 {out_path} ({len(pairs)} pairs)")
    return out_path


def write_report(df, csv_path: Path) -> None:
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index_label="pair")
    logger.info(f"选币报告已写出 {csv_path}")


def export_whitelist(pairs: list[str], config_path: Path) -> None:
    """把 top N 写为回测配置的 exchange.pair_whitelist (保留其余字段)."""
    config_path = Path(config_path)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    cfg.setdefault("exchange", {})
    cfg["exchange"]["pair_whitelist"] = pairs
    config_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"已更新回测配置 whitelist: {config_path} ({len(pairs)} pairs)")
