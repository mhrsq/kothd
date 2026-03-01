/*
 * backup_tool - "Corporate Backup Utility"
 * 
 * VULNERABILITY: SUID root binary that calls system() with user-controlled
 * environment. Can be exploited via:
 *   1. PATH hijacking: create a fake 'tar' in /tmp, then:
 *      export PATH=/tmp:$PATH && /usr/local/bin/backup_tool
 *   2. Direct: /usr/local/bin/backup_tool --config /dev/stdin
 *      then pipe a shell command
 *
 * Intended privesc path: webadmin → root
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>

#define BACKUP_DIR "/opt/webapp/backups"
#define MAX_PATH 256

int main(int argc, char *argv[]) {
    char cmd[512];
    char config_file[MAX_PATH] = "/opt/webapp/backup.conf";

    printf("[*] Web Fortress Backup Tool v1.2\n");
    printf("[*] Running as UID: %d\n", getuid());
    printf("[*] Effective UID: %d\n", geteuid());

    // Parse args
    if (argc > 2 && strcmp(argv[1], "--config") == 0) {
        strncpy(config_file, argv[2], MAX_PATH - 1);
    }

    // VULNERABLE: Uses system() which inherits PATH from environment
    // A user can set PATH=/tmp:$PATH and create /tmp/tar as a shell script
    snprintf(cmd, sizeof(cmd), "tar czf %s/backup_$(date +%%s).tar.gz /opt/webapp/data/ 2>/dev/null", BACKUP_DIR);

    printf("[*] Creating backup...\n");
    printf("[*] Command: %s\n", cmd);

    // Ensure backup dir exists
    mkdir(BACKUP_DIR, 0755);

    // VULNERABLE: system() call with SUID bit = root shell via PATH hijack
    setuid(0);  // Escalate to root (SUID bit allows this)
    system(cmd);

    printf("[+] Backup complete!\n");
    return 0;
}
