
# Python 3.14 기반 Linux 이미지
FROM python:3.14-slim

# 컨테이너 작업 폴더
WORKDIR /app

# 필요한 패키지 목록 복사
COPY requirements.txt .

# Windows에서 다운로드한 Linux용 패키지 복사
COPY wheelhouse/ /wheelhouse/

# 인터넷 연결 없이 패키지 설치
RUN pip install --no-index --find-links=/wheelhouse --no-cache-dir -r requirements.txt

# 웹서비스 코드 복사
COPY app.py .

# SQLite 데이터 폴더 생성
RUN mkdir -p /app/data

# 웹 애플리케이션 포트
EXPOSE 8000

# DB 초기화 후 Gunicorn 실행
CMD ["sh", "-c", "python -c 'from app import init_db; init_db()' && exec gunicorn --bind 0.0.0.0:8000 app:app"]
