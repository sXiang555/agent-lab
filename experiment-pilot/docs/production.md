# 生产部署与验收

生产拓扑为公网 HTTPS → Caddy → Next.js → FastAPI → PostgreSQL/pgvector。Caddy 是唯一发布宿主机端口的服务。数据库、审批队列、向量索引和 LangGraph 检查点都存在 PostgreSQL，Caddy 证书单独持久化。API 固定一个 worker，保证同一复盘的操作串行处理。

公网访客可打开只读样例，用内置虚构实验查看 AP 对比、口径差异和引用。样例端点使用独立的内置目录，不发起模型调用，不读取部署者的实验目录，也不创建复盘或申请。实验员和审批员使用不同令牌。生产配置强制关闭演示令牌和 API 文档，并限制代理路由、请求体和角色写请求频率。

## 上线前验收

需要 Docker Engine 和 Docker Compose v2.24+、Python 3.12+、uv、Node.js 22+。

```bash
make check
make production-smoke
```

生产烟测创建独立的 Compose 项目和临时令牌，在本机高端口启动 Caddy，并验证内部 CA 签发的 HTTPS 证书。它会检查 HTTP 跳转、公开样例、匿名和越权请求、请求体限制、pgvector 检索、SSE、数据库重启后的审批恢复、审批重试，以及备份恢复后的队列记录。测试结束后清理该次测试专用的容器和数据卷。

仓库根目录的 `.github/workflows/experiment-pilot.yml` 会在相关推送、PR 或手动触发时执行这两项检查，并上传离线评测报告。自定义托管环境的公网健康检查在部署后单独执行。

## 发布到 Linux 主机

1. 将域名的 DNS 记录指向主机，放行 TCP 80 和 443。保持 API 和 PostgreSQL 端口只在 Compose 内部网络可用。
2. 在主机上检出通过验收的代码版本，进入 `experiment-pilot/`。复制生产环境样例并填入实际域名。

   ```bash
   cp .env.production.example .env.production
   python3 deploy/init_secrets.py
   docker compose --env-file .env.production -f compose.prod.yaml config --quiet
   docker compose --env-file .env.production -f compose.prod.yaml up -d --build --wait
   ```

   `.secrets/` 权限为 0700。生成器只补齐缺失文件，保留已有令牌。Compose 把文件挂载给对应服务。令牌通过单独的安全渠道交给实验员和审批员。

3. 从主机之外用浏览器打开域名，确认浏览器接受 HTTPS 证书。访问 `/api/pilot/ready` 确认数据库就绪，再走一遍公开样例和受保护的审批流程。外部探活可以定期请求这个就绪端点。
4. 保留代码版本、启动时间和验收记录。演示部署使用虚构数据和规则模式。接入真实实验时使用只读挂载，配置 `PILOT_RUNS_FILE`，并按需要关闭公开样例。

## 备份与回退

```bash
sh deploy/backup.sh /secure/backup/pilot-2026-11-09.dump
```

备份包含工作流检查点、申请、队列和向量索引。把备份存到独立的受控位置并定期验证恢复。恢复演练应使用一套独立数据库，核对申请状态和队列记录。

升级前保存当前版本和一份数据库备份。回退时用上一版代码重新构建 API 和 Web，同时保留生产数据卷。涉及数据库格式变化时，先在隔离环境验证恢复，再切换流量。

## 运行边界

本配置面向单主机毕业作品演示。固定角色令牌适合少量操作人员。接入正式团队时再按账号身份、审计和高可用要求扩展。补跑申请只进入持久化队列，GPU 调度器属于独立的后续接入。
