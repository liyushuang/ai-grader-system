#!/bin/bash
export VOLCANO_API_KEY=ark-ddbae8e5-c1ad-4200-8b1d-b8483adca0c6-9eda7
export BAIDU_API_KEY=6QzUZkERoW31P0kZlpoA8Seh
export BAIDU_SECRET_KEY=bmCwZukpPIUxAvssGdS12m9ITj5UhWod
export DASHSCOPE_API_KEY=sk-ws-H.EMDIIYR.jtU9.MEQCIDg63k7FDifjcSOhZIrLlfmhEyb7or87x8Ka3ljuyrKFAiA9kSj93j6TJaUlazt1R_IS1QC-DWan69IoLEyeIbaZhw
cd /workspace/poc_grader
exec python3 web_server.py > /tmp/web_server.log 2>&1
