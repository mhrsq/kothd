package main

import (
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/kothd/scorebot/checker"
)

func main() {
	port := getEnv("SCOREBOT_PORT", "8081")
	sshUser := getEnv("HILL_SSH_USER", "root")
	sshPass := getEnv("HILL_SSH_PASS", "")
	sshKeyPath := getEnv("HILL_SSH_KEY", "")
	checkTimeout, _ := strconv.Atoi(getEnv("CHECK_TIMEOUT", "15"))

	log.Println("════════════════════════════════════════════════════")
	log.Println("  KoTH CTF — Scorebot")
	log.Printf("  Port: %s | SSH User: %s | Timeout: %ds", port, sshUser, checkTimeout)
	log.Println("════════════════════════════════════════════════════")

	hillChecker := checker.NewHillChecker(
		sshUser,
		sshPass,
		sshKeyPath,
		time.Duration(checkTimeout)*time.Second,
	)

	r := gin.Default()

	// Health check
	r.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"status":  "ok",
			"service": "scorebot",
			"uptime":  time.Since(startTime).String(),
		})
	})

	// Check a single hill
	r.POST("/check", func(c *gin.Context) {
		var req checker.CheckRequest
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}

		result := hillChecker.CheckHill(req)
		c.JSON(http.StatusOK, result)
	})

	// Check multiple hills in parallel
	r.POST("/check/batch", func(c *gin.Context) {
		var reqs []checker.CheckRequest
		if err := c.ShouldBindJSON(&reqs); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}

		results := hillChecker.CheckBatch(reqs)
		c.JSON(http.StatusOK, results)
	})

	// Reset king.txt on a hill (write "nobody")
	r.POST("/reset-king", func(c *gin.Context) {
		var req checker.ResetKingRequest
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}

		result := hillChecker.WriteKingFile(req)
		if result.Success {
			c.JSON(http.StatusOK, result)
		} else {
			c.JSON(http.StatusInternalServerError, result)
		}
	})

	log.Printf("Scorebot listening on :%s", port)
	if err := r.Run(fmt.Sprintf(":%s", port)); err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}

var startTime = time.Now()

func getEnv(key, fallback string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return fallback
}
