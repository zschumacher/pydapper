ARG python_version=3.9.9
ARG poetry_version=1.1.11

FROM python:$python_version
RUN mkdir -p /usr/lib/oracle
COPY --from=ghcr.io/oracle/oraclelinux8-instantclient:21 /usr/lib/oracle usr/lib/oracle
CMD bash

RUN curl -sSL https://install.python-poetry.org | python - && \
    /root/.local/bin/poetry config virtualenvs.create false

WORKDIR app

ADD . .

RUN /root/.local/bin/poetry install -E pymssql -E cx-Oracle -E mysql-connector-python -E psycopg2

CMD bash