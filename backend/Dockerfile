FROM python:3.12-slim
RUN pip install --no-cache-dir waitress==3.0.2
WORKDIR /app
COPY app.py console.html ./
RUN useradd --uid 10001 --create-home hidear && mkdir /data && chown hidear:hidear /data
USER hidear
ENV HIDEAR_DATABASE=/data/hidear.sqlite3
EXPOSE 8080
CMD ["waitress-serve", "--listen=0.0.0.0:8080", "--call", "app:factory"]
