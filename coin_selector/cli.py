"""CLI 入口: 默认选币 / export-data / export-whitelist."""
import argparse
import logging
from pathlib import Path

from coin_selector.feather_writer import ohlcv_to_feather
from coin_selector.fetcher import Fetcher
from coin_selector.pipeline import select_top
from coin_selector.writer import DEFAULT_REFRESH_PERIOD, export_whitelist, write_pairlist, write_report

logger = logging.getLogger("coin_selector")


def _add_common(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--exchange", default="binance", help="交易所 id (默认 binance)")
    ap.add_argument("--verbose", action="store_true", help="详细日志")


def _build_fetcher(args: argparse.Namespace) -> Fetcher:
    """按 --exchange 构造 Fetcher; 默认 binance 时无参构造 (内置 ccxt binance swap)."""
    if args.exchange and args.exchange != "binance":
        import ccxt

        cls = getattr(ccxt, args.exchange)
        return Fetcher(exchange=cls({"options": {"defaultType": "swap"}}))
    return Fetcher()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="coin-selector", description="多因子选币 (全市场 USDT 永续 -> top N)")
    ap.add_argument("--version", action="version", version="coin-selector 0.1.0")
    _add_common(ap)
    sub = ap.add_subparsers(dest="command")

    # 默认: 选币
    ap.add_argument("--top", type=int, default=30, help="最终保留币数 (默认 30)")
    ap.add_argument("--out", type=Path, default=Path("user_data_v4"), help="输出目录 (pairlist.json 写入此目录)")
    ap.add_argument("--report", type=Path, default=None, help="选币报告 CSV 路径 (可选)")
    ap.add_argument("--pairs-file", type=Path, default=None, help="输入 pairlist.json (供子命令复用)")
    ap.add_argument("--prescreen-size", type=int, default=75, help="初筛池大小 (默认 75)")
    ap.add_argument("--min-volume", type=float, default=5e6, help="24h 成交额下限 (默认 500 万 USDT)")
    ap.add_argument("--min-change", type=float, default=None, help="24h 涨跌幅下限 (可选)")
    ap.add_argument("--max-change", type=float, default=40.0, help="24h 涨跌幅上限 (默认 40%%)")
    ap.add_argument("--timeframe", default="30m", help="K 线周期 (默认 30m)")
    ap.add_argument("--lookback", type=int, default=500, help="K 线根数 (默认 500)")
    ap.add_argument("--refresh-period", type=int, default=DEFAULT_REFRESH_PERIOD,
                    help=f"pairlist 刷新周期秒数 (默认 {DEFAULT_REFRESH_PERIOD})")
    ap.add_argument("--weights", default="0.45,0.30,0.25", help="权重 趋势,流动性,波动率 (默认 0.45,0.30,0.25)")

    p_export = sub.add_parser("export-data", help="从币安拉缺失币 K 线写 freqtrade feather")
    p_export.add_argument("--data-dir", type=Path, default=Path("user_data_v4/data"), help="feather 输出目录")
    p_export.add_argument("--interval", default="30m", help="K 线周期 (默认 30m)")
    p_export.add_argument("--limit", type=int, default=500, help="K 线根数 (默认 500)")
    p_export.add_argument("--pairs", nargs="*", default=None, help="指定币 (默认读取 --pairs-file; 两者皆无则拉全市场 USDT 永续, 耗时长)")

    p_wl = sub.add_parser("export-whitelist", help="把 pairlist.json 的币写为回测配置 pair_whitelist")
    p_wl.add_argument("--config", type=Path, required=True, help="回测配置 JSON 路径")

    return ap


def main(argv: list[str] | None = None) -> int:
    import json

    ap = build_parser()
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    if args.command == "export-whitelist":
        if not args.pairs_file:
            ap.error("export-whitelist 需要 --pairs-file")

        pairs = json.loads(args.pairs_file.read_text())["pairs"]
        export_whitelist(pairs, args.config)
        return 0

    if args.command == "export-data":
        fetcher = _build_fetcher(args)
        if args.pairs:
            pairs = args.pairs
        elif args.pairs_file:
            pairs = json.loads(args.pairs_file.read_text())["pairs"]
        else:
            pairs = list(fetcher.fetch_tickers().keys())
            logger.warning(f"未提供 --pairs 且无 --pairs-file, 回退拉全市场 {len(pairs)} 币")
        frames = fetcher.fetch_ohlcv_batch(pairs, timeframe=args.interval, limit=args.limit)
        written = 0
        for pair, raw in frames.items():
            if ohlcv_to_feather(raw, pair, args.interval, args.data_dir):
                written += 1
        logger.info(f"export-data 完成: {written}/{len(pairs)} 币")
        return 0

    # 默认: 选币
    try:
        weights = tuple(float(x) for x in args.weights.split(","))
        if len(weights) != 3:
            ap.error("--weights 需为逗号分隔的 3 个数字")
    except ValueError:
        ap.error("--weights 需为逗号分隔的 3 个数字")
    fetcher = _build_fetcher(args)
    top, scored = select_top(
        fetcher, top_n=args.top, prescreen_size=args.prescreen_size,
        min_volume=args.min_volume, min_change=args.min_change, max_change=args.max_change,
        timeframe=args.timeframe, lookback=args.lookback, weights=weights,
    )
    write_pairlist(top, args.out / "pairlist.json", refresh_period=args.refresh_period)
    if args.report:
        write_report(scored, args.report)
    logger.info(f"选币完成: top {len(top)} -> {args.out / 'pairlist.json'}")
    return 0
