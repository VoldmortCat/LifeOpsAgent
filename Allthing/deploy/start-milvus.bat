@echo off
rem LifeOps Milvus standalone - data lives on D:\ZZB\work\Linux数据库\volumes
setlocal
set DATA=D:\ZZB\work\Linux数据库\volumes
if not exist "%DATA%" mkdir "%DATA%"
docker network create lifeops-milvus-net 2>nul

echo [1/3] etcd ...
docker start lifeops-milvus-etcd 2>nul || docker run -d --name lifeops-milvus-etcd --network lifeops-milvus-net --network-alias etcd --restart unless-stopped ^
 -v %DATA%\etcd:/etcd ^
 -e ETCD_AUTO_COMPACTION_MODE=revision -e ETCD_AUTO_COMPACTION_RETENTION=1000 -e ETCD_QUOTA_BACKEND_BYTES=4294967296 ^
 quay.io/coreos/etcd:v3.5.18 etcd -advertise-client-urls=http://etcd:2379 -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd

echo [2/3] minio ...
docker start lifeops-milvus-minio 2>nul || docker run -d --name lifeops-milvus-minio --network lifeops-milvus-net --network-alias minio --restart unless-stopped ^
 -v %DATA%\minio:/minio_data ^
 -e MINIO_ACCESS_KEY=minioadmin -e MINIO_SECRET_KEY=minioadmin ^
 minio/minio:RELEASE.2023-03-20T20-16-18Z minio server /minio_data --console-address ":9001"

echo waiting metadata backend ...
timeout /t 8 >nul

echo [3/3] milvus standalone ...
docker start lifeops-milvus 2>nul || docker run -d --name lifeops-milvus --network lifeops-milvus-net --restart unless-stopped ^
 --security-opt seccomp:unconfined ^
 -p 19530:19530 -p 29091:9091 ^
 -v %DATA%\milvus:/var/lib/milvus ^
 -e ETCD_ENDPOINTS=etcd:2379 -e MINIO_ADDRESS=minio:9000 -e COMMON_STORAGETYPE=local ^
 milvusdb/milvus:v2.5.6 milvus run standalone
