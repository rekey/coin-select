# coin-selector

多因子选币工具：从币安全市场 USDT 永续合约中，按趋势/动量、流动性、波动率三因子综合打分，选出 top N 币种，输出供 freqtrade `RemotePairList` 消费的 `pairlist.json`，实现无需重启的动态换币。

## 特性

- 两级筛选：先用 24h 成交额/涨跌幅从全市场初筛 50–100 个币，再用 30m K 线三因子打分精选 top 30
- 三因子加权：趋势/动量 (0.45) + 流动性/成交额 (0.30) + 波动率 (0.25，倒 U 映射，波动适中者优先)
- 与 freqtrade 解耦：独立 Python 包，仅依赖 `ccxt`、`pandas`、`numpy`、`pyarrow`
- 手动执行、幂等：重复运行覆盖同一 `pairlist.json`，不影响已运行的容器
- 附带选币报告（`selection_report.csv`），可人工检查选币合理性
- 附带 `export-data` 子命令：从币安补拉缺失币的 K 线，输出 freqtrade 标准 feather 文件（供回测使用）

## 环境要求

- Python >= 3.11（宿主机实测 3.13）
- 可访问 Binance API（默认 `api3.binance.com`）

## 安装

```bash
cd coin-selector
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## 快速开始

### 1. 选币并输出币列表

```bash
cd coin-selector
.venv/bin/python -m coin_selector --top 30 --out ../user_data_v4/ \
    --report ../user_data_v4/selection_report.csv
```

执行后生成：

- `../user_data_v4/pairlist.json` — 供 freqtrade-v4 容器读取的币列表（RemotePairList 格式）
- `../user_data_v4/selection_report.csv` — 每币各因子原始值 + 综合分 + 排名

### 2. 启动 freqtrade-v4 容器

```bash
cd /root/freqtrade
docker compose up -d freqtrade-v4
```

容器内 `RemotePairList` 每 1800 秒（30 分钟）自动重新读取 `pairlist.json`，无需重启即可换币。手动更新币列表后，等待一个刷新周期即可看到 whitelist 变化。

### 3. 回测数据准备（可选）

选币池中的币若在 pgsql 中无 K 线数据，可从币安补拉并输出为 freqtrade feather 文件：

```bash
cd coin-selector
.venv/bin/python -m coin_selector --pairs-file ../user_data_v4/pairlist.json \
    export-data --data-dir ../user_data_v4/data --interval 30m --limit 500
```

### 4. 导出回测配置（可选）

把当前 top N 写为回测配置的静态 `pair_whitelist`（动态 pairlist 在回测模式下不生效）：

```bash
cd coin-selector
.venv/bin/python -m coin_selector --pairs-file ../user_data_v4/pairlist.json \
    export-whitelist --config ../user_data_v4/backtest-config.json
```

## 命令与参数

### 主命令：选币

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--top` | 30 | 最终保留的币数 |
| `--out` | `user_data_v4` | 输出目录（`pairlist.json` 写入此目录） |
| `--report` | 无 | 选币报告 CSV 路径（可选） |
| `--prescreen-size` | 75 | 初筛池大小（ticker 层保留的币数） |
| `--min-volume` | 5000000 | 24h 成交额下限 (USDT)，剔除无流动性币 |
| `--min-change` | 无 | 24h 涨跌幅下限（可选，不启用则不过滤） |
| `--max-change` | 40.0 | 24h 涨跌幅上限（%），剔除极端暴涨币 |
| `--timeframe` | `30m` | 打分用 K 线周期 |
| `--lookback` | 500 | 打分用 K 线根数（30m × 500 ≈ 10.4 天） |
| `--weights` | `0.45,0.30,0.25` | 权重（趋势/动量、流动性/成交额、波动率），逗号分隔 3 个数 |
| `--exchange` | `binance` | 交易所 id（默认 binance，仅支持支持 `defaultType=swap` 的交易所） |
| `--verbose` | 关 | 输出详细日志 |

### 子命令：export-data

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--data-dir` | `user_data_v4/data` | feather 输出目录 |
| `--interval` | `30m` | K 线周期 |
| `--limit` | 500 | K 线根数 |
| `--pairs` | 无 | 指定币列表（默认读取 `--pairs-file`；两者皆无则拉全市场，耗时长） |

### 子命令：export-whitelist

| 参数 | 必填 | 说明 |
|------|------|------|
| `--config` | 是 | 目标回测配置 JSON 路径（会改写其 `exchange.pair_whitelist`） |

> 注意：`--pairs-file` 是全局参数，需放在子命令之前，如：
> `.venv/bin/python -m coin_selector --pairs-file pairlist.json export-data --data-dir data`

## 选币原理

```
全市场 USDT 永续 (约 680+)
  │ 1. fetch_tickers() 一次拉全市场 24h 成交额 / 涨跌幅
  ▼
第一级初筛 screeners
  │  成交量 ≥ min_volume，涨跌幅在 [min_change, max_change] 内
  │  按成交额降序取前 prescreen-size (默认 75)
  ▼
第二级打分 scorer（每币拉 30m K 线 500 根）
  │  趋势/动量: EMA20/EMA50 斜率 + 12h ROC
  │  流动性:    区间成交额 sum(close × volume)
  │  波动率:    ATR(14)%（以池中位数为锚，偏离越远分越低）
  │  归一化 → 加权 → 综合分
  ▼
top N (默认 30) → pairlist.json
```

## 与 freqtrade-v4 容器的联动

- `coin-selector` 与 freqtrade 完全解耦，运行在宿主机独立 venv 中
- v4 容器配置（`user_data_v4/config.json`，不入库）使用 freqtrade 内置 `RemotePairList`：

```json
{
  "pairlists": [
    {
      "method": "RemotePairList",
      "pairlist_url": "file:////freqtrade/user_data/pairlist.json",
      "refresh_period": 1800,
      "number_assets": 30,
      "keep_pairlist_on_failure": true
    }
  ]
}
```

- `pairlist_url` 使用四斜杠 `file:////`：freqtrade 按 `split("file:///", 1)[1]` 解析，三斜杠会吞掉前导 `/` 导致路径错误、容器启动崩溃
- 每次手动选币后，v4 容器会在下一个刷新周期（默认 1800 秒）自动采用新列表，无需 reload 或重启
- 回测时动态 pairlist 不生效，需先用 `export-whitelist` 导出静态 `pair_whitelist` 快照

## Docker 使用

也可以把 coin-selector 封装成 Docker 镜像运行（仅容器化手动执行，不绑定宿主机路径）。

### 构建镜像

```bash
cd /root/freqtrade
docker build -t rekey/coin-selector:latest coin-selector/
```

镜像基于 `python:3.13-slim`，自包含代码与依赖（ccxt/pandas/numpy/pyarrow），入口为 `python -m coin_selector`。

### 手动选币

```bash
# 挂载宿主机目录到容器 /data, 输出写到宿主机 user_data_v4/
docker run --rm -v /root/freqtrade/user_data_v4:/data \
  rekey/coin-selector:latest --out /data --top 30 --report /data/selection_report.csv
```

执行后生成宿主机 `user_data_v4/pairlist.json` 与 `selection_report.csv`（v4 容器挂载同一目录，自动读取新列表）。

### 回测数据补充

```bash
# export-data 子命令同样可用
docker run --rm -v /root/freqtrade/user_data_v4:/data \
  rekey/coin-selector:latest --pairs-file /data/pairlist.json export-data \
  --data-dir /data/data --interval 30m --limit 500
```

### 说明

- 镜像不绑定任何宿主机路径：`--out` / `--data-dir` 由 `docker run` 时通过 `-v` 挂载目录传入
- 容器需能访问 Binance API（默认 `api3.binance.com`），`docker run` 默认有外网
- 本镜像不含 tests（`tests/` 已通过 `.dockerignore` 排除）；单测在宿主机 venv 运行
- 若需 push 到 Docker Hub：`docker push rekey/coin-selector:latest`

## 测试

```bash
cd coin-selector
.venv/bin/python -m pytest tests/ -v
```

## 常见问题

- **选出的币有些很小众？** 趋势权重占 0.45，动量强的币即使成交额不大也会入选。可用 `--weights` 调低趋势权重，或提高 `--min-volume`。
- **拉取 K 线很慢？** 初筛池默认 75 个币，逐币串行拉取约 30 秒；若仍需提速，可减小 `--prescreen-size`。
- **某个币拉取失败？** `export-data` 与选币流程都会跳过失败币并记日志，不影响整体。
