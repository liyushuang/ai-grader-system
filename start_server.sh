#!/bin/bash
export VOLCANO_API_KEY="${VOLCANO_API_KEY:-}"
export ARK_API_KEY="${ARK_API_KEY:-$VOLCANO_API_KEY}"
export ARK_BASE_URL="${ARK_BASE_URL:-https://ark.cn-beijing.volces.com/api/v3}"
export ARK_MODEL="${ARK_MODEL:-doubao-seed-2-1-pro-260628}"
if [ "$ARK_BASE_URL" = "https://ark.cn-beijing.volces.com/api/plan/v3" ]; then
  export ARK_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
fi
if [ "$ARK_MODEL" = "ark-code-latest" ]; then
  export ARK_MODEL="doubao-seed-2-1-pro-260628"
fi
export BAIDU_API_KEY="${BAIDU_API_KEY:-}"
export BAIDU_SECRET_KEY="${BAIDU_SECRET_KEY:-}"
export DASHSCOPE_API_KEY="${DASHSCOPE_API_KEY:-}"
cd "$(dirname "$0")"
exec .venv/bin/python web_server.py > /tmp/web_server.log 2>&1
