FROM python:3.12-slim

WORKDIR /app

# 1. Сначала av из локального wheel
COPY wheels/ /app/wheels/
RUN pip install --no-cache-dir \
    --no-index \
    --find-links=/app/wheels \
    av numpy #paho-mqtt PyYAML

# 2. Потом остальное из PyPI (с retries и timeout)
COPY requirements.txt .
RUN pip install --no-cache-dir \
    --default-timeout=120 \
    --retries=5 \
    -r requirements.txt

#COPY requirements.txt .
#RUN pip install -r requirements.txt
#RUN pip install --no-cache-dir \
#    -i  https://mirrors.aliyun.com/pypi/simple/\
#    --trusted-host mirror.yandex.ru \
#    -r requirements.txt

COPY config.yaml /app/config.yaml
COPY detector/ /app/detector/

CMD ["python", "-u", "-m", "detector.main"]
