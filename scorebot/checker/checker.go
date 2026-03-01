package checker

import (
	"bytes"
	"fmt"
	"log"
	"net"
	"net/http"
	"strings"
	"sync"
	"time"

	"golang.org/x/crypto/ssh"
)

// CheckRequest is sent by the scoreboard tick engine
type CheckRequest struct {
	HillID       int    `json:"hill_id" binding:"required"`
	IPAddress    string `json:"ip_address" binding:"required"`
	SSHPort      int    `json:"ssh_port"`
	KingFilePath string `json:"king_file_path"`
	SLACheckType string `json:"sla_check_type"`  // "http", "tcp", "ssh"
	SLACheckURL  string `json:"sla_check_url"`   // for http checks
	SLACheckPort int    `json:"sla_check_port"`  // for tcp checks
	SSHUser      string `json:"ssh_user"`         // per-hill SSH user override
	SSHPass      string `json:"ssh_pass"`         // per-hill SSH password override
}

// CheckResult is returned to the scoreboard
type CheckResult struct {
	HillID        int    `json:"hill_id"`
	KingTeamName  string `json:"king_team_name"`
	SLAStatus     bool   `json:"sla_status"`
	RawKingTxt    string `json:"raw_king_txt"`
	CheckDuration int    `json:"check_duration_ms"`
	ErrorMessage  string `json:"error_message,omitempty"`
}

// HillChecker performs SSH + SLA checks on hills
type HillChecker struct {
	sshUser    string
	sshPass    string
	sshKeyPath string
	timeout    time.Duration
}

// NewHillChecker creates a new checker instance
func NewHillChecker(user, pass, keyPath string, timeout time.Duration) *HillChecker {
	return &HillChecker{
		sshUser:    user,
		sshPass:    pass,
		sshKeyPath: keyPath,
		timeout:    timeout,
	}
}

// CheckHill performs king.txt read + SLA check on a single hill
func (hc *HillChecker) CheckHill(req CheckRequest) CheckResult {
	start := time.Now()
	result := CheckResult{HillID: req.HillID}

	// Default values
	if req.SSHPort == 0 {
		req.SSHPort = 22
	}
	if req.KingFilePath == "" {
		req.KingFilePath = "/root/king.txt"
	}
	if req.SLACheckType == "" {
		req.SLACheckType = "ssh"
	}

	// Step 1: SSH into hill and read king.txt
	// Use per-hill SSH credentials if provided, otherwise fall back to global
	sshUser := hc.sshUser
	sshPass := hc.sshPass
	if req.SSHUser != "" {
		sshUser = req.SSHUser
	}
	if req.SSHPass != "" {
		sshPass = req.SSHPass
	}
	kingTxt, err := hc.readKingFileWithCreds(req.IPAddress, req.SSHPort, req.KingFilePath, sshUser, sshPass)
	if err != nil {
		result.ErrorMessage = fmt.Sprintf("SSH king read failed: %v", err)
		result.CheckDuration = int(time.Since(start).Milliseconds())
		log.Printf("[Hill %d] SSH failed: %v", req.HillID, err)
		return result
	}

	result.RawKingTxt = kingTxt
	result.KingTeamName = parseKingName(kingTxt)

	// Step 2: SLA check
	slaOK := false
	switch req.SLACheckType {
	case "http":
		slaOK = hc.checkHTTP(req.SLACheckURL, req.IPAddress)
	case "tcp":
		slaOK = hc.checkTCP(req.IPAddress, req.SLACheckPort)
	case "ssh":
		// If SSH king read succeeded, SSH is alive
		slaOK = true
	default:
		slaOK = true
	}
	result.SLAStatus = slaOK

	result.CheckDuration = int(time.Since(start).Milliseconds())

	log.Printf("[Hill %d] King: %q | SLA: %v | %dms",
		req.HillID, result.KingTeamName, slaOK, result.CheckDuration)

	return result
}

// CheckBatch checks multiple hills in parallel
func (hc *HillChecker) CheckBatch(reqs []CheckRequest) []CheckResult {
	results := make([]CheckResult, len(reqs))
	var wg sync.WaitGroup

	for i, req := range reqs {
		wg.Add(1)
		go func(idx int, r CheckRequest) {
			defer wg.Done()
			results[idx] = hc.CheckHill(r)
		}(i, req)
	}

	wg.Wait()
	return results
}

// ── SSH Operations ──────────────────────────────────────────────────────────

func (hc *HillChecker) getSSHConfig() *ssh.ClientConfig {
	config := &ssh.ClientConfig{
		User:            hc.sshUser,
		HostKeyCallback: ssh.InsecureIgnoreHostKey(),
		Timeout:         hc.timeout,
	}

	// Try key-based auth first
	if hc.sshKeyPath != "" {
		// Key auth would go here
		// For now, fall through to password
	}

	// Password auth
	config.Auth = []ssh.AuthMethod{
		ssh.Password(hc.sshPass),
	}

	return config
}

// shellQuote escapes a string for safe use in a shell command (single-quote wrapping).
func shellQuote(s string) string {
	// Replace single quotes with the escape sequence: ' -> '\''
	return "'" + strings.ReplaceAll(s, "'", "'\\''") + "'"
}

// ResetKingRequest is sent by the admin endpoint to reset king.txt on a hill
type ResetKingRequest struct {
	IPAddress    string `json:"ip_address" binding:"required"`
	SSHPort      int    `json:"ssh_port"`
	KingFilePath string `json:"king_file_path"`
	SSHUser      string `json:"ssh_user"`
	SSHPass      string `json:"ssh_pass"`
}

// ResetKingResult is returned after resetting king.txt
type ResetKingResult struct {
	Success      bool   `json:"success"`
	ErrorMessage string `json:"error_message,omitempty"`
}

// WriteKingFile SSHs into a hill and writes "nobody" to king.txt
func (hc *HillChecker) WriteKingFile(req ResetKingRequest) ResetKingResult {
	if req.SSHPort == 0 {
		req.SSHPort = 22
	}
	if req.KingFilePath == "" {
		req.KingFilePath = "/root/king.txt"
	}

	sshUser := hc.sshUser
	sshPass := hc.sshPass
	if req.SSHUser != "" {
		sshUser = req.SSHUser
	}
	if req.SSHPass != "" {
		sshPass = req.SSHPass
	}

	err := hc.writeKingFileWithCreds(req.IPAddress, req.SSHPort, req.KingFilePath, sshUser, sshPass)
	if err != nil {
		log.Printf("[ResetKing] Failed to write king.txt on %s:%d: %v", req.IPAddress, req.SSHPort, err)
		return ResetKingResult{Success: false, ErrorMessage: err.Error()}
	}

	log.Printf("[ResetKing] Successfully reset king.txt on %s:%d -> nobody", req.IPAddress, req.SSHPort)
	return ResetKingResult{Success: true}
}

func (hc *HillChecker) writeKingFileWithCreds(host string, port int, filePath string, user string, pass string) error {
	addr := fmt.Sprintf("%s:%d", host, port)

	if filePath == "" || filePath[0] != '/' {
		return fmt.Errorf("invalid file path: must be absolute")
	}

	config := &ssh.ClientConfig{
		User:            user,
		HostKeyCallback: ssh.InsecureIgnoreHostKey(),
		Timeout:         hc.timeout,
		Auth: []ssh.AuthMethod{
			ssh.Password(pass),
		},
	}

	client, err := ssh.Dial("tcp", addr, config)
	if err != nil {
		return fmt.Errorf("ssh dial: %w", err)
	}
	defer client.Close()

	session, err := client.NewSession()
	if err != nil {
		return fmt.Errorf("ssh session: %w", err)
	}
	defer session.Close()

	cmd := fmt.Sprintf("echo 'nobody' > %s", shellQuote(filePath))
	if err := session.Run(cmd); err != nil {
		return fmt.Errorf("ssh run: %w", err)
	}

	return nil
}

func (hc *HillChecker) readKingFile(host string, port int, filePath string) (string, error) {
	return hc.readKingFileWithCreds(host, port, filePath, hc.sshUser, hc.sshPass)
}

func (hc *HillChecker) readKingFileWithCreds(host string, port int, filePath string, user string, pass string) (string, error) {
	addr := fmt.Sprintf("%s:%d", host, port)

	// Validate filePath: must be an absolute path
	if filePath == "" || filePath[0] != '/' {
		return "", fmt.Errorf("invalid file path: must be absolute")
	}

	config := &ssh.ClientConfig{
		User:            user,
		HostKeyCallback: ssh.InsecureIgnoreHostKey(),
		Timeout:         hc.timeout,
		Auth: []ssh.AuthMethod{
			ssh.Password(pass),
		},
	}

	client, err := ssh.Dial("tcp", addr, config)
	if err != nil {
		return "", fmt.Errorf("ssh dial: %w", err)
	}
	defer client.Close()

	session, err := client.NewSession()
	if err != nil {
		return "", fmt.Errorf("ssh session: %w", err)
	}
	defer session.Close()

	var stdout bytes.Buffer
	session.Stdout = &stdout

	cmd := fmt.Sprintf("cat %s 2>/dev/null || echo ''", shellQuote(filePath))
	if err := session.Run(cmd); err != nil {
		return "", fmt.Errorf("ssh run: %w", err)
	}

	return stdout.String(), nil
}

// ── SLA Checks ──────────────────────────────────────────────────────────────

func (hc *HillChecker) checkHTTP(url string, ip string) bool {
	if url == "" {
		url = fmt.Sprintf("http://%s/", ip)
	}

	client := &http.Client{Timeout: hc.timeout}
	resp, err := client.Get(url)
	if err != nil {
		log.Printf("HTTP SLA check failed for %s: %v", url, err)
		return false
	}
	defer resp.Body.Close()

	// Accept any 2xx or 3xx status
	return resp.StatusCode >= 200 && resp.StatusCode < 400
}

func (hc *HillChecker) checkTCP(host string, port int) bool {
	if port == 0 {
		return false
	}

	addr := fmt.Sprintf("%s:%d", host, port)
	conn, err := net.DialTimeout("tcp", addr, hc.timeout)
	if err != nil {
		log.Printf("TCP SLA check failed for %s: %v", addr, err)
		return false
	}
	defer conn.Close()
	return true
}

// ── Helpers ─────────────────────────────────────────────────────────────────

func parseKingName(raw string) string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return ""
	}
	// Take only the first line
	lines := strings.SplitN(raw, "\n", 2)
	return strings.TrimSpace(lines[0])
}
