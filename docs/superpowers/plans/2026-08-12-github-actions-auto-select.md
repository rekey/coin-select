# GitHub Actions 自动选币 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 GitHub Actions 每 5 分钟自动选币，commit 回公开仓库后 curl 触发用户服务器 webhook 执行 git pull，freqtrade 分钟级换币。

**Architecture:** 新增定时 workflow（schedule + 手动 dispatch），跑现有 `python -m coin_selector` 选币，结果变化才 commit+push，然后按 `webhook.config.json`（URL 入库、token 走 secret）触发服务器；同步把 pairlist 的 `refresh_period` 从 1800 调到 300 以匹配 5 分钟节奏。

**Tech Stack:** GitHub Actions (ubuntu-latest, python 3.11), 现有 coin-selector 代码 (ccxt/pandas/numpy/pyarrow), 服务器侧建议 adnanh/webhook（用户搭建, 本文档给参考配置）。

## Global Constraints

- 设计规格: `docs/superpowers/specs/2026-08-12-github-actions-auto-select-design.md`
- 不新增 Python 依赖（ccxt>=4.3, pandas>=2.0, numpy>=1.26, pyarrow>=15 维持不变）
- `refresh_period` 默认 300，单一事实来源为 `coin_selector/writer.py` 的 `DEFAULT_REFRESH_PERIOD`
- workflow 触发**仅** `schedule` + `workflow_dispatch`；**禁止 push 触发**（Actions 自身 commit 会自触发循环）
- cron 表达式 `2-59/5 * * * *`（每 5 分钟, 错峰 2 分钟避开整点高峰）
- webhook 契约: `POST` + header `X-Webhook-Token`；2xx 成功；`webhook.config.json` 只存 URL（公开仓库, token 不得入库）
- 选币参数对齐默认: `--top 30 --prescreen-size 75 --min-volume 5e6 --max-change 40 --timeframe 30m --lookback 500`
- 文档与代码注释使用中文（与现有 README/注释一致）

---

### Task 1: refresh_period 默认 300 + CLI --refresh-period 参数

**Files:**
- Modify: `coin_selector/writer.py:8`（DEFAULT_REFRESH_PERIOD 1800 → 300）
- Modify: `coin_selector/cli.py:7,36-46,106`（import 常量、新增参数、传参）
- Test: `tests/test_writer.py:7-11`、`tests/test_cli.py`

**Interfaces:**
- Consumes: 现有 `write_pairlist(pairs, out_path, refresh_period=...)` 签名（已有参数, 不动签名）
- Produces: CLI 新参数 `--refresh-period`（int, 默认 `writer.DEFAULT_REFRESH_PERIOD`）；`write_pairlist` 默认 refresh_period 变为 300

- [ ] **Step 1: 更新 test_writer.py 断言为 300**

把 `tests/test_writer.py` 中:

```python
def test_write_pairlist_atomic_and_format(tmp_path: Path):
    pairs = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    out = write_pairlist(pairs, tmp_path / "pairlist.json", refresh_period=1800)
    data = json.loads(out.read_text())
    assert data == {"pairs": pairs, "refresh_period": 1800}
```

改为（改为依赖常量, 不硬编码, 使默认值变更后测试仍通过）:

```python
from coin_selector.writer import DEFAULT_REFRESH_PERIOD, export_whitelist, write_pairlist, write_report

def test_write_pairlist_atomic_and_format(tmp_path: Path):
    pairs = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    out = write_pairlist(pairs, tmp_path / "pairlist.json")
    data = json.loads(out.read_text())
    assert data == {"pairs": pairs, "refresh_period": DEFAULT_REFRESH_PERIOD}
```

- [ ] **Step 2: 新增 CLI 参数测试**

在 `tests/test_cli.py` 末尾追加:

```python
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
```

- [ ] **Step 3: 运行测试验证失败**

Run: `cd /root/github/coin-select && python -m pytest tests/test_cli.py::test_cli_refresh_period_flag -v`
Expected: FAIL（`error: unrecognized arguments: --refresh-period`）

- [ ] **Step 4: 实现 writer.py 默认值**

修改 `coin_selector/writer.py:8`:

```python
DEFAULT_REFRESH_PERIOD = 1800
```

为:

```python
DEFAULT_REFRESH_PERIOD = 300  # 与 GitHub Actions 每 5 分钟选币节奏匹配
```

- [ ] **Step 5: 实现 CLI 参数**

修改 `coin_selector/cli.py:7`:

```python
from coin_selector.writer import export_whitelist, write_pairlist, write_report
```

为:

```python
from coin_selector.writer import DEFAULT_REFRESH_PERIOD, export_whitelist, write_pairlist, write_report
```

在 `coin_selector/cli.py:45`（`--lookback` 之后）追加:

```python
    ap.add_argument("--refresh-period", type=int, default=DEFAULT_REFRESH_PERIOD,
                    help=f"pairlist 刷新周期秒数 (默认 {DEFAULT_REFRESH_PERIOD})")
```

修改 `coin_selector/cli.py:106`:

```python
    write_pairlist(top, args.out / "pairlist.json", refresh_period=1800)
```

为:

```python
    write_pairlist(top, args.out / "pairlist.json", refresh_period=args.refresh_period)
```

- [ ] **Step 6: 运行全部测试验证通过**

Run: `cd /root/github/coin-select && python -m pytest tests/ -v`
Expected: 全部 PASS（test_writer 因改为引用常量不受默认值变更影响；test_cli_refresh_period_flag 通过）

- [ ] **Step 7: Commit**

```bash
cd /root/github/coin-select
git add coin_selector/writer.py coin_selector/cli.py tests/test_writer.py tests/test_cli.py
git commit -m "feat: pairlist refresh_period 默认改为 300, CLI 支持 --refresh-period"
```

---

### Task 2: webhook.config.json + select-pairs workflow

**Files:**
- Create: `webhook.config.json`
- Create: `.github/workflows/select-pairs.yml`

**Interfaces:**
- Consumes: Task 1 的 `--refresh-period` 参数（本任务 workflow 不显式传, 用默认 300）
- Produces: `webhook.config.json`（`{"url": "", "comment": ...}`, workflow 第 5 步读取其 `url` 字段）；workflow 触发链（schedule 每 5 分钟 + dispatch）

- [ ] **Step 1: 创建 webhook.config.json**

创建 `webhook.config.json`:

```json
{
  "url": "",
  "comment": "服务器 webhook 端点。留空 = 未启用；搭建好端点后填入 https://你的域名:端口/hooks/pairlist-updated 并 push，下一轮 cron 或手动 dispatch 即生效。token 配置在 GitHub repository secret WEBHOOK_TOKEN (Settings -> Secrets and variables -> Actions)。"
}
```

- [ ] **Step 2: 创建 workflow**

创建 `.github/workflows/select-pairs.yml`:

```yaml
name: select-pairs

on:
  schedule:
    - cron: "2-59/5 * * * *"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  select-pairs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: 安装依赖
        run: pip install .

      - name: 币安 API 连通性探测
        run: |
          curl -fsS --max-time 10 https://api3.binance.com/api/v3/ping >/dev/null
          echo "币安 API 可达"

      - name: 运行选币
        run: python -m coin_selector --out ./out --report ./out/selection_report.csv

      - name: 结果变化则提交并推送
        run: |
          if [ ! -f pairlist.json ] || ! diff -q out/pairlist.json pairlist.json >/dev/null 2>&1; then
            cp out/pairlist.json out/selection_report.csv .
            git add pairlist.json selection_report.csv
            git config user.name "github-actions[bot]"
            git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
            git commit -m "ci: 自动选币更新 $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
            git push
            echo "已推送新选币结果"
          else
            echo "选币结果无变化, 跳过 commit"
          fi

      - name: 触发服务器更新 (webhook)
        env:
          TOKEN: ${{ secrets.WEBHOOK_TOKEN }}
        run: |
          URL=$(python - <<'EOF'
          import json
          try:
              print(json.load(open("webhook.config.json"))["url"].strip())
          except Exception:
              print("")
          EOF
          )
          if [ -z "$URL" ]; then
            echo "::warning::webhook.config.json url 为空, 跳过触发"
            exit 0
          fi
          if [ -z "$TOKEN" ]; then
            echo "::warning::WEBHOOK_TOKEN secret 未配置, 跳过触发"
            exit 0
          fi
          for i in 1 2 3; do
            code=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 15 \
              -X POST "$URL" -H "X-Webhook-Token: $TOKEN" || echo "000")
            echo "触发尝试 $i: HTTP $code"
            [ "$code" != "000" ] && [ "$code" -lt 400 ] && exit 0
            [ "$i" -lt 3 ] && sleep 10
          done
          echo "::error::webhook 触发失败 (最后状态 $code)"
          exit 1
```

- [ ] **Step 3: 验证 YAML 语法**

Run: `cd /root/github/coin-select && python -c "import yaml; yaml.safe_load(open('.github/workflows/select-pairs.yml')); yaml.safe_load(open('webhook.config.json')); print('YAML OK')"`
Expected: `YAML OK`（无解析错误）

- [ ] **Step 4: 本地验证选币命令可跑通（不 push, 不触发）**

Run: `cd /root/github/coin-select && python -m coin_selector --out /tmp/cs-check --report /tmp/cs-check/selection_report.csv --top 5 --prescreen-size 10`
Expected: 日志显示 ticker 数量、初筛池、选币完成, 生成 `/tmp/cs-check/pairlist.json`；随后 `rm -rf /tmp/cs-check`

> 注意: 此步骤需要宿主机可访问币安 API（与现有手动用法一致）；若网络不可达则跳过并在 commit message 中注明（CI 环境首次 dispatch 时验证）。

- [ ] **Step 5: Commit**

```bash
cd /root/github/coin-select
git add webhook.config.json .github/workflows/select-pairs.yml
git commit -m "ci: 新增 select-pairs workflow (每 5 分钟选币 + commit + webhook 触发)"
```

---

### Task 3: README 自动化章节

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 1 的 `--refresh-period` 参数、Task 2 的 workflow 与 `webhook.config.json`

- [ ] **Step 1: 更新命令参数表**

在 `README.md` 主命令参数表中 `--lookback` 行之后追加一行:

```markdown
| `--refresh-period` | 300 | pairlist 刷新周期（秒），与 freqtrade RemotePairList 轮询节奏一致 |
```

- [ ] **Step 2: 更新 freqtrade 联动章节的 refresh_period**

在 `README.md`"与 freqtrade-v4 容器的联动"章节的配置示例中:

```json
"refresh_period": 1800,
```

改为:

```json
"refresh_period": 300,
```

并在该章节末尾追加说明:

```markdown
> `refresh_period` 需与选币节奏匹配（默认 300 秒 = 5 分钟）。注意 RemotePairList 响应 JSON 里的 `refresh_period` 字段会覆盖容器配置，因此 `pairlist.json` 内的值（由 `--refresh-period` 控制，默认 300）与容器配置需保持一致。
```

- [ ] **Step 3: 新增"自动化选币（GitHub Actions）"章节**

在 `README.md`"与 freqtrade-v4 容器的联动"章节之后、"Docker 使用"之前插入:

```markdown
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
```

- [ ] **Step 4: Commit**

```bash
cd /root/github/coin-select
git add README.md
git commit -m "docs: README 新增 GitHub Actions 自动化选币章节"
```

---

### Task 4: .gitignore + 全量验证

**Files:**
- Create: `.gitignore`

**Interfaces:**
- Consumes: 全部前序任务

- [ ] **Step 1: 创建 .gitignore**

创建 `.gitignore`:

```gitignore
__pycache__/
*.pyc
*.egg-info/
.venv/
.pytest_cache/
out/
```

- [ ] **Step 2: 全量测试**

Run: `cd /root/github/coin-select && python -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 3: 检查 git 状态**

Run: `cd /root/github/coin-select && git status --short`
Expected: 工作区干净（仅显示 .gitignore 未提交; `out/`、egg-info、`__pycache__` 等均被忽略）

- [ ] **Step 4: Commit**

```bash
cd /root/github/coin-select
git add .gitignore
git commit -m "chore: 新增 .gitignore"
```

- [ ] **Step 5: 确认仓库可推送（提示用户执行, 不代推）**

告知用户: 推到 GitHub 需在远端创建公开仓库后执行:

```bash
cd /root/github/coin-select
git remote add origin git@github.com:<owner>/<repo>.git
git push -u origin main
```

推送后首次验证: Actions 页 → select-pairs → Run workflow；观察币安连通性探测 → 选币 → commit → webhook 触发四步日志。
