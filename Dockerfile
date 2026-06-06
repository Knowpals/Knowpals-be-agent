FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY app ./app

CMD ["python", "-m", "app.main"]