首个可部署版本。ExperimentPilot 帮助 RT-DETR / RT-DETRv2 实验组导入训练日志、判断 AP 对照是否可比，并保留可追溯的证据和补跑申请。

- 日志导入按指定 epoch 读取 COCO AP 与 AP_small，记录日志行号和 SHA-256。
- Next.js 工作台展示引用和 SSE 执行进度。人工审批通过后，补跑请求进入持久化演示队列。
- LangGraph、MCP、混合检索、SQLite 本地模式和 PostgreSQL/pgvector 生产模式均随源码交付。
- 发布包包含生产 Compose、Caddy HTTPS、独立角色令牌、备份与恢复手册。Docker 生产演练验证了数据库重启后的审批恢复。

解压附带的部署包，进入 `agent-lab/experiment-pilot/`。本地运行、演示录屏和评测报告从该目录的 `README.md` 开始。公网部署按 `docs/production.md` 配置实际主机和 HTTPS。包内演示数据均为虚构，队列当前未连接 GPU 调度器。
