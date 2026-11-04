FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml LICENSE ./
COPY desk ./desk
COPY policy ./policy
RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "desk"]
