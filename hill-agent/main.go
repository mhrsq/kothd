/*
KoTH CTF Platform — Hill Agent

Lightweight agent deployed on each hill server. Periodically reads
/root/king.txt and reports the content to the KoTH scoreboard API.
This provides a second verification method alongside the SSH-based
scorebot check (dual-verification).

Usage:
  ./hill-agent \
    -hill-id=1 \
    -token="agent-hill-1-abc123" \
    -server="http://YOUR_KOTH_SERVER:8000" \
    -interval=10 \
    -king-file="/root/king.txt"

Or via environment variables:
  HILL_ID=1
  AGENT_TOKEN=agent-hill-1-abc123
  KOTH_SERVER=http://YOUR_KOTH_SERVER:8000
  REPORT_INTERVAL=10
  KING_FILE=/root/king.txt
  SLA_CHECK_PORT=80       (optional: port to verify SLA)
  SLA_CHECK_TYPE=tcp      (optional: tcp or http)
*/
package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// AgentReport is sent to the scoreboard API
type AgentReport struct {
	HillID     int    `json:"hill_id"`
	AgentToken string `json:"agent_token"`
	KingName   string `json:"king_name"`
	RawKingTxt string `json:"raw_king_txt"`
	SLAStatus  bool   `json:"sla_status"`
	Timestamp  string `json:"timestamp"`
}

// Config holds agent configuration
type Config struct {
	HillID         int
	AgentToken     string
	KoTHServer     string
	ReportInterval int // seconds
	KingFilePath   string
	SLACheckPort   int
	SLACheckType   string // "tcp", "http", or ""
}

func main() {
	cfg := parseConfig()

	log.Println("════════════════════════════════════════════════════")
	log.Println("  KoTH CTF — Hill Agent")
	log.Printf("  Hill ID: %d", cfg.HillID)
	log.Printf("  Server:  %s", cfg.KoTHServer)
	log.Printf("  Interval: %ds", cfg.ReportInterval)
	log.Printf("  King file: %s", cfg.KingFilePath)
	log.Println("════════════════════════════════════════════════════")

	// Graceful shutdown
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	ticker := time.NewTicker(time.Duration(cfg.ReportInterval) * time.Second)
	defer ticker.Stop()

	// Send first report immediately
	sendReport(cfg)

	for {
		select {
		case <-ticker.C:
			sendReport(cfg)
		case sig := <-sigCh:
			log.Printf("Received signal %v, shutting down...", sig)
			return
		}
	}
}

func parseConfig() Config {
	hillID := flag.Int("hill-id", 0, "Hill ID")
	token := flag.String("token", "", "Agent authentication token")
	server := flag.String("server", "", "KoTH server URL (required)")
	interval := flag.Int("interval", 10, "Report interval in seconds")
	kingFile := flag.String("king-file", "/root/king.txt", "Path to king.txt")
	slaPort := flag.Int("sla-port", 0, "Port to check for SLA (0=skip)")
	slaType := flag.String("sla-type", "", "SLA check type: tcp or http")
	flag.Parse()

	cfg := Config{
		HillID:         *hillID,
		AgentToken:     *token,
		KoTHServer:     *server,
		ReportInterval: *interval,
		KingFilePath:   *kingFile,
		SLACheckPort:   *slaPort,
		SLACheckType:   *slaType,
	}

	// Override with env vars if set
	if v := os.Getenv("HILL_ID"); v != "" {
		if id, err := strconv.Atoi(v); err == nil {
			cfg.HillID = id
		}
	}
	if v := os.Getenv("AGENT_TOKEN"); v != "" {
		cfg.AgentToken = v
	}
	if v := os.Getenv("KOTH_SERVER"); v != "" {
		cfg.KoTHServer = v
	}
	if v := os.Getenv("REPORT_INTERVAL"); v != "" {
		if i, err := strconv.Atoi(v); err == nil {
			cfg.ReportInterval = i
		}
	}
	if v := os.Getenv("KING_FILE"); v != "" {
		cfg.KingFilePath = v
	}
	if v := os.Getenv("SLA_CHECK_PORT"); v != "" {
		if p, err := strconv.Atoi(v); err == nil {
			cfg.SLACheckPort = p
		}
	}
	if v := os.Getenv("SLA_CHECK_TYPE"); v != "" {
		cfg.SLACheckType = v
	}

	// Validate
	if cfg.HillID == 0 {
		log.Fatal("ERROR: --hill-id or HILL_ID is required")
	}
	if cfg.AgentToken == "" {
		log.Fatal("ERROR: --token or AGENT_TOKEN is required")
	}
	if cfg.KoTHServer == "" {
		log.Fatal("ERROR: --server or KOTH_SERVER is required")
	}

	return cfg
}

func readKingFile(path string) (string, string) {
	data, err := os.ReadFile(path)
	if err != nil {
		log.Printf("Warning: Cannot read %s: %v", path, err)
		return "", ""
	}

	raw := string(data)
	name := strings.TrimSpace(raw)

	// Take only first line as king name
	if idx := strings.IndexByte(name, '\n'); idx >= 0 {
		name = strings.TrimSpace(name[:idx])
	}

	return name, raw
}

func checkSLA(cfg Config) bool {
	if cfg.SLACheckPort == 0 {
		return true // No SLA check configured, assume up
	}

	switch cfg.SLACheckType {
	case "http":
		url := fmt.Sprintf("http://localhost:%d/", cfg.SLACheckPort)
		client := &http.Client{Timeout: 5 * time.Second}
		resp, err := client.Get(url)
		if err != nil {
			log.Printf("SLA HTTP check failed: %v", err)
			return false
		}
		defer resp.Body.Close()
		return resp.StatusCode >= 200 && resp.StatusCode < 400

	case "tcp":
		addr := fmt.Sprintf("localhost:%d", cfg.SLACheckPort)
		conn, err := net.DialTimeout("tcp", addr, 5*time.Second)
		if err != nil {
			log.Printf("SLA TCP check failed: %v", err)
			return false
		}
		conn.Close()
		return true

	default:
		// Default: try TCP
		addr := fmt.Sprintf("localhost:%d", cfg.SLACheckPort)
		conn, err := net.DialTimeout("tcp", addr, 5*time.Second)
		if err != nil {
			return false
		}
		conn.Close()
		return true
	}
}

func sendReport(cfg Config) {
	kingName, rawTxt := readKingFile(cfg.KingFilePath)
	slaOK := checkSLA(cfg)

	report := AgentReport{
		HillID:     cfg.HillID,
		AgentToken: cfg.AgentToken,
		KingName:   kingName,
		RawKingTxt: rawTxt,
		SLAStatus:  slaOK,
		Timestamp:  time.Now().UTC().Format(time.RFC3339),
	}

	body, err := json.Marshal(report)
	if err != nil {
		log.Printf("ERROR: Failed to marshal report: %v", err)
		return
	}

	url := fmt.Sprintf("%s/api/agent/report", cfg.KoTHServer)
	resp, err := http.Post(url, "application/json", bytes.NewReader(body))
	if err != nil {
		log.Printf("ERROR: Failed to send report: %v", err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode == 200 {
		log.Printf("✓ Report sent: king=%q sla=%v", kingName, slaOK)
	} else {
		respBody, _ := io.ReadAll(resp.Body)
		log.Printf("✗ Report failed (HTTP %d): %s", resp.StatusCode, string(respBody))
	}
}
