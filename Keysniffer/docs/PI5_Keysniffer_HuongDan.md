# Keysniffer (`kisni`) trên Raspberry Pi 5 — Hướng dẫn vận hành chi tiết

> **Trạng thái tính đến 2026-11-15:** code đã viết và đã test trên máy host, nhưng
> **chưa có trace thật nào được ghi**. Các bước dưới đây là quy trình để tạo trace đầu
> tiên, rồi mở rộng thành campaign. Tài liệu phương pháp gốc là
> [`KEYSNIFFER_PLAN.md`](../KEYSNIFFER_PLAN.md); khi tài liệu này khác plan, plan thắng.

| Trường | Giá trị |
|---|---|
| Mẫu | `kisni` — keylogger kernel, build lại từ nguồn GPL-2.0 của `jarun/spy` |
| Bản chất | **Module nhân** — không có tiến trình, không có PID, không giám sát bằng `ps` |
| Nguồn gốc | Nguồn công khai, build lại cho aarch64. **Không phải** bản `.ko` của paper |
| Thiết bị | Raspberry Pi 5, Debian 13 aarch64, kernel 6.18.x (kiểm tra lại bằng `uname -r`) |
| Máy điều khiển | Laptop Windows, `192.168.7.1`, SSH sang Pi `192.168.7.2` |
| Kết quả đúng | `debugfs_delta > 0`, `lsmod` sạch sau trace, manifest đầy đủ |

---

## 0. Đọc trước — bốn điều không được làm

Đây là **module nhân**. Một lỗi trong callback có thể panic cả máy, không chỉ chết một
tiến trình. Vì vậy:

1. **Không `insmod` trước khi có image thẻ nhớ và đường khôi phục đã kiểm chứng.**
   Pi 5 không có snapshot; image là đường rollback duy nhất.
2. **Không `insmod --force`, không tắt module signature enforcement.** Module bị từ chối
   là một blocker phải báo, không phải chướng ngại phải lách.
3. **Không nạp bản `.ko` của paper** (`kisni-4.19.57-v7+.ko` — ARMv7/kernel 4.19). Nó sẽ
   bị từ chối trên Pi 5; nếu nạp được thì đó là dấu hiệu bạn đang chạy sai kernel.
4. **Không sửa gì trong `spy_cb()`.** Hàm đó chính là đường mã đang được đo. Chỉ được sửa
   lời gọi API cơ học để biên dịch, và mọi sửa đổi phải ghi vào `PATCHES.md`.

Ngoài ra:

- **Gõ qua SSH không tạo trace.** `kisni` bắt sự kiện bàn phím console (VT). Phím gõ qua
  SSH không đi qua `kbd_handler`, nên debugfs không tăng. Đây là cách làm hỏng campaign
  phổ biến nhất.
- **Không `maK_It`**, dưới bất kỳ dạng nào.
- **Không mở ngoại lệ C2 cho family này.** `kisni` không networking.

---

## 1. Vai trò từng máy

| Máy | Vai trò | Chạy gì |
|---|---|---|
| Laptop Windows `192.168.7.1` | Build source, giữ bản gốc, điều khiển | SSH, đọc/ghi image, giữ hash |
| Raspberry Pi 5 `192.168.7.2` | Nạn nhân — nơi module chạy thật | `kisni_runner.py`, `keysynth`, `kisni.ko` |
| Máy phân tích cô lập | Clone source, đối chiếu hash | Bản sao `jarun/spy`, không lên mạng |
| Oscilloscope Picoscope 6404E | Đo EM, nhận trigger từ GPIO 17 | `pico-em-capture` |

Laptop **không bao giờ** nạp module. Nó chỉ giữ source, tạo image và soạn lệnh.

---

## 2. Chuẩn bị Raspberry Pi 5

### 2.1 Phần cứng

- Nguồn chính thức **5 V / 5 A**. Nguồn yếu gây throttle và làm hỏng toàn bộ dataset.
- Tản nhiệt chủ động. Campaign chạy hàng giờ liên tục.
- Thẻ microSD riêng cho lab — **bạn sẽ phải image nó trước khi nạp module lần đầu**.
- Cáp mạng point-to-point với laptop (không dùng WiFi khi đo).
- Với trace EM: probe 45° trên CPU, amplifier, và dây GPIO 17 → EXT/AUX của scope.

### 2.2 Ghi thẻ nhớ

Dùng Raspberry Pi Imager. Trước khi bấm **Write**, mở hộp thoại tuỳ chỉnh
(`Ctrl+Shift+X`) và đặt:

| Mục | Giá trị | Vì sao |
|---|---|---|
| Hostname | `pi5-em-target` | Tên ổn định cho tài liệu |
| Username | `emlab` | Tài khoản quản trị |
| Password | mật khẩu mạnh | Cần cho lần SSH đầu |
| Wireless LAN | để trống | Lab không dùng WiFi; `wlan0` phải down khi đo |
| Enable SSH | **bật** | Cách duy nhất vào máy không cần bàn phím |
| Password authentication | **bật** | Ban đầu; chuyển sang key ở bước 2.4 |

Nếu dùng bản Pi OS Lite, không cần desktop.

### 2.3 Lần khởi động đầu — ghi nhận môi trường

Chạy trên Pi và **ghi lại nguyên văn** các giá trị này:

```bash
uname -a
uname -r                    # chuỗi này quyết định mọi lần build module
cat /etc/os-release
cat /proc/device-tree/model | tr -d '\000'; echo
vcgencmd get_throttled      # phải là throttled=0x0
grep -E 'arm_freq|overclock|force_turbo' /boot/firmware/config.txt   # phải rỗng
cat /proc/sys/kernel/tainted                                         # phải là 0
```

> **Cảnh báo:** repo đang ghi hai phiên bản nhân khác nhau (`6.18.34` trong
> `pi5_setup_report.md`, `6.18.50` trong `BENCH_OPERATIONS.md`). Đừng giả định —
> `uname -r` trên máy thật là nguồn duy nhất. Lệch một chuỗi là module không nạp được.

### 2.4 Link bench tĩnh và SSH

Trên Pi:

```bash
sudo nmcli con add type ethernet ifname eth0 con-name bench-static \
     ipv4.method manual ipv4.addresses 192.168.7.2/24 \
     ipv4.never-default yes ipv6.method disabled
sudo nmcli con up bench-static
ip -4 addr show eth0          # phải thấy 192.168.7.2/24
ip route                      # CHỈ 192.168.7.0/24 — không có default route
```

Trên laptop:

```powershell
ssh-keygen -t ed25519 -C "emlab bench"
ssh-copy-id emlab@192.168.7.2
ssh emlab@192.168.7.2 "uname -m; id"
```

Hai bẫy thường gặp:

- Re-image Pi làm đổi host key → `ssh-keygen -R 192.168.7.2`.
- Link tĩnh không có DNS/mDNS → `pi5-em-target.local` không phân giải; dùng IP.

### 2.5 Cài công cụ khi còn internet

Làm bước này **trước** khi bật isolation, vì `apt` cần mạng.

```bash
sudo apt update
sudo apt install -y build-essential linux-headers-$(uname -r) \
                    python3 python3-venv file binutils iptables iproute2 \
                    git python3-gpiozero python3-lgpio
sudo modprobe uinput
ls -l /dev/uinput              # phải tồn tại
sudo chvt 1                    # đảm bảo có một VT đang hoạt động
```

`python3-gpiozero` + `python3-lgpio` là backend GPIO trên Pi 5. Nếu thiếu, runner vẫn
chạy nhưng ghi `status: trigger-degraded` và **không phát xung trigger** — trace EM sẽ
không có edge.

Nếu `linux-headers-$(uname -r)` không có cho kernel Raspberry Pi, thử gói meta:

```bash
apt-cache policy linux-headers-rpi-2712
ls -l /lib/modules/$(uname -r)/build          # phải trỏ tới /usr/src/linux-headers-<ver>
ls /lib/modules/$(uname -r)/Module.symvers    # cần nếu CONFIG_MODVERSIONS=y
```

### 2.6 Quyết định chữ ký module — đọc trước khi build

```bash
zgrep -E 'CONFIG_MODVERSIONS|CONFIG_MODULE_SIG|CONFIG_MODULE_SIG_FORCE|CONFIG_MODULE_SIG_ALL|CONFIG_DEBUG_FS' \
      /boot/config-$(uname -r)
```

| Cấu hình | Ý nghĩa cho kế hoạch này |
|---|---|
| `CONFIG_MODVERSIONS=y` | Phải build bằng `Module.symvers` của Pi; lệch sẽ báo *no symbol version for module_layout* |
| `CONFIG_MODULE_SIG=y`, `FORCE` không đặt | Module không ký vẫn nạp được; nhân bị taint (`G OE`) — bình thường |
| `CONFIG_MODULE_SIG_FORCE=y` | Module không ký **bị từ chối**. **Không tắt enforcement.** Ký bằng MOK cục bộ nếu có; nếu không, báo blocker và dừng |
| `CONFIG_DEBUG_FS=y` | `/sys/kernel/debug/kisni/keys` sẽ tồn tại |

**Không dùng `insmod --force`.** Ép qua version magic là cách biến bài thực tập thành một
panic không gỡ được.

---

## 3. Image thẻ nhớ, đường khôi phục, preflight

### 3.1 Image thẻ nhớ — bước không được bỏ

Thực hiện từ laptop khi thẻ nhớ đang cắm vào đầu đọc. **Kiểm tra thiết bị hai lần trước
khi đọc/ghi** — chọn sai ổ sẽ xoá dữ liệu của bạn.

**Trên Linux/WSL:**

```bash
lsblk -o NAME,SIZE,MODEL,MOUNTPOINT
sudo dd if=/dev/sdX of=pi5-prekeysniffer-$(date +%F).img \
     bs=4M status=progress conv=fsync
sha256sum pi5-prekeysniffer-$(date +%F).img > pi5-prekeysniffer-$(date +%F).img.sha256
```

**Trên Windows:** dùng Win32DiskImager hoặc balenaEtcher ở chế độ **Read** để đọc thẻ ra
file `.img`, rồi băm bằng PowerShell:

```powershell
Get-FileHash -Algorithm SHA256 .\pi5-prekeysniffer-2026-11-15.img |
    Format-List
```

Lưu file `.sha256` cạnh image. `keysni_preflight.py` kiểm tra đúng cặp
`<image>` + `<image>.sha256`.

### 3.2 Đường khôi phục khi Pi panic

Không có đường này thì **không được nạp module**. Chọn một và ghi lại bạn có cái nào:

| Cách | Cần gì | Ghi chú |
|---|---|---|
| HDMI + bàn phím USB | Màn hình, bàn phím | Đơn giản nhất, cần nhìn được màn hình |
| UART console | USB-TTL, `enable_uart=1` | Là thay đổi debug, **không phải** chỉnh xung nhịp — được phép |
| Rút thẻ và flash lại | Đầu đọc thẻ + image ở 3.1 | Luôn có, nhưng chậm |

### 3.3 Preflight — cổng kiểm tra toàn bộ điều kiện

Công cụ chỉ đọc, không ghi gì.

**Trên laptop (kiểm tra image):**

```powershell
python -I Keysniffer\keysni_preflight.py --image D:\backup\pi5-prekeysniffer-2026-11-15.img
```

Trên Windows, các kiểm tra thiết bị bị `SKIP`; phần P1 (image + `.sha256`) vẫn chạy.

**Trên Pi (kiểm tra thiết bị):**

```bash
python3 -I /home/emlab/work/tools/keysni_preflight.py
```

Image nằm trên laptop, không nằm trên Pi. Vì vậy **không truyền `--image`** khi chạy trên
Pi; công cụ trả `warn` và nhắc xác nhận thủ công. Chỉ truyền `--image PATH` khi file thật
sự có trên máy đang chạy lệnh.

Ý nghĩa kết quả:

- `ok` — đạt.
- `warn` — phải đọc; có thể chấp nhận có ghi chú.
- `fail` — **dừng lại, sửa xong mới đi tiếp.**

Các nhóm kiểm tra:

| Phase | Kiểm tra gì |
|---|---|
| P1 | Image + `.sha256`; throttle; không overclock; đường khôi phục |
| P3 | Headers đúng kernel; `Module.symvers`; `CONFIG_MODULE_SIG*`; toolchain |
| P5 | `debugfs` đã mount và không có entry `kisni` cũ; `uinput`; nhân chưa taint |

---

## 4. Lấy và ghim source

### 4.1 Trên máy phân tích cô lập

Không clone trên Windows, không clone trên Pi nếu có máy cô lập:

```bash
git clone https://github.com/jarun/spy.git
cd spy
git rev-parse HEAD | tee /tmp/src-rev.txt
sha256sum spy.c Makefile | tee /tmp/src.sha256
git log --oneline -1
```

Ghi revision và hash vào `Keysniffer/analysis_notes/KEYSNIFFER_PROVENANCE.md`.

> **Không theo nhánh.** Nếu source thay đổi giữa hai lô trace, artifact thay đổi và
> dataset không còn đồng nhất. Revision đã ghim phải nằm trong mọi manifest.

### 4.2 Chép source đã ghim sang Pi

```bash
scp -r spy emlab@192.168.7.2:/home/emlab/work/spy
```

Hoặc nén rồi chép:

```bash
tar czf spy-pinned.tar.gz spy
scp spy-pinned.tar.gz emlab@192.168.7.2:/home/emlab/work/
ssh emlab@192.168.7.2 'cd /home/emlab/work && tar xzf spy-pinned.tar.gz'
```

### 4.3 Nếu không có máy cô lập

Đây là một **deviation** phải ghi rõ. Cách chấp nhận được: clone trên Pi **khi Pi còn
internet**, ngay sau khi cài packages và **trước** khi bật isolation; ghi lại revision,
hash, thời điểm clone. Không clone từ Windows.

---

## 5. Build module cho đúng kernel đang chạy

### 5.1 Kiểm tra headers

```bash
ls -l /lib/modules/$(uname -r)/build
ls /lib/modules/$(uname -r)/Module.symvers
```

`build` phải tồn tại và trỏ tới `/usr/src/linux-headers-<ver>`. Nếu `CONFIG_MODVERSIONS=y`
mà thiếu `Module.symvers`, build sẽ tạo module không nạp được.

### 5.2 Build

```bash
cd /home/emlab/work/spy
make -C /lib/modules/$(uname -r)/build M=$PWD modules
```

### 5.3 Kiểm tra artifact

```bash
file kisni.ko
modinfo kisni.ko
modinfo -F vermagic kisni.ko
```

Kết quả phải là:

- `ELF 64-bit LSB relocatable, ARM aarch64`
- `vermagic:` trùng **chính xác** chuỗi `uname -r` (so cả chuỗi, không chỉ phần đầu)

Cảnh báo của compiler chấp nhận được. **Lỗi thì không được vá lặng lẽ.** Nếu source 4.19
không còn biên dịch, chỉ được sửa API cơ học (thay helper đã bị bỏ, sửa chữ ký hàm), mỗi
sửa đổi ghi vào `PATCHES.md` kèm diff trước/sau. **Tuyệt đối không thêm `printk`, bộ đếm,
hay đổi định dạng ghi trong `spy_cb()`.**

### 5.4 Băm và đóng băng artifact

```bash
cd /home/emlab/work/spy
sha256sum kisni.ko | tee kisni.ko.sha256

VER=$(uname -r)
HASH=$(sha256sum kisni.ko | cut -c1-12)
cp kisni.ko "/home/emlab/work/modules/kisni-${VER}-${HASH}.ko"
sha256sum "/home/emlab/work/modules/kisni-${VER}-${HASH}.ko"
```

Từ giờ **chỉ** dùng file trong `modules/`. Hash đầy đủ là thứ runner đối chiếu ở mỗi trace;
đổi file giữa campaign là làm hỏng dataset.

---

## 6. Static review trước khi nạp

Nạp module nhân là hành động đặc quyền cao nhất trong dự án. Đọc source trước khi nó chạy.

```bash
cd /home/emlab/work/spy
grep -n "module_param\|debugfs_create\|register_keyboard_notifier\|module_init\|module_exit" spy.c
```

Checklist:

- [ ] `module_init` an toàn khi lỗi: gỡ thư mục debugfs và trả mã lỗi, không để notifier
      đã đăng ký dở.
- [ ] `module_exit` gỡ notifier **trước** khi xoá thư mục.
- [ ] Callback không deref thứ có thể `NULL` (nó chạy trong ngữ cảnh ngắt — lỗi ở đây
      panic cả máy).
- [ ] Ghi buffer không vượt `BUF_LEN` (upstream kiểm tra và quay vòng; xác nhận trong bản
      đã ghim).
- [ ] Không networking, không ghi file ngoài debugfs, không tương tác tiến trình.
- [ ] Có `MODULE_LICENSE("GPL v2")` — bắt buộc cho `EXPORT_SYMBOL_GPL`.

Ghi kết quả vào `Keysniffer/analysis_notes/KEYSNIFFER_STATIC_REVIEW.md`, kèm revision đã
ghim và ghi chú rằng lab **cố ý** nạp một keylogger.

---

## 7. Build `keysynth` và chuẩn bị workload

### 7.1 Biên dịch

```bash
cd /home/emlab/work/tools
gcc -O2 -Wall -Wextra -o keysynth keysynth.c
./keysynth --help
```

Exit code của `keysynth`:

| rc | Nghĩa |
|---|---|
| 0 | Đã phát đúng số phím yêu cầu |
| 2 | Sai tham số |
| 3 | Không mở được `/dev/uinput` hoặc không tạo được thiết bị |
| 4 | Keyfile không đọc được hoặc không có ký tự gõ được |
| 5 | Ghi thiết bị thất bại (thiết bị bị gỡ giữa chừng) |

### 7.2 uinput và VT

```bash
sudo modprobe uinput
ls -l /dev/uinput
sudo chvt 1
```

`keysynth` tạo một thiết bị `uinput` khai báo `EV_KEY` với keycode thông thường. Thiết bị
này được `kbd_match()` chấp nhận và bind vào console keyboard handler, nên sự kiện mới
tới được `spy_cb()`.

### 7.3 Keyfile — bắt buộc cho hai cell typing

```bash
mkdir -p /home/emlab/work/keys
printf '%s\n' 'the quick brown fox jumps over the lazy dog 0123456789' \
    > /home/emlab/work/keys/keys.txt
sha256sum /home/emlab/work/keys/keys.txt
```

Chỉ dùng ký tự mà `keysynth` map được: chữ cái, chữ số, space, enter, tab, `. , - ;`.
Ký tự khác bị bỏ qua (không lỗi), nhưng làm workload khó so sánh hơn.

> **Đừng bỏ `--keyfile`.** Runner chỉ ghi `keystroke_file_sha256` khi keyfile tồn tại.
> Nếu cả hai cell typing đều không có keyfile, analyzer thấy `None` và báo
> *"typing cells used different keyfiles"* — dù thực tế cả hai dùng chuỗi built-in.

Tham số workload phải **giữ nguyên** trong toàn dataset:

| Tham số | Giá trị | Vì sao |
|---|---|---|
| `--rate` | 20 phím/giây | 50 ms/key; ~50 phím trong 2,5 s |
| `--duration` | 2,5 s | Cùng cửa sổ với các trace khác |
| keyfile | một file, đã băm | So sánh được giữa hai cell |
| injector | `uinput` | Không trộn với USB HID trong một dataset |

### 7.4 Cổng ba trường hợp — quan trọng nhất

Phải chứng minh đủ ba trường hợp **trước** khi chụp trace thật.

**Trường hợp A — module nạp + `keysynth` gõ:**

```bash
KO=/home/emlab/work/modules/kisni-$(uname -r)-<hash>.ko
sudo insmod "$KO" codes=1
ls -l /sys/kernel/debug/kisni/keys

BEFORE=$(sudo cat /sys/kernel/debug/kisni/keys | wc -c)
sudo /home/emlab/work/tools/keysynth \
     --keyfile /home/emlab/work/keys/keys.txt --rate 20 --duration 2.5
AFTER=$(sudo cat /sys/kernel/debug/kisni/keys | wc -c)
echo "before=$BEFORE after=$AFTER delta=$((AFTER-BEFORE))"

sudo rmmod kisni
```

Kỳ vọng: `delta > 0`, xấp xỉ số phím đã gõ (mỗi phím là một record). Trên kernel
6.18.50+rpt-rpi-2712, `smoke03` với 50 phím và `codes=1` cho delta = **160 byte** ổn định
trên 96/96 trace — dùng con số này làm mốc hiệu chuẩn, không phải làm yêu cầu tuyệt đối.

> **Đừng dùng `stat -c %s` (kể cả `ls -l`).** debugfs tạo inode với `i_size = 0` và
> handler đọc của module (`simple_read_from_buffer`) không cập nhật nó, nên trên kernel
> 6.18.50+rpt-rpi-2712 `stat` báo `0` **cả trước lẫn sau** dù buffer đã có 160 byte. Chỉ
> độ dài của dữ liệu `read` trả về mới phản ánh nội dung buffer; runner đo đúng theo cách
> này.

**Trường hợp B — không có module:**

```bash
ls /sys/kernel/debug/kisni 2>/dev/null || echo "no debugfs entry (correct)"
sudo /home/emlab/work/tools/keysynth \
     --keyfile /home/emlab/work/keys/keys.txt --rate 20 --duration 1
ls /sys/kernel/debug/kisni 2>/dev/null || echo "still absent (correct)"
```

**Trường hợp C — chỉ SSH, không `keysynth`:**

```bash
sudo insmod "$KO" codes=1
BEFORE=$(sudo cat /sys/kernel/debug/kisni/keys | wc -c)
# Bây giờ gõ vài phím trong chính phiên SSH này
AFTER=$(sudo cat /sys/kernel/debug/kisni/keys | wc -c)
echo "before=$BEFORE after=$AFTER"
sudo rmmod kisni
```

Kỳ vọng: `AFTER == BEFORE` — chứng minh SSH không tới notifier.

> **Nếu trường hợp A không tăng:** kiểm tra `chvt 1`, `/dev/uinput`, và chạy lại.
> **Nếu trường hợp C có tăng:** mô hình của tài liệu này sai; dừng lại và xem xét trước khi
> chụp bất cứ trace nào.

### 7.5 Reboot sau cổng kiểm tra

Ba trường hợp trên đã nạp module, nên `/proc/sys/kernel/tainted` khác 0. **Reboot Pi**
trước trace thật đầu tiên:

```bash
sudo reboot
# sau khi lên lại:
cat /proc/sys/kernel/tainted      # phải là 0
vcgencmd get_throttled            # phải là throttled=0x0
lsmod | grep kisni || echo "clean"
ls /sys/kernel/debug/kisni 2>/dev/null || echo "no stale entry"
```

---

## 8. Diễn tập nạp/gỡ 50 lần

Làm trên trạng thái image dùng một lần, không có gì quý trên thẻ.

```bash
KO=/home/emlab/work/modules/kisni-$(uname -r)-<hash>.ko

for i in $(seq 1 50); do
    sudo insmod "$KO" codes=1 || { echo "FAIL load $i"; break; }
    sudo rmmod kisni        || { echo "FAIL unload $i"; break; }
    echo "cycle $i ok"
done

lsmod | grep kisni || echo "clean"
sudo dmesg | tail -20
```

Vì sao 50 lần: module rò một notifier hoặc một dentry mỗi lần nạp sẽ panic ở lần thứ 60,
không phải lần đầu. Một lần nạp/gỡ sạch không chứng minh được gì.

Bảng xử lý lỗi:

| Triệu chứng | Ý nghĩa | Hành động |
|---|---|---|
| `insmod: Invalid module format` | Lệch vermagic | Build lại cho đúng kernel; **không** ép |
| `insmod: Unknown symbol module_layout` | Lệch `Module.symvers` / modversions | Cài headers đúng, build lại |
| `Operation not permitted` | Signature enforcement | Xem bảng 2.6; **không** tắt enforcement |
| dmesg có Oops khi nạp | Đường `module_init` hỏng | Lưu trace, sửa source, review lại |
| Máy treo | Panic | Tắt nguồn, đọc log/serial, ghi lại, flash lại image |

**Sau 50 chu trình, reboot** để xoá taint trước trace thật đầu tiên.

---

## 9. Dry run runner

Chạy được trên bất kỳ host nào, không root, không module. Mục đích: kiểm tra CLI và shape
manifest.

```bash
python3 -I /home/emlab/work/tools/kisni_runner.py \
    --mode kisni-typing --count 2 --duration 0.1 \
    --run-dir /tmp/kisni_dry
```

Manifest sinh ra có `dry_run: true` trong từng dòng. Analyzer sẽ **từ chối** dataset kiểu
này — đúng như mong đợi, vì nó có đúng shape nhưng không có phép đo.

---

## 10. Trace thật đầu tiên

Chỉ làm sau khi mục 3–9 đều đạt.

### 10.1 Kiểm tra trước phiên

```bash
cat /proc/sys/kernel/tainted        # 0
vcgencmd get_throttled             # throttled=0x0
lsmod | grep kisni || echo clean
ls /sys/kernel/debug/kisni 2>/dev/null || echo "no stale entry"
ls -l /dev/uinput
```

### 10.2 Chép và bật isolation

`isolation-on.sh` nằm trong `Bashlite/`, không phải thư mục gốc repo:

```bash
# trên laptop, trong thư mục gốc repo
scp Bashlite/isolation-on.sh isolation-off.sh \
    emlab@192.168.7.2:/home/emlab/work/tools/
```

Trên Pi:

```bash
sudo bash /home/emlab/work/tools/isolation-on.sh \
     --admin 192.168.7.1 --no-redirect
```

Kiểm tra:

```bash
sudo iptables -S OUTPUT | head
# phải thấy -P OUTPUT DROP
```

Ghi chú: script vẫn mở OUTPUT tới `C2_HOST` (mặc định `192.168.7.1`). `kisni` không dùng
đường này. Nếu muốn siết hơn, đặt `--c2` vào một địa chỉ không tồn tại trên bench (ví dụ
`192.0.2.1`); SSH vẫn hoạt động nhờ rule `ESTABLISHED,RELATED`.

**Không** dùng `--redirect`/DNAT cho family này.

### 10.3 Arm scope trước khi chạy runner

Runner nạp module, settle **1,0 s**, rồi mới kéo GPIO 17 lên mức cao. Nếu scope chưa arm,
edge sẽ bị bỏ lỡ.

Thứ tự đúng:

1. Cấu hình scope: 2 MHz, cửa sổ 2,5 s, trigger **rising edge** trên EXT/AUX (hoặc channel B).
2. Arm scope ở chế độ single-shot.
3. Chạy runner.
4. Kiểm tra trace bắt đầu đúng edge, không có pre-roll dài.

Nối dây: GPIO 17 → EXT/AUX của scope, mass chung → GND của Pi. Dùng đồng hồ đo xác nhận
3,3 V trước khi nối. Ghi lại phương án trigger đã chọn vào
`analysis_notes/KEYSNIFFER_PROVENANCE.md`.

### 10.4 Chạy một trace

```bash
KO=/home/emlab/work/modules/kisni-$(uname -r)-<hash>.ko
HASH=<sha256 đầy đủ của .ko>

sudo python3 -I /home/emlab/work/tools/kisni_runner.py \
    --module "$KO" \
    --expected-hash "$HASH" --execute \
    --mode kisni-typing \
    --keysynth /home/emlab/work/tools/keysynth \
    --keyfile /home/emlab/work/keys/keys.txt --rate 20 \
    --count 1 --duration 2.5 --trigger gpio17 \
    --run-dir /home/emlab/work/manifests/smoke01
```

Trace đầu tiên **không** truyền `--allow-taint`. Nếu nhân đã taint sẵn vì thứ khác, runner
phải từ chối, và bạn cần biết điều đó trước trace đầu chứ không phải sau 3000 trace.

### 10.5 Đọc manifest

Manifest là JSONL, mỗi dòng một trace. Các trường phải đúng:

| Trường | Phải là | Nghĩa |
|---|---|---|
| `status` | `ok` | Chu trình hoàn tất |
| `debugfs_delta` | **> 0** | Module thật sự đã ghi — bằng chứng chính |
| `keystroke_count` | ~50 (20 phím/s × 2,5 s) | Injector thực sự đã gõ |
| `lsmod_after` | `false` | Module đã gỡ sạch |
| `keysynth_leftover` | `false` | Không còn tiến trình injector |
| `module_sha256` | khớp hash đã ghim | Đúng artifact |
| `dmesg_taint` | có `G OE` | Bình thường với module ngoài cây nguồn |
| `trigger_edge_ns_on/off` | có giá trị | Trigger đã thực sự đổi trạng thái |

> **`debugfs_delta = 0` nghĩa là dừng lại.** Module nạp được nhưng không ghi gì: hoặc
> `keysynth` không tới được VT, hoặc module không nhận sự kiện. Trace khi đó gần giống
> nhân sạch và **không sửa được sau này**.

`debugfs_delta` âm là **wrap** của buffer 16 KB, không phải lỗi: record vẫn được ghi,
nhưng byte delta là cận dưới. Ghi chú lại và dùng `keystroke_count` cho trace đó.

### 10.6 Kỳ vọng của analyzer trên smoke dataset

```bash
python3 -I /home/emlab/work/tools/keysni_analyze.py \
    /home/emlab/work/manifests/smoke01/manifest.jsonl
```

Với **một cell**, analyzer sẽ trả **khác 0** vì `2x2 ablation incomplete: missing cell(s)
...`. Đó là hành vi đúng, không phải trace hỏng. Điều cần kiểm tra là không có problem nào
khác: `status` sạch, `debugfs_delta > 0`, không có `no-activity`.

`smoke03` trên kernel 6.18.50+rpt-rpi-2712 là ví dụ đã đạt: 96/96 trace `ok`,
`debugfs_delta = 160`, và analyzer chỉ báo thiếu 3 cell đối chứng.

Analyzer cũng coi việc **các manifest không mô tả cùng một thí nghiệm** là problem, không
phải warning: khác `expected_hash`, kernel, `codes=`, trigger/GPIO pin, rate, duration,
injector, schema hoặc runner version (chi tiết ở §12).

Analyzer chỉ trả 0 khi dataset có **đủ bốn cell**. Đừng "sửa" bằng cách bỏ qua cảnh báo.

---

## 11. Các trace tiếp theo và campaign 2×2

### 11.1 `--allow-taint` từ trace thứ hai

Lần nạp module đầu tiên đã làm nhân taint, và cờ này chỉ xoá được bằng reboot. Trace thứ
hai trở đi sẽ bị từ chối nếu không có `--allow-taint`:

```bash
sudo python3 -I /home/emlab/work/tools/kisni_runner.py ... --allow-taint ...
```

Đó không phải lỗi — nó ngăn mọi manifest quy nhầm một taint có sẵn cho `kisni`. Mask thật
được ghi trong từng dòng manifest.

### 11.2 Bốn cell

| Cell | Module | Gõ phím | Vai trò |
|---|---|---|---|
| `kisni-typing` | có | có | **Lớp malware** |
| `typing-only` | không | có | Benign đối chứng **cùng workload** |
| `kisni-idle` | có | không | Footprint nền của module |
| `idle` | không | không | Tham chiếu idle sẵn có |

Campaign tối thiểu theo plan là hai cell typing, nhưng `keysni_analyze.py` coi **đủ bốn
cell** là bắt buộc. Nếu chỉ chụp hai, kết quả phải ghi rõ là chưa hoàn chỉnh.

**Lưu ý CLI:** với `--execute`, runner luôn đòi `--module` và `--expected-hash`, kể cả ở
`typing-only` và `idle`. Ở hai mode đó runner **không nạp** module, nhưng vẫn kiểm tra
hash/vermagic và ghi hash vào manifest.

Ví dụ `typing-only`:

```bash
sudo python3 -I /home/emlab/work/tools/kisni_runner.py \
    --module "$KO" --expected-hash "$HASH" --execute \
    --mode typing-only \
    --keysynth /home/emlab/work/tools/keysynth \
    --keyfile /home/emlab/work/keys/keys.txt --rate 20 \
    --count 20 --duration 2.5 --trigger gpio17 --allow-taint \
    --run-dir /home/emlab/work/manifests/run01-typing-only
```

Ví dụ `kisni-idle` (không cần `--keysynth`/`--keyfile`):

```bash
sudo python3 -I /home/emlab/work/tools/kisni_runner.py \
    --module "$KO" --expected-hash "$HASH" --execute \
    --mode kisni-idle --count 10 --duration 2.5 \
    --trigger gpio17 --allow-taint \
    --run-dir /home/emlab/work/manifests/run01-kisni-idle
```

Ví dụ `idle`:

```bash
sudo python3 -I /home/emlab/work/tools/kisni_runner.py \
    --module "$KO" --expected-hash "$HASH" --execute \
    --mode idle --count 10 --duration 2.5 \
    --trigger gpio17 --allow-taint \
    --run-dir /home/emlab/work/manifests/run01-idle
```

### 11.3 Volume, thời gian, dung lượng

| Cell | Trace | Thời gian (~3,2 s/trace) | Đĩa (~40 MB/trace) |
|---|---|---|---|
| `kisni-typing` | 3 000 | ~2,7 h | ~120 GB |
| `typing-only` | 3 000 | ~2,7 h | ~120 GB |
| `kisni-idle` | 1 000 (tuỳ chọn) | ~0,9 h | ~40 GB |
| `idle` | 1 000 (tuỳ chọn) | ~0,9 h | ~40 GB |

Đủ bốn cell là khoảng **320 GB**, cộng headroom 10% thành khoảng **350 GB**. Đừng đoán —
chạy tool trước trace đầu tiên:

```bash
python3 -I capacity_plan.py --out /home/emlab/work/runs --traces 2000 --cells 4
```

`capacity_plan.py` nằm ở thư mục gốc repo. Nếu chạy trên Pi, chép nó sang trước:

```bash
scp capacity_plan.py emlab@192.168.7.2:/home/emlab/work/tools/
```

Nếu phải giảm dung lượng: ghi `int16` thay vì `float64` giảm 4 lần, nhưng phải sửa **cả**
`pico-em-capture/capture.py` **và** `em_analysis.py`, và phải làm **trước** trace đầu tiên.

### 11.4 Quy tắc phiên đo

- `vcgencmd get_throttled` = `0x0` trước và sau mỗi phiên.
- `wlan0` down, radio soft-blocked.
- Không di chuyển Pi, probe, hay amplifier trong một dataset.
- Manifest append-only; resume bằng `--count` + `--run-dir`.
- Đầu mỗi phiên, xác minh lại hash module; `.ko` đổi là dataset vô hiệu.
- Sau mỗi 100 trace: `lsmod` sạch, `dmesg` không có Oops.
- Chụp `typing-only` và `kisni-typing` **xen kẽ theo block**, không chụp hết cell này rồi
  sang cell kia. Drift nhiệt độ/khí hậu sẽ ảnh hưởng đều cả hai cell thay vì giả làm
  khác biệt lớp.
- Nếu máy panic giữa campaign: phiên kết thúc; reimage, rồi resume từ dòng manifest cuối.

---

## 12. Kiểm tra dataset trước khi train

```bash
python3 -I /home/emlab/work/tools/keysni_analyze.py \
    /home/emlab/work/manifests/run01/manifest.jsonl
```

Analyzer trả khác 0 khi:

- ablation chưa đủ bốn cell;
- hai cell typing khác keyfile hoặc khác rate;
- module buffer bị tái sử dụng (`debugfs_bytes_before != 0`);
- có trace thất bại;
- module không ghi gì (`kisni-typing` toàn delta 0);
- dataset chỉ có dry run;
- **các manifest không mô tả cùng một thí nghiệm**: khác `expected_hash` (build
  `.ko` khác), `kernel_release`, `codes=`, `trigger`/`gpio_pin`, `rate`,
  `duration_s`, `injector`, `schema`/`runner_version`, hoặc trường
  `module_sha256`/`kernel_release` lệch giữa các trace.

Phân tích tối thiểu trước khi có bất kỳ kết luận ML nào:

- `kisni-typing` và `typing-only` phải có cùng số phím và cùng độ dài cửa sổ.
- Spectrogram STFT 8192/4096, chọn band bằng NICV, theo paper.
- Chạy classifier **có** và **không** có ablation `typing-only`, báo cả hai số. Khoảng cách
  giữa chúng là thước đo trung thực cho việc classifier học bàn phím hay học rootkit.

---

## 13. Dọn dẹp cuối campaign

```bash
sudo rmmod kisni
lsmod | grep kisni || echo "clean"
sudo pkill -f keysynth
sudo bash /home/emlab/work/tools/isolation-off.sh

# Giữ source + hash, không giữ binary:
rm -f /home/emlab/work/modules/*.ko
```

Giữ lại: source đã ghim, `git rev-parse HEAD`, hash `spy.c`/`Makefile`, hash `.ko`,
manifest, image.

---

## 14. Xử lý sự cố

| Triệu chứng | Nguyên nhân thường gặp | Cách sửa |
|---|---|---|
| `insmod: Invalid module format` | Vermagic khác kernel đang chạy | `modinfo -F vermagic` so với `uname -r`; build lại. Không `--force` |
| `Unknown symbol module_layout` | Build không dùng `Module.symvers` của Pi | Cài `linux-headers-$(uname -r)`, build lại |
| `Operation not permitted` khi `insmod` | `CONFIG_MODULE_SIG_FORCE=y` | Ký bằng MOK cục bộ nếu có; nếu không, **báo blocker và dừng** |
| `/sys/kernel/debug/kisni` không có | debugfs chưa mount, hoặc `CONFIG_DEBUG_FS` tắt | `mount -t debugfs none /sys/kernel/debug`; xem bảng 2.6 |
| `debugfs_delta = 0` | `keysynth` không tới VT, hoặc không ai gõ | `sudo chvt 1`; chạy lại cổng 7.4; kiểm tra `/dev/uinput` |
| `status: trigger-degraded` | Thiếu `gpiozero`/`lgpio`, hoặc không mở được GPIO | Cài `python3-gpiozero python3-lgpio`; kiểm tra quyền; trace EM **không dùng được** |
| `keysynth` rc=2 | Sai tham số | Xem `./keysynth --help` |
| `keysynth` rc=3 | Không mở được `/dev/uinput` | `sudo modprobe uinput`; chạy bằng root |
| `keysynth` rc=4 | Keyfile rỗng/không đọc được | Kiểm tra `--keyfile`; dùng ký tự map được |
| `keysynth` rc=5 | Ghi thiết bị thất bại | Thiết bị uinput bị gỡ giữa chừng; chạy lại |
| `--allow-taint` bị đòi | Nhân đã taint trước khi nạp | **Reboot Pi** rồi đo lại; hoặc chấp nhận và ghi rõ trong manifest |
| Runner từ chối containment | Không có policy `OUTPUT DROP` | Chạy `isolation-on.sh` trước |
| Runner báo `not Linux` | Chạy `--execute` trên Windows | Chạy trên Pi; dry run thì được |
| Runner báo hash mismatch | Sai `--expected-hash` hoặc `.ko` đã đổi | Băm lại file; không dùng binary khác |
| Analyzer báo ablation thiếu cell | Chưa chụp đủ bốn cell | Đúng như thiết kế — chụp thêm, hoặc ghi rõ dataset chưa hoàn chỉnh |
| Analyzer từ chối dataset dry run | Chỉ có trace `dry_run: true` | Đúng như thiết kế — chạy trace thật |
| Pi treo khi `rmmod` | Rò notifier hoặc dentry | Flash lại image ở 3.1; đọc dmesg; ghi lại số chu trình đã chạy |
| `ssh` báo host key thay đổi | Đã re-image | `ssh-keygen -R 192.168.7.2` |

---

## 15. Checklist trước khi đo

- [ ] Image thẻ nhớ đã chụp **và** có file `.sha256`.
- [ ] Đường khôi phục sau panic đã xác định cụ thể (HDMI/UART/flash lại).
- [ ] `vcgencmd get_throttled` = `0x0`.
- [ ] `/proc/sys/kernel/tainted` = `0` sau lần reboot gần nhất.
- [ ] Không có `arm_freq` / `force_turbo` trong `/boot/firmware/config.txt`.
- [ ] `ip route` trên Pi chỉ có `192.168.7.0/24`.
- [ ] `rfkill block wifi` đã chạy, `wlan0` DOWN.
- [ ] Isolation đã bật; `curl`/`nc` ra internet đều thất bại.
- [ ] `keysni_preflight.py` không còn dòng `fail`.
- [ ] Source đã ghim revision và hash.
- [ ] `vermagic` của `.ko` trùng đúng `uname -r`.
- [ ] Static review đã điền đủ 6 mục.
- [ ] 50 chu trình nạp/gỡ sạch, `lsmod` không còn `kisni`, **đã reboot**.
- [ ] `keysynth` biên dịch được, `/dev/uinput` mở được, `chvt 1` đã chạy.
- [ ] Cổng 7.4 đã chứng minh đủ ba trường hợp.
- [ ] `debugfs_delta > 0` trên trace thật đầu tiên.
- [ ] Scope đã arm trước runner; trace bắt đầu đúng trigger edge.
- [ ] Dung lượng đĩa đã kiểm tra bằng `capacity_plan.py`.
- [ ] Vị trí Pi, probe, amplifier đã ghi lại và sẽ không đổi trong dataset.

---

## 16. Những gì phải ghi vào luận văn

- Revision nguồn đã ghim (`git rev-parse HEAD`) và `sha256sum spy.c Makefile`.
- Hash của `kisni.ko` đã build, và **vermagic** của nó.
- Đây là **same-source re-instantiation trên kernel 6.18**, không phải sao chép trace của
  paper.
- Suy luận danh tính nguồn là `jarun/spy` — ghi rõ là *inferred*, trừ khi đã đối chiếu được
  `.ko` gốc.
- `PATCHES.md` nếu có sửa API, kèm diff, và xác nhận **không sửa gì trong `spy_cb()`**.
- Cấu hình Pi: `uname -a`, `/etc/os-release`, `dpkg -l`, danh sách service đang chạy.
- `vcgencmd get_throttled` trước và sau mỗi phiên.
- `/proc/sys/kernel/tainted` trước khi nạp, và mask taint sau khi nạp.
- Keyfile đã dùng (hash), rate, số phím mỗi cửa sổ.
- Chọn injector (`uinput` hay USB HID) và lý do; xác nhận không trộn trong một dataset.
- 2×2 ablation: cell nào đã chụp, cell nào không, và vì sao.
- Kết quả `keysni_analyze.py` trên dataset cuối.
- Dung lượng thực tế đã dùng và số trace mỗi cell.
- Hạn chế đã biết: một họ rootkit thay vì hai (paper); 6404E thay vì 6407; `uinput` thay vì
  gõ thật; độ trễ ~200 ms của phím đầu tiên sau trigger edge.

---

## Phụ lục A — Toàn bộ lệnh theo thứ tự

Thay `<ver>` bằng `uname -r`, `<hash>` bằng hash thật.

### A.1 Trên Pi — khi còn internet

```bash
sudo apt update
sudo apt install -y build-essential linux-headers-$(uname -r) \
                    python3 python3-venv file binutils iptables iproute2 \
                    git python3-gpiozero python3-lgpio
sudo modprobe uinput
sudo chvt 1

# Nếu có máy cô lập: bỏ qua clone ở đây và scp source đã ghim sang.
# Nếu không: clone trước khi bật isolation, rồi ghim ngay.
git clone https://github.com/jarun/spy.git /home/emlab/work/spy
cd /home/emlab/work/spy
git rev-parse HEAD
sha256sum spy.c Makefile
```

### A.2 Trên laptop — image và chép công cụ

```bash
# Linux/WSL
lsblk -o NAME,SIZE,MODEL,MOUNTPOINT
sudo dd if=/dev/sdX of=pi5-prekeysniffer-$(date +%F).img bs=4M status=progress conv=fsync
sha256sum pi5-prekeysniffer-$(date +%F).img > pi5-prekeysniffer-$(date +%F).img.sha256

# Chép công cụ
scp Keysniffer/kisni_runner.py Keysniffer/keysni_preflight.py \
    Keysniffer/keysni_analyze.py Keysniffer/tools/keysynth.c \
    Bashlite/isolation-on.sh isolation-off.sh capacity_plan.py \
    emlab@192.168.7.2:/home/emlab/work/tools/
```

### A.3 Trên Pi — preflight, build, ghim

```bash
python3 -I /home/emlab/work/tools/keysni_preflight.py

cd /home/emlab/work/spy
make -C /lib/modules/$(uname -r)/build M=$PWD modules
file kisni.ko && modinfo kisni.ko
sha256sum kisni.ko
cp kisni.ko /home/emlab/work/modules/kisni-$(uname -r)-$(sha256sum kisni.ko | cut -c1-12).ko
```

### A.4 Trên Pi — diễn tập và build injector

```bash
KO=/home/emlab/work/modules/kisni-$(uname -r)-<hash>.ko

for i in $(seq 1 50); do
    sudo insmod "$KO" codes=1 || break
    sudo rmmod kisni || break
done
lsmod | grep kisni || echo clean
sudo reboot

cd /home/emlab/work/tools
gcc -O2 -Wall -Wextra -o keysynth keysynth.c
printf '%s\n' 'the quick brown fox jumps over the lazy dog 0123456789' \
    > /home/emlab/work/keys/keys.txt
sha256sum /home/emlab/work/keys/keys.txt
```

### A.5 Trên Pi — trace đầu tiên

```bash
sudo bash /home/emlab/work/tools/isolation-on.sh \
     --admin 192.168.7.1 --no-redirect

sudo python3 -I /home/emlab/work/tools/kisni_runner.py \
    --module "$KO" --expected-hash <sha256> --execute \
    --mode kisni-typing \
    --keysynth /home/emlab/work/tools/keysynth \
    --keyfile /home/emlab/work/keys/keys.txt --rate 20 \
    --count 1 --duration 2.5 --trigger gpio17 \
    --run-dir /home/emlab/work/manifests/smoke01

python3 -I /home/emlab/work/tools/keysni_analyze.py \
    /home/emlab/work/manifests/smoke01/manifest.jsonl
# Kỳ vọng: non-zero vì "ablation incomplete" — đúng với dataset một cell.
```

### A.6 Dọn dẹp

```bash
sudo rmmod kisni; lsmod | grep kisni || echo clean
sudo pkill -f keysynth
sudo bash /home/emlab/work/tools/isolation-off.sh
```

---

## Phụ lục B — Bản đồ file trên Pi

```text
/home/emlab/work/
├── tools/            script + keysynth (KHÔNG để lẫn với .ko)
│   ├── kisni_runner.py
│   ├── keysni_preflight.py
│   ├── keysni_analyze.py
│   ├── keysynth.c
│   ├── keysynth
│   ├── isolation-on.sh
│   ├── isolation-off.sh
│   └── capacity_plan.py
├── spy/              source đã ghim (giữ .git để biết revision)
├── modules/          kisni-<ver>-<hash>.ko + .sha256
├── keys/             keys.txt (chuỗi gõ cố định)
└── manifests/        JSONL kết quả từng phiên
```

Vì sao tách thư mục: Python nạp module từ thư mục hiện tại. Để script chung với file lạ có
thể khiến một `json.py` độc hại được nạp thay cho thư viện thật.

---

## Phụ lục C — Manifest và ý nghĩa

Mỗi trace là một dòng JSONL. Các trường đáng chú ý:

| Trường | Ý nghĩa |
|---|---|
| `mode` | `kisni-typing`, `typing-only`, `kisni-idle`, `idle` |
| `dry_run` | `true` = không nạp module, không gõ; analyzer từ chối dataset toàn dry run |
| `module_sha256` | Hash `.ko`; phải khớp artifact đã ghim |
| `module_vermagic` | Phải khớp `uname -r` |
| `kernel_release` | Kernel lúc chạy |
| `module_load_monotonic_ns` / `module_unload_monotonic_ns` | Thời điểm nạp/gỡ, ngoài cửa sổ trigger |
| `debugfs_bytes_before` / `_after` / `debugfs_delta` | Bằng chứng module có ghi; `delta = 0` là lỗi, âm là wrap |
| `keystroke_file_sha256` | Hash keyfile; phải giống nhau giữa hai cell typing |
| `keystroke_count` | Số phím `keysynth` báo qua `emitted=N` |
| `keystroke_interval_ms` | Suy ra từ `--rate`; phải giống nhau giữa hai cell typing |
| `injector` | `uinput` hoặc `hid`; không trộn |
| `dmesg_taint` | Taint sau khi nạp; `G OE` là bình thường |
| `lsmod_after` | `false` = module đã gỡ sạch |
| `keysynth_leftover` | `false` = không còn tiến trình injector |
| `trigger_edge_ns_on` / `_off` | Cửa sổ trigger thực tế |
| `window_ns` | Độ dài cửa sổ đo được |
| `status` | `ok` là giá trị duy nhất chấp nhận cho trace tốt |

---

## Phụ lục D — Khác biệt so với Bashlite

| Tiêu chí | Bashlite | Keysniffer |
|---|---|---|
| Trigger | GPIO 17, mức cao | **Giống hệt** |
| Settle trước lần đo | 1,0 s | **Giống hệt** |
| Độ dài cửa sổ | `--duration` (2,5 s) | **Giống hệt** |
| Shape manifest | JSONL | **Giống hệt**, thêm trường riêng của module |
| Cái được giám sát | Tiến trình (có PID) | **Module nhân — không có PID** |
| Dọn dẹp giữa trace | Giết cây tiến trình + sweep `/proc` | `rmmod` + xác nhận `lsmod` sạch |
| Nguồn hoạt động | C2 giả gửi lệnh | `keysynth` gõ phím |
| Rủi ro chính | Mẫu thoát containment | **Panic cả máy** |
| Containment | Cần mở port C2 | Policy `OUTPUT DROP` là đủ, không mở port |
