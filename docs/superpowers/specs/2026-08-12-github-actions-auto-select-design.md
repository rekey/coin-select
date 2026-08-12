# GitHub Actions 自动选币设计

日期: 2026-08-12
状态: 已确认（用户逐节审批通过）

## 背景与目标

coin-selector 目前是宿主机手动执行的选币工具（输出 `pairlist.json` 供 freqtrade RemotePairList 消费）。目标：用 GitHub Actions 定时自动选币，选完通过 curl 触发用户服务器上的 webhook 执行 git pull，实现分钟级换币，无需人工干预。

已确认的关键决策（含调研依据）:

- **触发频率: 每 5 分钟一次**。依据: 币安 24h ticker（热门币列表/初筛池数据）秒级实时更新，币种类实时变化；30m K 线仅是打分用数据。
- **产物回传: commit 回公开仓库 → curl 服务器 webhook → git pull**。git 协议直达 GitHub，无 raw CDN 缓存（raw.githubusercontent.com 有 max-age=300 且无 purge 接口），延迟从"最坏 35 分钟"降到秒级。
- **仓库公开**。GitHub Actions 免费额度为**账户级共享**（私有仓库 2000 分钟/月，账户下所有私有仓库共享），公开仓库标准 runner **无限免费**且不占用账户配额。
- **配置分离: URL 入库、token 走 secret**。公开仓库下 token 不能入库，`webhook.config.json` 只存 URL（空=未启用），token 存 repository secret `WEBHOOK_TOKEN`。
- **freqtrade `refresh_period` 同步调小至 300s**。RemotePairList 响应 JSON 里的 `refresh_period` 字段会覆盖本地配置，pairlist.json 当前写死 1800，不改则 5 分钟选币被 30 分钟轮询吃掉。

## 架构与数据流

```
GitHub Actions（公开仓库，无限额度）
  触发: schedule cron '2-59/5 * * * *'（每 5 分钟, 错峰 2 分钟避开整点高峰）
        + workflow_dispatch（手动立即跑, 用于验证）
  │
  │ ① checkout → setup-python 3.11 → pip install .
  │ ② 币安连通性探测（curl api3.binance.com，451/超时立即失败退出）
  │ ③ python -m coin_selector --out ./out --report ./out/selection_report.csv
  │    （参数对齐默认: --top 30 --prescreen-size 75 --min-volume 5e6
  │       --max-change 40 --timeframe 30m --lookback 500 --refresh-period 300）
  │ ④ diff 与仓库当前 pairlist.json
  │    ├─ 无变化 → 结束（不 commit、不 curl）
  │    └─ 有变化 → commit(pairlist.json + selection_report.csv) + push main
  │ ⑤ 读 webhook.config.json:
  │    ├─ url 为空 → 跳过（未启用, 记日志）
  │    └─ url 非空 → curl -X POST $url -H "X-Webhook-Token: ${{ secrets.WEBHOOK_TOKEN }}"
  │        （重试 3 次, 间隔 10s; 仍失败 → workflow 标红失败）
  ▼
用户服务器 webhook 端点（用户自行搭建, 本文档给建议方案）
  │ 校验 token → git pull（公开仓库无需凭据）
  │ → cp pairlist.json selection_report.csv → /root/freqtrade/user_data_v4/
  ▼
freqtrade RemotePairList 每 300s 读本地 file:///freqtrade/user_data/pairlist.json
  （config.json 的 refresh_period: 1800 → 300）
```

全链路延迟: 选币完成 → commit（秒级）→ curl 触发 → git pull（秒级）→ freqtrade 下一轮询窗口（≤300s）。**最坏约 5 分钟**。

## Workflow 细节 (.github/workflows/select-pairs.yml)

- **触发**: 仅 `schedule` + `workflow_dispatch`。**不用 push 触发**——Actions 自身 commit 回仓库会造成无限循环。
- **权限**: `permissions: contents: write`（GITHUB_TOKEN push 用）。
- **commit 身份**: `github-actions[bot]`，message 带选币时间戳。
- **币安连通性探测**: 第一步先 `curl -sS --max-time 10 https://api3.binance.com/api/v3/ping`，失败即 fail（快速失败, 不选币不动仓库）。此步骤同时验证 Actions 美国节点访问币安无 451 地域限制——若 451 需另议（自托管 runner 或代理）。
- **失败语义**: 任何步骤失败 → job 失败 → 不产生 commit → 服务器旧列表继续生效（freqtrade `keep_pairlist_on_failure: true` 兜底）。

## 配置文件与 secret 约定

新增 `webhook.config.json` 入库（公开仓库, 只含 URL, 无敏感信息）:

```json
{
  "url": "",
  "comment": "服务器 webhook 端点。留空 = 未启用；搭建好端点后填入并 push，下一轮 cron 或手动 dispatch 即生效"
}
```

- token 不进仓库: GitHub repository secret `WEBHOOK_TOKEN`（Settings → Secrets and variables → Actions）。未配置时 workflow 跳过 curl 并记 warning（不 fail）。
- 启用流程: 搭好端点 → 填 URL 并 push → 配一次 secret → 手动 dispatch 验证。
- workflow 内: URL 从文件读, token 从 `${{ secrets.WEBHOOK_TOKEN }}` 读, 两者齐备才执行 curl。

## 服务器侧建议（用户搭建, 本文档给参考方案）

接口契约（README 写明）:

- 方法: `POST`
- 认证: header `X-Webhook-Token: <token>`, 与 `WEBHOOK_TOKEN` 相同
- 成功: 返回 2xx; token 不匹配: 4xx; 执行失败: 5xx
- 效果: 拉取公开仓库 main 分支最新 pairlist.json + selection_report.csv 到 `/root/freqtrade/user_data_v4/`

参考实现（adnanh/webhook 容器）:

```bash
docker run -d --name webhook --restart unless-stopped \
  -v /root/freqtrade:/freqtrade \
  -v /root/webhook/hooks.yaml:/etc/webhook/hooks.yaml \
  adnanh/webhook -hooks /etc/webhook/hooks.yaml -verbose
```

hooks.yaml 校验 header token + 执行 pull 脚本; 容器内预 clone 公开仓库到 `/freqtrade/coin-select-results`（一次性）。注意用 `header-match`（校验 `X-Webhook-Token` header），不是 `payload-hash`（那是 body HMAC 校验，与接口契约不符）; secret 明文存在于服务器 hooks.yaml, 需 chmod 600 保护。

```yaml
- id: pairlist-updated
  execute-command: /usr/local/bin/pull-pairlist.sh
  trigger-rule:
    match:
      - type: header-match
        name: X-Webhook-Token
        value: <与 WEBHOOK_TOKEN 相同的随机串>
```

## 代码改动清单

1. `.github/workflows/select-pairs.yml` — 新增（定时选币 + commit + curl 触发）
2. `webhook.config.json` — 新增（触发 URL 配置, 默认空）
3. `coin_selector/writer.py` — `DEFAULT_REFRESH_PERIOD` 1800 → 300
4. `coin_selector/cli.py` — 新增 `--refresh-period` 参数（默认 300）, 传给 `write_pairlist`
5. `tests/test_writer.py` — 相应断言更新（refresh_period 默认 300）
6. `README.md` — 更新: 自动化选币章节（架构图、启用步骤、服务器 webhook 搭建建议、接口契约、schedule 可靠性说明、故障排查）、频率相关数字
7. `.gitignore` — 检查, `out/` 临时目录不入库

## 错误处理

| 故障 | 行为 |
|------|------|
| 币安 API 451/不可达 | 探测步骤直接 fail, 不选币、不动仓库 |
| 选币中途失败 | job fail, 无 commit, 旧列表继续 |
| 结果无变化 | 不 commit、不 curl（零噪音） |
| curl 失败（服务器离线） | 重试 3 次仍失败 → job 标红（可见告警）; commit 已在仓库, 服务器恢复后 pull 即可补上 |
| secret 未配置 | 跳过 curl + warning（不 fail） |
| schedule 延迟/跳单 | GitHub 不保证 schedule 精确（整点高峰可能延迟 5-10 分钟）; 错峰 `2-59/5` 缓解; 对场景足够 |

## 测试与验证

- 现有 pytest 不动, 仅 test_writer.py 断言随默认值更新
- 验证路径: push → `workflow_dispatch` 手动跑一次 → 观察币安连通性/选币/commit/curl 全链路
- 服务器侧: 搭好后 curl 端点试一次, 确认 token 校验与 pull 生效
- 环境性风险: 币安 API 从 Actions 访问的 451 地域限制（首次手动 dispatch 即见分晓）

## 风险与说明

- **commit 噪音**: 5 分钟频率下结果几乎每次都微变, 一天可能上百 commit; 文件仅几 KB, GitHub 无 commit 数限制, 接受。如需收敛可后续加"变化超过 N 个币才 commit"阈值（YAGNI, 本次不做）。
- **schedule 可靠性**: 见错误处理表最后一行。
- **币安 451**: 见测试与验证。
