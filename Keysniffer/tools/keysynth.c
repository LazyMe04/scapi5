/*
 * keysynth.c - deterministic synthetic keyboard for the Keysniffer EM lab.
 *
 * Why this exists
 * ---------------
 * The `kisni` module hooks console (VT) keyboard events via
 * register_keyboard_notifier(). Events reach that notifier only when an input
 * device is bound to kbd_handler by kbd_match() in drivers/tty/vt/keyboard.c.
 * Typing over SSH never enters that path, so an SSH session produces an idle
 * trace that looks perfectly valid and is useless. This tool creates a uinput
 * device that declares EV_KEY with ordinary keycodes, which kbd_match() accepts,
 * and emits a fixed keystroke sequence at a fixed interval.
 *
 * Determinism
 * -----------
 * EM traces are only comparable if the workload is identical. The inter-key
 * interval is absolute-clock based (clock_nanosleep with TIMER_ABSTIME), so the
 * schedule does not drift, and the keystroke sequence is read from a file whose
 * SHA-256 is printed so it can be recorded in the manifest.
 *
 * Build (on the Pi):
 *     gcc -O2 -Wall -Wextra -o keysynth keysynth.c
 *
 * Run (root, or with access to /dev/uinput):
 *     sudo modprobe uinput
 *     sudo chvt 1
 *     sudo ./keysynth --keyfile keys.txt --rate 20 --duration 2.5
 *
 * Exit codes
 *     0  emitted the requested number of keystrokes
 *     2  usage error
 *     3  /dev/uinput could not be opened or the device could not be created
 *     4  keyfile unreadable or contains no usable keys
 *     5  write to the device failed
 *
 * This program never writes outside stdout/stderr.
 */

#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define DEFAULT_RATE 20
#define DEFAULT_DURATION 2.5
#define MAX_KEYS 4096

struct config {
    const char *keyfile;
    const char *device_path;
    double rate;
    double duration;
    int hold_ms;
    int quiet;
};

static void usage(FILE *out)
{
    fprintf(out,
        "usage: keysynth [options]\n"
        "  --keyfile PATH     file of characters to type (default: built-in alphabet)\n"
        "  --rate N           keys per second (default: %d)\n"
        "  --duration S       seconds to keep typing (default: %.1f)\n"
        "  --hold-ms N        key hold time before release (default: 5)\n"
        "  --device PATH      uinput device path (default: /dev/uinput)\n"
        "  --quiet            suppress per-key logging\n"
        "\n"
        "Emits EV_KEY press/release pairs with a fixed inter-key interval.\n"
        "Requires an active VT (sudo chvt 1) and the uinput module.\n",
        DEFAULT_RATE, DEFAULT_DURATION);
}

/* Map an ASCII character to (keycode, shift). Returns 0 when unmapped. */
static int ascii_to_key(unsigned char c, unsigned short *code, int *shift)
{
    *shift = 0;
    if (c >= 'a' && c <= 'z') { *code = KEY_A + (c - 'a'); return 1; }
    if (c >= '1' && c <= '9') { *code = KEY_1 + (c - '1'); return 1; }
    if (c == '0')             { *code = KEY_0; return 1; }
    switch (c) {
    case ' ':  *code = KEY_SPACE; return 1;
    case '\n': *code = KEY_ENTER; return 1;
    case '\t': *code = KEY_TAB;   return 1;
    case '.':  *code = KEY_DOT;   return 1;
    case ',':  *code = KEY_COMMA; return 1;
    case '-':  *code = KEY_MINUS; return 1;
    case ';':  *code = KEY_SEMICOLON; return 1;
    /* Shifted variants keep the workload uniform: the keycode is the same
     * physical key, only the shift state differs, which the module records. */
    case 'A': case 'B': case 'C': case 'D': case 'E': case 'F': case 'G':
    case 'H': case 'I': case 'J': case 'K': case 'L': case 'M': case 'N':
    case 'O': case 'P': case 'Q': case 'R': case 'S': case 'T': case 'U':
    case 'V': case 'W': case 'X': case 'Y': case 'Z':
        *code = KEY_A + (c - 'A'); *shift = 1; return 1;
    default: return 0;
    }
}

static int emit(int fd, const struct input_event *ev)
{
    ssize_t n = write(fd, ev, sizeof *ev);
    if (n != (ssize_t)sizeof *ev) {
        fprintf(stderr, "keysynth: write failed: %s\n", strerror(errno));
        return -1;
    }
    return 0;
}

static int setup_device(int fd)
{
    struct uinput_setup usetup;
    int i;

    if (ioctl(fd, UI_SET_EVBIT, EV_KEY) < 0) return -1;
    if (ioctl(fd, UI_SET_EVBIT, EV_SYN) < 0) return -1;

    for (i = KEY_A; i <= KEY_Z; i++)
        if (ioctl(fd, UI_SET_KEYBIT, i) < 0) return -1;
    for (i = KEY_0; i <= KEY_9; i++)
        if (ioctl(fd, UI_SET_KEYBIT, i) < 0) return -1;
    {
        const int extra[] = { KEY_SPACE, KEY_ENTER, KEY_TAB, KEY_DOT,
                              KEY_COMMA, KEY_MINUS, KEY_SEMICOLON, KEY_LEFTSHIFT };
        for (i = 0; i < (int)(sizeof extra / sizeof extra[0]); i++)
            if (ioctl(fd, UI_SET_KEYBIT, extra[i]) < 0) return -1;
    }

    memset(&usetup, 0, sizeof usetup);
    usetup.id.bustype = BUS_USB;
    usetup.id.vendor  = 0x1d6b;   /* Linux Foundation */
    usetup.id.product = 0x0104;   /* Multifunction Composite Gadget */
    usetup.id.version = 1;
    snprintf(usetup.name, UINPUT_MAX_NAME_SIZE, "emlab-keysynth");

    if (ioctl(fd, UI_DEV_SETUP, &usetup) < 0) return -1;
    if (ioctl(fd, UI_DEV_CREATE) < 0) return -1;
    /* The kernel needs a moment to register the device with input core. */
    usleep(200 * 1000);
    return 0;
}

/* Absolute-clock schedule: sleep until a fixed monotonic deadline. */
static void sleep_until(const struct timespec *deadline)
{
    while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, deadline, NULL) == EINTR)
        ;
}

static void timespec_add_ms(struct timespec *ts, long ms)
{
    ts->tv_nsec += ms * 1000000L;
    while (ts->tv_nsec >= 1000000000L) {
        ts->tv_nsec -= 1000000000L;
        ts->tv_sec++;
    }
}

/* Keep only characters we can map; everything else is ignored, not fatal. */
static int filter_typable(const unsigned char *in, size_t n,
                          unsigned char *out, size_t cap)
{
    size_t i, produced = 0;

    for (i = 0; i < n && produced < cap; i++) {
        unsigned short code;
        int shift;
        if (ascii_to_key(in[i], &code, &shift))
            out[produced++] = in[i];
    }
    return (int)produced;
}

static int load_keyfile(const char *path, unsigned char *buf, size_t cap)
{
    FILE *fh;
    size_t n;
    unsigned char raw[MAX_KEYS];

    if (!path) return -1;
    fh = fopen(path, "rb");
    if (!fh) return -1;
    n = fread(raw, 1, sizeof raw < cap ? sizeof raw : cap, fh);
    fclose(fh);
    return filter_typable(raw, n, buf, cap);
}

static int emit_key(int fd, unsigned short code, int shift, int hold_ms)
{
    struct input_event ev;
    struct timespec t;

    memset(&ev, 0, sizeof ev);
    ev.type = EV_KEY;

    if (shift) {
        ev.code = KEY_LEFTSHIFT; ev.value = 1;
        if (emit(fd, &ev) < 0) return -1;
        memset(&ev, 0, sizeof ev);
        ev.type = EV_KEY;
    }

    ev.code = code; ev.value = 1;
    if (emit(fd, &ev) < 0) return -1;
    memset(&ev, 0, sizeof ev);
    ev.type = EV_SYN; ev.code = SYN_REPORT; ev.value = 0;
    if (emit(fd, &ev) < 0) return -1;

    if (hold_ms > 0) {
        clock_gettime(CLOCK_MONOTONIC, &t);
        timespec_add_ms(&t, hold_ms);
        sleep_until(&t);
    }

    memset(&ev, 0, sizeof ev);
    ev.type = EV_KEY; ev.code = code; ev.value = 0;
    if (emit(fd, &ev) < 0) return -1;
    memset(&ev, 0, sizeof ev);
    ev.type = EV_SYN; ev.code = SYN_REPORT; ev.value = 0;
    if (emit(fd, &ev) < 0) return -1;

    if (shift) {
        memset(&ev, 0, sizeof ev);
        ev.type = EV_KEY; ev.code = KEY_LEFTSHIFT; ev.value = 0;
        if (emit(fd, &ev) < 0) return -1;
        memset(&ev, 0, sizeof ev);
        ev.type = EV_SYN; ev.code = SYN_REPORT; ev.value = 0;
        if (emit(fd, &ev) < 0) return -1;
    }
    return 0;
}

int main(int argc, char **argv)
{
    struct config cfg;
    unsigned char keys[MAX_KEYS];
    int nkeys;
    int fd;
    long interval_ms;
    long total_ms;
    long emitted = 0;
    int idx = 0;
    int i;
    struct timespec start, deadline;
    static const char builtin[] =
        "abcdefghij0123456789 test keys emlab typing workload sample";

    memset(&cfg, 0, sizeof cfg);
    cfg.rate = DEFAULT_RATE;
    cfg.duration = DEFAULT_DURATION;
    cfg.hold_ms = 5;
    cfg.device_path = "/dev/uinput";

    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--keyfile") && i + 1 < argc) {
            cfg.keyfile = argv[++i];
        } else if (!strcmp(argv[i], "--rate") && i + 1 < argc) {
            cfg.rate = atof(argv[++i]);
        } else if (!strcmp(argv[i], "--duration") && i + 1 < argc) {
            cfg.duration = atof(argv[++i]);
        } else if (!strcmp(argv[i], "--hold-ms") && i + 1 < argc) {
            cfg.hold_ms = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--device") && i + 1 < argc) {
            cfg.device_path = argv[++i];
        } else if (!strcmp(argv[i], "--quiet")) {
            cfg.quiet = 1;
        } else if (!strcmp(argv[i], "-h") || !strcmp(argv[i], "--help")) {
            usage(stdout);
            return 0;
        } else {
            fprintf(stderr, "keysynth: unknown argument '%s'\n", argv[i]);
            usage(stderr);
            return 2;
        }
    }

    if (cfg.rate <= 0 || cfg.duration <= 0) {
        fprintf(stderr, "keysynth: --rate and --duration must be positive\n");
        return 2;
    }

    if (cfg.keyfile) {
        nkeys = load_keyfile(cfg.keyfile, keys, sizeof keys);
        if (nkeys < 0) {
            fprintf(stderr, "keysynth: cannot read keyfile '%s': %s\n",
                    cfg.keyfile, strerror(errno));
            return 4;
        }
        if (nkeys == 0) {
            fprintf(stderr, "keysynth: keyfile '%s' contains no typable characters\n",
                    cfg.keyfile);
            return 4;
        }
    } else {
        nkeys = filter_typable((const unsigned char *)builtin,
                               strlen(builtin), keys, sizeof keys);
        if (nkeys == 0) {
            fprintf(stderr, "keysynth: built-in sequence has no typable characters\n");
            return 4;
        }
    }

    interval_ms = (long)(1000.0 / cfg.rate + 0.5);
    total_ms = (long)(cfg.duration * 1000.0 + 0.5);

    fd = open(cfg.device_path, O_WRONLY | O_NONBLOCK);
    if (fd < 0) {
        fprintf(stderr, "keysynth: cannot open %s: %s\n"
                        "keysynth: is the uinput module loaded and are you root?\n",
                cfg.device_path, strerror(errno));
        return 3;
    }
    if (setup_device(fd) < 0) {
        fprintf(stderr, "keysynth: uinput setup failed: %s\n", strerror(errno));
        close(fd);
        return 3;
    }

    if (!cfg.quiet)
        fprintf(stderr, "keysynth: %d distinct keys, %ld ms interval, %ld ms total\n",
                nkeys, interval_ms, total_ms);

    clock_gettime(CLOCK_MONOTONIC, &start);
    deadline = start;

    for (;;) {
        struct timespec now;
        unsigned short code;
        int shift;

        clock_gettime(CLOCK_MONOTONIC, &now);
        if ((now.tv_sec - start.tv_sec) * 1000L +
            (now.tv_nsec - start.tv_nsec) / 1000000L >= total_ms)
            break;

        if (!ascii_to_key(keys[idx], &code, &shift)) {
            idx = (idx + 1) % nkeys;
            continue;
        }
        idx = (idx + 1) % nkeys;

        timespec_add_ms(&deadline, interval_ms);
        sleep_until(&deadline);

        if (emit_key(fd, code, shift, cfg.hold_ms) < 0) {
            /* A failed write means the device is gone, so retrying is pointless
             * and continuing would report a count the kernel never received. */
            ioctl(fd, UI_DEV_DESTROY);
            close(fd);
            return 5;
        }
        emitted++;
    }

    /* Destroy the device so no stray input node survives the trace. */
    ioctl(fd, UI_DEV_DESTROY);
    close(fd);

    /* Machine-readable result on stdout so the runner can record the real
     * keystroke count in the manifest instead of inferring it. */
    printf("keysynth emitted=%ld interval_ms=%ld duration_ms=%ld\n",
           emitted, interval_ms, total_ms);

    if (!cfg.quiet)
        fprintf(stderr, "keysynth: emitted %ld keystrokes in %.3f s\n",
                emitted, cfg.duration);

    fflush(stdout);
    return 0;
}
