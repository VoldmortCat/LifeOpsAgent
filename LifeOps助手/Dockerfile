# LifeOps 前端 — Nginx 运行（H5 构建产物由宿主机生成）
FROM nginx:alpine

COPY dist/build/h5 /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]