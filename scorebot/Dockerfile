# ── Build stage ──
FROM golang:1.22-alpine AS builder

RUN apk add --no-cache git

WORKDIR /build
COPY go.mod go.sum* ./
COPY . .
RUN go mod tidy && go mod download
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o scorebot .

# ── Runtime stage ──
FROM alpine:3.20

RUN apk add --no-cache ca-certificates openssh-client

WORKDIR /app
COPY --from=builder /build/scorebot /app/scorebot

EXPOSE 8081

ENTRYPOINT ["/app/scorebot"]
