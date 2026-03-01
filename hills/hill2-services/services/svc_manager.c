/*
 * svc_manager - "Service Manager Utility"
 * 
 * VULNERABILITY: SUID root binary with multiple vuln paths:
 *   1. "restart" subcommand runs user-supplied service name via system()
 *      → svc_manager restart "; /bin/bash"
 *   2. "check" subcommand reads arbitrary files as root
 *      → svc_manager check /root/king.txt
 *   3. "log" subcommand appends to arbitrary files as root
 *      → svc_manager log /root/king.txt "MyTeamName"
 *
 * Intended privesc: svcadmin/operator → root
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

void usage() {
    printf("Usage: svc_manager <command> [args]\n");
    printf("Commands:\n");
    printf("  restart <service>    - Restart a service\n");
    printf("  check <file>         - Check service config file\n");
    printf("  log <file> <message> - Append to service log\n");
    printf("  status               - Show service status\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        usage();
        return 1;
    }

    // Escalate to root (SUID)
    setuid(0);
    setgid(0);

    if (strcmp(argv[1], "restart") == 0) {
        if (argc < 3) {
            printf("Usage: svc_manager restart <service_name>\n");
            return 1;
        }
        // VULNERABLE: command injection via service name
        char cmd[512];
        snprintf(cmd, sizeof(cmd), "systemctl restart %s 2>&1 || echo 'Service restart attempted: %s'", argv[2], argv[2]);
        printf("[*] Restarting service: %s\n", argv[2]);
        system(cmd);

    } else if (strcmp(argv[1], "check") == 0) {
        if (argc < 3) {
            printf("Usage: svc_manager check <config_file>\n");
            return 1;
        }
        // VULNERABLE: arbitrary file read as root
        printf("[*] Checking config: %s\n", argv[2]);
        FILE *f = fopen(argv[2], "r");
        if (f) {
            char buf[4096];
            while (fgets(buf, sizeof(buf), f)) {
                printf("%s", buf);
            }
            fclose(f);
        } else {
            printf("Error: Cannot open %s\n", argv[2]);
        }

    } else if (strcmp(argv[1], "log") == 0) {
        if (argc < 4) {
            printf("Usage: svc_manager log <file> <message>\n");
            return 1;
        }
        // VULNERABLE: arbitrary file write as root
        printf("[*] Logging to: %s\n", argv[2]);
        FILE *f = fopen(argv[2], "w");
        if (f) {
            fprintf(f, "%s\n", argv[3]);
            fclose(f);
            printf("[+] Log entry written\n");
        } else {
            printf("Error: Cannot write to %s\n", argv[2]);
        }

    } else if (strcmp(argv[1], "status") == 0) {
        printf("=== Service Manager Status ===\n");
        printf("  Binary: /usr/local/bin/svc_manager\n");
        printf("  SUID:   yes\n");
        printf("  Owner:  root\n");
        system("ls -la /usr/local/bin/svc_manager");

    } else {
        printf("Unknown command: %s\n", argv[1]);
        usage();
    }

    return 0;
}
