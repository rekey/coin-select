# coin-selector: 多因子选币 (全市场 USDT 永续 -> top N, 输出 RemotePairList 格式 pairlist.json)
FROM python:3.13-slim

WORKDIR /app

# 先拷 pyproject 装依赖 (利用层缓存)
COPY pyproject.toml ./
COPY coin_selector/ ./coin_selector/
RUN pip install --no-cache-dir .

# 默认入口: python -m coin_selector (等价宿主机 .venv 用法)
ENTRYPOINT ["python", "-m", "coin_selector"]
