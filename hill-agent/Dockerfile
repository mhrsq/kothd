# KoTH CTF — Hill Agent
# Lightweight binary to deploy on each hill server.
# Build: docker build -t koth-hill-agent .
# Or just: go build -o hill-agent .
FROM golang:1.22-alpine AS builder

WORKDIR /build
COPY go.mod ./
COPY main.go ./

RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o hill-agent .

# ─── Minimal runtime ────────────────────────────────────────────────────────
FROM alpine:3.20

RUN apk --no-cache add ca-certificates && \
    addgroup -S koth && adduser -S -G koth -h /app koth

WORKDIR /app
COPY --from=builder /build/hill-agent .
RUN chown -R koth:koth /app

USER koth

ENTRYPOINT ["./hill-agent"]
