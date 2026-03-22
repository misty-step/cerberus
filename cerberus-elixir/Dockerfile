# syntax=docker/dockerfile:1.7

ARG ELIXIR_IMAGE=hexpm/elixir:1.19.1-erlang-27.3.4.1-alpine-3.20.8
ARG ALPINE_IMAGE=alpine:3.20

FROM ${ELIXIR_IMAGE} AS build

RUN apk add --no-cache build-base git

ENV MIX_ENV=prod

WORKDIR /app

RUN mix local.hex --force && mix local.rebar --force

COPY cerberus-elixir/mix.exs cerberus-elixir/mix.lock ./cerberus-elixir/
WORKDIR /app/cerberus-elixir
RUN mix deps.get --only ${MIX_ENV}

COPY cerberus-elixir/config ./config
RUN mix deps.compile

COPY cerberus-elixir/lib ./lib
COPY cerberus-elixir/rel ./rel
COPY defaults ../defaults
COPY pi ../pi
COPY templates ../templates

RUN mix compile
RUN mix release cerberus

FROM ${ALPINE_IMAGE} AS runtime

RUN apk add --no-cache ca-certificates libgcc libstdc++ ncurses-libs openssl sqlite-libs && \
    addgroup -S cerberus && adduser -S cerberus -G cerberus

WORKDIR /app

COPY --from=build /app/cerberus-elixir/_build/prod/rel/cerberus ./

RUN mkdir -p /app/data && chown -R cerberus:cerberus /app

ENV HOME=/app \
    MIX_ENV=prod \
    PORT=8080 \
    CERBERUS_DB_PATH=/app/data/cerberus.sqlite3

EXPOSE 8080

USER cerberus

ENTRYPOINT ["bin/cerberus"]
CMD ["start"]
