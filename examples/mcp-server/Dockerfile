FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir mcp
# 引擎文件（fishing.py / engine.py）和 server.py 通过 compose 的 bind mount 挂进 /app，
# 存档 fishing_save.json 也落在这里，容器重启不丢进度。
CMD ["python", "server.py"]
