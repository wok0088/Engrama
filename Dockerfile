# ==========================================
# 阶段 1：构建依赖虚拟环境 (builder)
# ==========================================
FROM python:3.12-slim AS builder

WORKDIR /build

# 创建独立虚拟环境
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 安装第三方依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ==========================================
# 阶段 2：独立的模型预下载 (model-downloader)
# ==========================================
FROM python:3.12-slim AS model-downloader

WORKDIR /models

# 只用 huggingface_hub 这个轻量官方包来下载，不再引入复杂的机器学习包环境
RUN pip install --no-cache-dir huggingface_hub

# 利用 --local-dir 直接把真实模型文件下载到脱水文件夹里，放弃复杂的软连接机制
RUN huggingface-cli download BAAI/bge-m3 --local-dir /models/bge-m3 --local-dir-use-symlinks False


# ==========================================
# 阶段 3：最终应用环境 (runner)
# ==========================================
FROM python:3.12-slim AS runner

WORKDIR /app

# 1. 恢复配置已安装好的虚拟环境
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 2. 将早已准备好的模型复制到项目的预期路径中
COPY --from=model-downloader /models/bge-m3 /app/data/models/bge-m3

# 3. 最后再复制易变的应用源码（让它对缓存的破坏影响降到最低）
COPY engrama/ engrama/
COPY api/ api/
COPY mcp_server/ mcp_server/

# 创建数据存储挂载的预留点
RUN mkdir -p /app/data

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# 启动引擎
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
