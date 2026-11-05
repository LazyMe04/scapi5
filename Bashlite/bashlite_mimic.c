/*
 * bashlite_mimic.c
 * Behavioral mimic for EM side-channel research on Raspberry Pi 5 (aarch64)
 *
 * Mô phỏng các pattern CPU + syscall điển hình của Bashlite:
 *  - Tight computational loops (flood-like activity)
 *  - Socket creation + sendto localhost (network-like syscalls)
 *  - Light forking
 *
 * AN TOÀN: Chỉ giao tiếp với 127.0.0.1, không có C2, không scan, không DDoS thật.
 * Chỉ dùng cho nghiên cứu thu thập tín hiệu EM.
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <time.h>
#include <signal.h>
#include <sys/wait.h>
#include <errno.h>

#define DURATION_SEC     2.5          /* Thời gian chạy mặc định (phù hợp paper) */
#define FLOOD_ITER       800000       /* Số vòng lặp tính toán dày */
#define SOCKET_ROUNDS    40           /* Số lần tạo socket + gửi localhost */
#define NUM_CHILDREN     2            /* Số process con nhẹ */

volatile sig_atomic_t stop_flag = 0;

void handle_signal(int sig) {
    stop_flag = 1;
}

/* Mô phỏng phần tính toán dày đặc (CPU-bound như flooder) */
void cpu_intensive_loop(unsigned long iterations) {
    volatile unsigned long x = 0;
    for (unsigned long i = 0; i < iterations && !stop_flag; i++) {
        x += i * 0x5bd1e995;
        x ^= (x >> 15);
        x *= 0x27d4eb2d;
    }
    (void)x; /* tránh bị tối ưu hóa hết */
}

/* Mô phỏng pattern socket + send (chỉ đến localhost) */
void network_like_activity(int rounds) {
    struct sockaddr_in addr;
    char buf[64];
    int sock;

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(9);               /* discard port */
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

    for (int i = 0; i < rounds && !stop_flag; i++) {
        sock = socket(AF_INET, SOCK_DGRAM, 0);
        if (sock < 0) continue;

        snprintf(buf, sizeof(buf), "mimic-%d-%ld", i, time(NULL));
        sendto(sock, buf, strlen(buf), 0,
               (struct sockaddr *)&addr, sizeof(addr));

        close(sock);

        /* Thêm một chút công việc CPU giữa các lần gửi */
        cpu_intensive_loop(12000);
    }
}

/* Process con mô phỏng hành vi fork nhẹ của botnet */
void child_worker(int id) {
    cpu_intensive_loop(FLOOD_ITER / 3);
    network_like_activity(SOCKET_ROUNDS / 2);
    _exit(0);
}

int main(int argc, char *argv[]) {
    double duration = DURATION_SEC;
    time_t start;
    pid_t pids[NUM_CHILDREN];
    int i, status;

    if (argc > 1) {
        duration = atof(argv[1]);
        if (duration <= 0.1) duration = DURATION_SEC;
    }

    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);

    printf("[bashlite_mimic] Starting on aarch64 (duration ≈ %.2fs)\n", duration);
    start = time(NULL);

    /* Tạo vài process con (mô phỏng pattern fork) */
    for (i = 0; i < NUM_CHILDREN; i++) {
        pids[i] = fork();
        if (pids[i] == 0) {
            child_worker(i);
        }
    }

    /* Process cha cũng chạy pattern chính */
    while (!stop_flag && (difftime(time(NULL), start) < duration)) {
        cpu_intensive_loop(FLOOD_ITER / 4);
        network_like_activity(SOCKET_ROUNDS / 3);
    }

    /* Chờ các process con kết thúc */
    for (i = 0; i < NUM_CHILDREN; i++) {
        if (pids[i] > 0) {
            waitpid(pids[i], &status, 0);
        }
    }

    printf("[bashlite_mimic] Finished cleanly.\n");
    return 0;
}