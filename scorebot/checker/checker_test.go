package checker

import (
	"testing"
	"time"
)

// ── parseKingName tests ─────────────────────────────────────────────────────

func TestParseKingName_Normal(t *testing.T) {
	got := parseKingName("TeamAlpha\n")
	if got != "TeamAlpha" {
		t.Errorf("parseKingName(%q) = %q, want %q", "TeamAlpha\n", got, "TeamAlpha")
	}
}

func TestParseKingName_Multiline(t *testing.T) {
	got := parseKingName("TeamAlpha\nGarbageLine\nMore")
	if got != "TeamAlpha" {
		t.Errorf("parseKingName = %q, want %q", got, "TeamAlpha")
	}
}

func TestParseKingName_Empty(t *testing.T) {
	got := parseKingName("")
	if got != "" {
		t.Errorf("parseKingName(%q) = %q, want %q", "", got, "")
	}
}

func TestParseKingName_WhitespaceOnly(t *testing.T) {
	got := parseKingName("   \n\t  ")
	if got != "" {
		t.Errorf("parseKingName = %q, want empty", got)
	}
}

func TestParseKingName_LeadingTrailingSpaces(t *testing.T) {
	got := parseKingName("  TeamAlpha  \n")
	if got != "TeamAlpha" {
		t.Errorf("parseKingName = %q, want %q", got, "TeamAlpha")
	}
}

// ── shellQuote tests ────────────────────────────────────────────────────────

func TestShellQuote_Simple(t *testing.T) {
	got := shellQuote("/root/king.txt")
	want := "'/root/king.txt'"
	if got != want {
		t.Errorf("shellQuote = %q, want %q", got, want)
	}
}

func TestShellQuote_WithSingleQuote(t *testing.T) {
	got := shellQuote("/root/king's.txt")
	want := "'/root/king'\\''s.txt'"
	if got != want {
		t.Errorf("shellQuote = %q, want %q", got, want)
	}
}

func TestShellQuote_WithSpaces(t *testing.T) {
	got := shellQuote("/home/user/my file.txt")
	want := "'/home/user/my file.txt'"
	if got != want {
		t.Errorf("shellQuote = %q, want %q", got, want)
	}
}

// ── NewHillChecker tests ────────────────────────────────────────────────────

func TestNewHillChecker(t *testing.T) {
	hc := NewHillChecker("root", "pass123", "", 10*time.Second)
	if hc.sshUser != "root" {
		t.Errorf("sshUser = %q, want %q", hc.sshUser, "root")
	}
	if hc.sshPass != "pass123" {
		t.Errorf("sshPass = %q, want %q", hc.sshPass, "pass123")
	}
	if hc.timeout != 10*time.Second {
		t.Errorf("timeout = %v, want %v", hc.timeout, 10*time.Second)
	}
}

// ── CheckRequest defaults test ──────────────────────────────────────────────

func TestCheckHill_DefaultPort(t *testing.T) {
	hc := NewHillChecker("root", "pass", "", 1*time.Second)

	req := CheckRequest{
		HillID:    1,
		IPAddress: "192.0.2.1", // TEST-NET, won't connect
	}

	// CheckHill will fail to SSH (expected — we're testing defaults)
	result := hc.CheckHill(req)

	// The point is it shouldn't panic; it should return an error gracefully
	if result.HillID != 1 {
		t.Errorf("HillID = %d, want 1", result.HillID)
	}
	if result.ErrorMessage == "" {
		t.Error("Expected an error message for unreachable host")
	}
	if result.CheckDuration <= 0 {
		t.Error("Expected positive check duration")
	}
}

func TestCheckHill_PerHillCredentials(t *testing.T) {
	hc := NewHillChecker("global_user", "global_pass", "", 1*time.Second)

	req := CheckRequest{
		HillID:    2,
		IPAddress: "192.0.2.1",
		SSHUser:   "hill_user",
		SSHPass:   "hill_pass",
	}

	result := hc.CheckHill(req)
	// Just verify it doesn't panic and returns correct hill ID
	if result.HillID != 2 {
		t.Errorf("HillID = %d, want 2", result.HillID)
	}
}

// ── CheckBatch test ─────────────────────────────────────────────────────────

func TestCheckBatch_ReturnsCorrectCount(t *testing.T) {
	hc := NewHillChecker("root", "pass", "", 1*time.Second)

	reqs := []CheckRequest{
		{HillID: 1, IPAddress: "192.0.2.1"},
		{HillID: 2, IPAddress: "192.0.2.2"},
		{HillID: 3, IPAddress: "192.0.2.3"},
	}

	results := hc.CheckBatch(reqs)

	if len(results) != 3 {
		t.Fatalf("CheckBatch returned %d results, want 3", len(results))
	}

	for i, r := range results {
		if r.HillID != reqs[i].HillID {
			t.Errorf("results[%d].HillID = %d, want %d", i, r.HillID, reqs[i].HillID)
		}
	}
}

// ── WriteKingFile validation test ───────────────────────────────────────────

func TestWriteKingFile_InvalidPath(t *testing.T) {
	hc := NewHillChecker("root", "pass", "", 1*time.Second)

	result := hc.WriteKingFile(ResetKingRequest{
		IPAddress:    "192.0.2.1",
		KingFilePath: "relative/path.txt", // must be absolute
	})

	if result.Success {
		t.Error("Expected failure for relative path")
	}
	if result.ErrorMessage == "" {
		t.Error("Expected error message")
	}
}

func TestWriteKingFile_EmptyPath(t *testing.T) {
	hc := NewHillChecker("root", "pass", "", 1*time.Second)

	result := hc.WriteKingFile(ResetKingRequest{
		IPAddress:    "192.0.2.1",
		KingFilePath: "",
	})

	// Empty path should use default "/root/king.txt" and then fail on SSH
	if result.Success {
		t.Error("Expected failure (unreachable host)")
	}
}

// ── SLA check helper tests ─────────────────────────────────────────────────

func TestCheckHTTP_Unreachable(t *testing.T) {
	hc := NewHillChecker("root", "pass", "", 1*time.Second)
	ok := hc.checkHTTP("http://192.0.2.1:9999/", "192.0.2.1")
	if ok {
		t.Error("Expected false for unreachable HTTP endpoint")
	}
}

func TestCheckTCP_ZeroPort(t *testing.T) {
	hc := NewHillChecker("root", "pass", "", 1*time.Second)
	ok := hc.checkTCP("192.0.2.1", 0)
	if ok {
		t.Error("Expected false for port 0")
	}
}

func TestCheckTCP_Unreachable(t *testing.T) {
	hc := NewHillChecker("root", "pass", "", 1*time.Second)
	ok := hc.checkTCP("192.0.2.1", 9999)
	if ok {
		t.Error("Expected false for unreachable TCP endpoint")
	}
}

// ── readKingFileWithCreds path validation ───────────────────────────────────

func TestReadKingFile_InvalidPath(t *testing.T) {
	hc := NewHillChecker("root", "pass", "", 1*time.Second)
	_, err := hc.readKingFileWithCreds("192.0.2.1", 22, "no_slash", "root", "pass")
	if err == nil {
		t.Error("Expected error for non-absolute path")
	}
}

func TestReadKingFile_EmptyPath(t *testing.T) {
	hc := NewHillChecker("root", "pass", "", 1*time.Second)
	_, err := hc.readKingFileWithCreds("192.0.2.1", 22, "", "root", "pass")
	if err == nil {
		t.Error("Expected error for empty path")
	}
}
