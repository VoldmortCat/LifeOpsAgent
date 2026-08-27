# LifeOps 向量数据库（Milvus）运维手册

## 日常使用（99% 的情况你什么都不用做）

三个容器创建时都带 `--restart unless-stopped`：

> **只要 Docker Desktop 在运行，Milvus 就自动跟着起**，开机后无需任何手动操作。
> （Docker Desktop 本身建议在设置里勾选开机自启）

## 手动操作

| 操作 | 方式 |
|---|---|
| 启动 | 双击 `start-milvus.bat`（或命令行进本目录执行它） |
| 停止 | 双击 `stop-milvus.bat` |
| 彻底删除重建 | 见下方"灾难恢复" |

## 地址速查

| 用途 | 地址 |
|---|---|
| Milvus 服务连接 | http://127.0.0.1:19530 （代码里 pymilvus 用这个） |
| 健康检查 | http://localhost:29091/healthz （返回 OK 即就绪） |
| 数据落盘 | D:\ZZB\work\Linux数据库\volumes\{milvus,minio,etcd} |
| 镜像存储 | D:\ZZB\work\Linux数据库\wsl\（junction 自 C 盘原路径） |

## 快速自检三连

```cmd
docker ps                                    :: 三个 lifeops-milvus* 容器应为 Up
curl http://localhost:29091/healthz          :: 应返回 OK
cd /d ..\.venv\Scripts && python.exe -c "from pymilvus import MilvusClient; c=MilvusClient(uri='http://127.0.0.1:19530'); print(c.list_collections())"
```

## 灾难恢复

数据全在 D 盘 volumes 里，删容器不丢数据：

```cmd
docker rm -f lifeops-milvus lifeops-milvus-minio lifeops-milvus-etcd
start-milvus.bat        :: 容器重建，数据自动挂回
```

向量库数据坏了需要重灌（会调 DashScope API）：

```cmd
cd /d ..
.venv\Scripts\python.exe scripts\rebuild_vectordb.py
```

## 已踩过的坑（改配置前先看）

1. **9091 端口不能用** —— 落在 Windows 保留段(9072-9171)，健康检查映射到宿主机 29091，
   容器内部仍是 9091。同理避免 8091-8601 段。
2. **裸 docker run 必须加 --network-alias** —— Milvus 通过主机名 etcd/minio 找依赖，
   compose 的服务名机制在这里不存在，别名就是 DNS。
3. **bat 文件必须 CRLF 换行** —— LF 会被 cmd 解析错乱（robocopy 变 opy 事件）。
4. **C 盘 AppData\Local\Docker\wsl 是 junction** —— 指向 D:\ZZB\work\Linux数据库\wsl，
   别删真身；确认稳定后可删 C 盘的 wsl.bak 备份释放 15GB。

## 相关文件

- start-milvus.bat / stop-milvus.bat —— 启停脚本
- docker-compose.milvus.yml —— 仅存档参考（本机没装 compose 插件，实际用 bat）
- pull.log / milvus-boot.log —— 历史部署日志，可删
