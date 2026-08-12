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

容器内 `RemotePairList` 每 300 秒（5 分钟）自动重新读取 `pairlist.json`，无需重启即可换币。手动更新币列表后，等待一个刷新周期即可看到 whitelist 变化。

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
| `--refresh-period` | 300 | pairlist 刷新周期（秒），与 freqtrade RemotePairList 轮询节奏一致 |
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
      "refresh_period": 300,
      "number_assets": 30,
      "keep_pairlist_on_failure": true
    }
  ]
}
```

- `pairlist_url` 使用四斜杠 `file:////`：freqtrade 按 `split("file:///", 1)[1]` 解析，三斜杠会吞掉前导 `/` 导致路径错误、容器启动崩溃
- 每次手动选币后，v4 容器会在下一个刷新周期（默认 300 秒）自动采用新列表，无需 reload 或重启
- 回测时动态 pairlist 不生效，需先用 `export-whitelist` 导出静态 `pair_whitelist` 快照

> `refresh_period` 需与选币节奏匹配（默认 300 秒 = 5 分钟）。注意 RemotePairList 响应 JSON 里的 `refresh_period` 字段会覆盖容器配置，因此 `pairlist.json` 内的值（由 `--refresh-period` 控制，默认 300）与容器配置需保持一致。

## 自动化选币（GitHub Actions）

仓库公开部署后，GitHub Actions 每 5 分钟自动选币一次，选完通过 curl 触发你服务器上的 webhook 执行 `git pull`，freqtrade 在下一个轮询周期（300 秒）内自动换币，全程无需人工干预。

### 架构

```
GitHub Actions（公开仓库, 无限免费额度）
  schedule cron '2-59/5 * * * *'（每 5 分钟, 错峰避开整点）+ 手动 workflow_dispatch
  │ checkout → pip install . → 币安连通性探测
  │ python -m coin_selector --out ./out --report ./out/selection_report.csv
  │ 结果变化才 commit + push (pairlist.json + selection_report.csv)
  ▼
curl -X POST <webhook URL> -H "X-Webhook-Token: <token>"（重试 3 次）
  ▼
服务器 webhook 端点（adnanh/webhook 等）
  校验 token → git pull 公开仓库 → cp 到 user_data_v4/
  ▼
freqtrade RemotePairList 每 300s 读本地 pairlist.json → whitelist 自动更新
```

全链路延迟：选币完成 → commit（秒级）→ curl 触发 → git pull（秒级）→ freqtrade 轮询（≤300s），最坏约 5 分钟。git pull 走 git 协议直达 GitHub，无 raw CDN 缓存问题。

### 启用步骤

1. **搭建服务器 webhook 端点**（见下文参考方案），记录 URL 与 token
2. **配置 GitHub secret**：仓库 Settings → Secrets and variables → Actions，新增 `WEBHOOK_TOKEN`（与服务器端一致）
3. **填写 URL**：编辑 `webhook.config.json` 的 `url` 字段并 push
4. **手动验证**：仓库 Actions 页 → select-pairs → Run workflow（workflow_dispatch），观察选币/commit/触发三步日志

未配置 secret 或 URL 为空时，workflow 跳过触发步骤并输出 warning（不影响选币与 commit）。

### 服务器 webhook 参考方案（adnanh/webhook）

```bash
# 一次性: 预 clone 公开仓库到 /root/freqtrade/coin-select-results
git clone https://github.com/<owner>/<repo>.git /root/freqtrade/coin-select-results

# 启动 webhook 容器
docker run -d --name webhook --restart unless-stopped \
  -v /root/freqtrade:/freqtrade \
  -v /root/webhook/hooks.yaml:/etc/webhook/hooks.yaml \
  adnanh/webhook -hooks /etc/webhook/hooks.yaml -verbose
```

`/root/webhook/hooks.yaml`（chmod 600，token 与 `WEBHOOK_TOKEN` 相同）:

```yaml
- id: pairlist-updated
  execute-command: /usr/local/bin/pull-pairlist.sh
  trigger-rule:
    match:
      - type: header-match
        name: X-Webhook-Token
        value: <与 WEBHOOK_TOKEN 相同的随机串>
```

`/usr/local/bin/pull-pairlist.sh`（挂载进容器或内置于镜像）:

```bash
#!/bin/bash
set -e
git -C /freqtrade/coin-select-results pull --ff-only origin main
cp /freqtrade/coin-select-results/pairlist.json /freqtrade/user_data_v4/pairlist.json
cp /freqtrade/coin-select-results/selection_report.csv /freqtrade/user_data_v4/selection_report.csv
```

### 接口契约

| 项 | 约定 |
|----|------|
| 方法 | `POST` |
| 认证 | header `X-Webhook-Token`，与 `WEBHOOK_TOKEN` 一致 |
| 成功 | 返回 2xx |
| token 不匹配 | 返回 4xx（workflow 视为失败, 重试 3 次后标红） |
| 执行失败 | 返回 5xx |

### 说明与故障排查

- **schedule 延迟**：GitHub 不保证 cron 精确准时，负载高时可能延迟数分钟；`2-59/5` 已错峰避开整点高峰。对 5 分钟级换币场景足够。
- **commit 噪音**：结果几乎每次微变，一天可能上百个 commit；文件仅几 KB，无影响。如嫌多可后续加"变化超 N 个币才提交"阈值。
- **币安 451**：若 workflow 在连通性探测步骤失败，说明 GitHub Actions 出口 IP 被币安地域限制，需改用自托管 runner 或代理（首次手动 dispatch 即可验证）。
- **服务器离线**：workflow 重试 3 次仍失败会标红告警；commit 已在仓库，服务器恢复后 pull 即可补上（也可手动触发一次）。
- **本地手动模式不受影响**：`file://` 读取方式与手动选币命令照常可用。

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
