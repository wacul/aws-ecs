FROM python:3-alpine


ADD . /app/

WORKDIR /app/

# required packages
RUN apk add --update --no-cache curl ca-certificates jq bash && \
    pip install --no-cache-dir -r /app/requirements.txt

ENTRYPOINT [ "python3", "main.py" ]
