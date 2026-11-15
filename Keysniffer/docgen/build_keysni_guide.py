#!/usr/bin/env python3
"""Generate the Vietnamese operator guide for the Keysniffer (`kisni`) run.

Build:  uv run --no-project --with python-docx python -I Keysniffer/docgen/build_keysni_guide.py
Output: KEYSniffer_HuongDan.docx in Keysniffer/docs/.

The document mirrors Bashlite/docgen/build_pi5_guide.py in structure and tone on
purpose: an operator who has read the Bashlite guide should recognise every
chapter here. What differs is the content, because this family is measured
differently — there is no process to supervise, no C2 to spoof, and the module
can panic the machine.
"""
import os
import re
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(_ROOT, "Keysniffer", "docs", "PI5_Keysniffer_HuongDan.docx")

doc = Document()

# ---- page + base style ------------------------------------------------------
for s in doc.sections:
    s.page_width, s.page_height = Cm(21.0), Cm(29.7)
    s.left_margin = s.right_margin = Cm(2.0)
    s.top_margin = s.bottom_margin = Cm(2.0)

normal = doc.styles["Normal"]
normal.font.name = "Calibri"
normal.font.size = Pt(10.5)
normal.paragraph_format.space_after = Pt(6)
normal.paragraph_format.line_spacing = 1.12

for name, size, color in (("Heading 1", 18, "1F3864"),
                          ("Heading 2", 13.5, "2F5496"),
                          ("Heading 3", 11.5, "2F5496")):
    st = doc.styles[name]
    st.font.name = "Calibri"
    st.font.size = Pt(size)
    st.font.color.rgb = RGBColor.from_string(color)
    st.paragraph_format.space_before = Pt(14 if name == "Heading 1" else 10)
    st.paragraph_format.space_after = Pt(6)

TOKEN = re.compile(r"(\*\*.+?\*\*|`.+?`)")


def _runs(par, text, size=None, bold=False):
    for part in TOKEN.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            # Recurse so inline code inside a bold span is still rendered as code.
            _runs(par, part[2:-2], size=size, bold=True)
            continue
        if part.startswith("`") and part.endswith("`") and len(part) > 2:
            r = par.add_run(part[1:-1]); r.font.name = "Consolas"
            r.font.size = Pt(size if size else 9.5)
            r.bold = True if bold else None
        else:
            r = par.add_run(part)
            r.bold = True if bold else None
            if size:
                r.font.size = Pt(size)


def p(text, style=None):
    par = doc.add_paragraph(style=style)
    _runs(par, text)
    return par


def bullet(text):
    return p(text, style="List Bullet")


def numbered(text):
    return p(text, style="List Number")


def _plain(text):
    """Headings are plain text: drop the inline-markup characters."""
    return text.replace("**", "").replace("`", "")


def h1(text):
    return doc.add_heading(_plain(text), level=1)


def h2(text):
    return doc.add_heading(_plain(text), level=2)


def h3(text):
    return doc.add_heading(_plain(text), level=3)


def _shade(cell, fill):
    """Shade a table cell. Cell shading avoids paragraph-XML child ordering issues."""
    pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), fill)
    pr.append(shd)


def code(text):
    """Monospace block inside a one-cell table: boxed, shaded, wraps internally."""
    t = doc.add_table(rows=1, cols=1)
    t.style = "Table Grid"
    # Keep a command block on one page: a block split across a page break is
    # exactly where a command gets mis-copied.
    t.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
    cell = t.rows[0].cells[0]
    _shade(cell, "F2F2F2")
    cell.text = ""
    par = cell.paragraphs[0]
    par.paragraph_format.space_before = Pt(2)
    par.paragraph_format.space_after = Pt(2)
    par.paragraph_format.line_spacing = 1.0
    r = par.add_run(text.strip("\n"))
    r.font.name = "Consolas"; r.font.size = Pt(8.5)
    r.font.color.rgb = RGBColor.from_string("1A1A1A")
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_after = Pt(2)
    spacer.paragraph_format.space_before = Pt(0)
    return t


def table(headers, rows, widths=None, font_size=9):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = t.rows[0].cells
    for i, htxt in enumerate(headers):
        hdr[i].text = ""
        par = hdr[i].paragraphs[0]
        r = par.add_run(htxt); r.bold = True; r.font.size = Pt(font_size)
        _shade(hdr[i], "DEEAF6")
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            par = cells[i].paragraphs[0]
            _runs(par, str(val), size=font_size)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def callout(kind, title, text):
    fill = {"warn": "FFF2CC", "info": "DEEAF6", "danger": "FBE4E4"}[kind]
    t = doc.add_table(rows=1, cols=1)
    t.style = "Table Grid"
    cell = t.rows[0].cells[0]
    _shade(cell, fill)
    cell.text = ""
    par = cell.paragraphs[0]
    _runs(par, title, size=10, bold=True)
    par2 = cell.add_paragraph()
    _runs(par2, text, size=10)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def kv_block(pairs):
    table(["Trường", "Giá trị"], pairs, widths=[5.0, 12.0])


def page_break():
    doc.add_page_break()


def footer():
    f = doc.sections[0].footer
    par = f.paragraphs[0]
    par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = par.add_run("Pi 5 + Keysniffer (kisni) — Hướng dẫn vận hành   |   trang ")
    run.font.size = Pt(8); run.font.color.rgb = RGBColor.from_string("808080")
    fld1 = OxmlElement("w:fldChar"); fld1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve"); instr.text = "PAGE"
    fld2 = OxmlElement("w:fldChar"); fld2.set(qn("w:fldCharType"), "end")
    run._r.append(fld1); run._r.append(instr); run._r.append(fld2)


# ============================================================================
# COVER
# ============================================================================
tp = doc.add_paragraph(); tp.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = tp.add_run("RASPBERRY PI 5  ·  EM SIDE-CHANNEL LAB")
r.font.size = Pt(11); r.font.color.rgb = RGBColor.from_string("808080"); r.bold = True

t = doc.add_paragraph(); t.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = t.add_run("Keysniffer (kisni) trên Pi 5\nModule nhân ghi phím vào debugfs")
r.font.size = Pt(26); r.bold = True; r.font.color.rgb = RGBColor.from_string("1F3864")

s = doc.add_paragraph(); s.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = s.add_run("Hướng dẫn thực hành — từ build module đến trace đầu tiên")
r.font.size = Pt(13); r.italic = True; r.font.color.rgb = RGBColor.from_string("2F5496")

doc.add_paragraph()
kv_block([
    ["Mẫu", "`kisni` — keylogger kernel, build lại từ nguồn GPL-2.0 của `jarun/spy`"],
    ["Bản chất", "**Module nhân** — không có tiến trình, không có PID, không thể giám sát bằng `ps`"],
    ["Nguồn gốc", "Nguồn công khai, build lại cho aarch64. **Không phải** bản `.ko` của paper"],
    ["Thiết bị đo", "Raspberry Pi 5, Debian 13 aarch64, kernel 6.18.50"],
    ["Máy điều khiển", "Laptop Windows, `192.168.7.1`, SSH sang Pi"],
    ["Ngày soạn", "2026-11-09"],
])
doc.add_paragraph()

callout("danger", "Rủi ro khác hẳn Bashlite",
        "Đây là **module nhân**. Một lỗi trong `spy_cb()` gây panic cả máy, không phải chết một "
        "tiến trình. Phải image thẻ nhớ trước khi `insmod` lần đầu, và phải có đường khôi phục "
        "đã kiểm chứng. Chương 4 nói rõ hơn.")

callout("info", "Tài liệu này dành cho ai",
        "Người vận hành đã đọc qua hướng dẫn Bashlite. Cấu trúc giống hệt bản đó, nhưng nội dung "
        "khác vì bản chất phép đo khác: ở đây không có malware để chạy, mà có một module nằm "
        "trong nhân và một bàn phím giả để nó có việc làm.")

page_break()

# ============================================================================
# TOC
# ============================================================================
h1("Mục lục")
toc = [
    ("Chương 1", "Hiểu nhanh trước khi làm"),
    ("Chương 2", "`kisni` là gì và hoạt động thế nào"),
    ("Chương 3", "Chuẩn bị Raspberry Pi 5"),
    ("Chương 4", "Quy tắc an toàn — đọc kỹ"),
    ("Chương 5", "Chạy: từng bước thực hành"),
    ("Chương 6", "Bộ đối chứng 2×2 — vì sao phải có hai cell"),
    ("Chương 7", "Xử lý sự cố"),
    ("Phụ lục A", "Toàn bộ lệnh theo thứ tự"),
    ("Phụ lục B", "Bản đồ file trên Pi"),
    ("Phụ lục C", "Checklist trước khi đo"),
    ("Phụ lục D", "Những gì phải ghi vào luận văn"),
]
table(["Phần", "Nội dung"], toc, widths=[3.0, 14.0], font_size=10)

page_break()

# ============================================================================
# CHUONG 1
# ============================================================================
h1("Chương 1 — Hiểu nhanh trước khi làm")

h2("1.1 Mục tiêu của cả quá trình")
p("Ta muốn ghi lại **tín hiệu điện từ (EM)** phát ra từ chip Raspberry Pi 5 khi nó đang chạy "
  "một rootkit trong nhân, rồi so sánh với tín hiệu khi nhân hoàn toàn sạch. Máy phân loại sau "
  "này sẽ học từ hai tập tín hiệu đó.")
p("Vì vậy có ba yêu cầu không thể bỏ:")
numbered("Module phải **thực sự được nạp** vào nhân trên silicon thật — không phải mô phỏng, không phải trên Windows.")
numbered("Nó phải **làm việc thật** trong suốt cửa sổ đo — phải có phím được gõ để callback của nó chạy.")
numbered("Mọi thứ khác phải **giữ nguyên** so với lần đo goodware — cùng bản OS, cùng service, cùng trigger, cùng cửa sổ.")

h2("1.2 Cái gì chạy ở đâu")
table(["Máy", "Vai trò", "Chạy gì"], [
    ["Laptop Windows (192.168.7.1)", "Build source, giữ bản gốc, điều khiển", "SSH client, soạn tài liệu, giữ hash"],
    ["Raspberry Pi 5 (192.168.7.2)", "Nạn nhân — nơi module chạy thật", "`kisni_runner.py`, `keysynth`, module `kisni.ko`"],
    ["Máy phân tích cô lập", "Clone source, đối chiếu hash", "Bản sao `jarun/spy`, không lên mạng"],
    ["Oscilloscope (chưa có)", "Đo tín hiệu EM", "—"],
], widths=[5.0, 6.0, 6.0])
p("Điểm quan trọng: **laptop không bao giờ nạp module**. Nó chỉ giữ source và soạn lệnh.")

h2("1.3 Từ điển tối thiểu")
table(["Thuật ngữ", "Nghĩa đơn giản"], [
    ["Kernel module", "Đoạn mã được nạp vào **nhân** Linux lúc máy đang chạy. Chạy với toàn quyền, không có PID."],
    ["`insmod` / `rmmod`", "Nạp / gỡ module. `lsmod` liệt kê module đang có."],
    ["`vermagic`", "Chuỗi định danh phiên bản nhân mà module được build cho. Lệch một ký tự là từ chối nạp."],
    ["`debugfs`", "Hệ thống file ảo để nhân xuất dữ liệu gỡ lỗi. Ở đây là `/sys/kernel/debug/kisni/keys`."],
    ["`keyboard_notifier`", "Cơ chế của nhân cho phép mã đăng ký nhận sự kiện bàn phím."],
    ["VT / console", "Bàn phím ảo gắn với màn hình console. **SSH không đi qua đường này.**"],
    ["`uinput`", "Cơ chế tạo thiết bị nhập liệu giả từ user space — dùng để gõ phím bằng tay không."],
    ["Taint", "Cờ trong nhân báo rằng đã có mã ngoài cây nguồn được nạp. Không xoá được nếu không reboot."],
    ["Ablation", "Phép đối chứng: bỏ đi đúng một biến để chứng minh biến đó là nguyên nhân khác biệt."],
    ["GPIO trigger", "Một chân của Pi phát xung báo cho oscilloscope bắt đầu ghi."],
], widths=[4.0, 13.0])

page_break()

# ============================================================================
# CHUONG 2
# ============================================================================
h1("Chương 2 — kisni là gì và hoạt động thế nào")

h2("2.1 Danh tính")
kv_block([
    ["Tên module", "`kisni` (dòng mã của dự án `jarun/spy`, đổi tên từ `keysniffer`)"],
    ["Tác giả", "Arun Prakash Jana"],
    ["Giấy phép", "GPL v2"],
    ["Chức năng", "*Sniff and log keys pressed in the system to debugfs*"],
    ["File log", "`/sys/kernel/debug/kisni/keys`, quyền `0400`, buffer vòng 16 KB"],
    ["Tham số", "`codes` — 0 = chữ theo keymap, 1 = hex, 2 = thập phân"],
    ["Bản paper dùng", "`kisni-4.19.57-v7+.ko` (ARMv7, kernel 4.19) — **không nạp được trên Pi 5**"],
])
callout("warn", "Đây là suy luận có căn cứ, không phải bằng chứng",
        "Paper chỉ ghi tên file. Dự án công khai khớp mô tả là `jarun/spy`, module tên `kisni`, "
        "mô tả trùng khớp. Độ tin cậy cao nhưng **chưa chứng minh**. Trong luận văn phải ghi là "
        "*suy luận (inferred)*, trừ khi lấy được file `.ko` gốc của paper và so `modinfo`.")

h2("2.2 Vì sao phải build lại, trong khi Bashlite thì không")
p("Đây là câu hỏi quan trọng nhất về mặt phương pháp, và trả lời sai sẽ làm hỏng phần kết luận.")
table(["Artifact", "Nguồn gốc", "Được build lại?"], [
    ["Bashlite", "ELF in-the-wild, đóng. SHA-256 chính là danh tính", "**Không** — build lại là thay toolchain của tác giả, mẫu không còn là in-the-wild"],
    ["Keysniffer (`kisni`)", "Nguồn mở GPL-2.0. Bản của paper **chính là** một lần build nguồn này", "**Có, có điều kiện** — danh tính là revision nguồn, không phải hash một binary"],
], widths=[3.6, 7.4, 6.0], font_size=8.5)
p("Cái giá phải trả, nói thẳng:")
bullet("Trace không còn mô tả mã input/VT của kernel 4.19, mà là của 6.18.")
bullet("Vì vậy đây là **cùng nguồn, tái hiện trên phần cứng mới** (same-source re-instantiation), không phải sao chép lại trace của paper. Luận văn phải viết đúng như vậy.")
bullet("Hành vi của module (bắt sự kiện bàn phím console, ghi vào debugfs) giữ nguyên — đó chính là thuộc tính mà classifier được kỳ vọng nắm bắt.")

h2("2.3 Nó hoạt động thế nào")
p("Module làm đúng bốn việc, theo thứ tự trong `spy.c`:")
numbered("`module_init` tạo thư mục `kisni` trong `/sys/kernel/debug` rồi tạo file `keys`.")
numbered("Đăng ký một `keyboard_notifier` với nhân.")
numbered("Mỗi lần có phím trên console, `spy_cb()` được gọi: đọc `keycode`, `shift`, `down`, ghi một dòng vào buffer.")
numbered("`module_exit` gỡ notifier **trước**, rồi mới xoá thư mục.")

callout("danger", "Không sửa gì trong spy_cb()",
        "Hàm này **chính là** đường mã đang được đo. Thêm một `printk`, một bộ đếm, hay đổi định "
        "dạng ghi đều làm artifact thay đổi và mọi trace trở nên vô nghĩa. Nếu buộc phải sửa để "
        "biên dịch trên 6.18, chỉ được sửa lời gọi API và phải ghi vào `PATCHES.md`.")

h2("2.4 Điểm chết người: SSH không đi qua notifier")
p("`kisni` bắt sự kiện của **console (VT) keyboard**. Sự kiện chỉ tới notifier khi một thiết bị "
  "nhập liệu được bind vào `kbd_handler` trong `drivers/tty/vt/keyboard.c`. Gõ qua SSH **không** "
  "đi qua đường đó.")
table(["Cách gõ", "Có tới `spy_cb()`?", "Kết quả trace"], [
    ["Gõ qua SSH", "❌ Không", "Trace **rỗng**, trông giống máy rảnh — và vô dụng"],
    ["Bàn phím vật lý trên Pi", "✅ Có", "Đúng, nhưng không thể tự động hoá"],
    ["`uinput` giả lập (`keysynth`)", "✅ Có", "Đúng, và lặp lại được — **đây là lựa chọn**"],
    ["Pi Pico làm USB HID", "✅ Có", "Đúng, nhưng thêm workload USB — không trộn với `uinput`"],
], widths=[5.5, 4.0, 7.5])
callout("danger", "Đây là cách làm hỏng cả campaign phổ biến nhất",
        "Bỏ 10 phút gõ SSH để \"kiểm tra xem module có chạy không\", rồi thấy debugfs không tăng, "
        "tưởng module hỏng. Hoặc tệ hơn: không kiểm tra, chụp 3000 trace, và cả 3000 trace đều rỗng. "
        "Chương 5 có bước kiểm tra bắt buộc cho việc này.")

h2("2.5 Vì sao phải nạp lại module cho từng trace")
p("Buffer debugfs chỉ có 16 KB và **không thể truncate từ user space**. Nếu module nạp một lần rồi "
  "chạy 3000 trace, byte count sẽ tăng mãi rồi quay vòng, và delta giữa hai lần đọc mất ý nghĩa.")
p("Vì vậy mỗi trace là **một chu trình nạp − gõ − gỡ**. Việc nạp/gỡ nằm **ngoài** cửa sổ trigger, "
  "nên đường mã nạp module không làm nhiễm trace.")

h2("2.6 Vì sao cấu trúc này tạo ra tín hiệu EM")
p("Rootkit nằm trong nhân không có vòng lặp tính toán. Tín hiệu của nó đến từ chỗ khác:")
bullet("Mỗi lần có phím, `spy_cb()` chạy **trong nhân**, chen vào đường xử lý ngắt — một đỉnh ngắn nhưng rất đều.")
bullet("Hàm ghi vào buffer debugfs chạy ở chế độ nhân, khác hẳn đường user space của goodware.")
bullet("Nhịp gõ cố định (20 phím/giây) tạo ra một chuỗi đỉnh tuần hoàn.")
p("Đó là lý do phải kiểm tra cửa sổ **có phím thật** trước khi tin bất kỳ trace nào: không có phím "
  "thì module chỉ là mã nằm im trong bộ nhớ nhân, và tín hiệu không khác nhân sạch.")

page_break()

# ============================================================================
# CHUONG 3
# ============================================================================
h1("Chương 3 — Chuẩn bị Raspberry Pi 5")

h2("3.1 Phần cứng và nguồn")
bullet("Nguồn chính thức 5 V / 5 A. Nguồn yếu gây throttle, làm hỏng toàn bộ dataset.")
bullet("Tản nhiệt chủ động. Một campaign 3000 trace chạy hàng giờ liên tục.")
bullet("Thẻ microSD riêng cho lab — **bạn sẽ phải image nó trước khi nạp module lần đầu**.")
callout("warn", "Điều kiện tiên quyết tuyệt đối",
        "Pi phải là thiết bị bạn **có thể xoá sạch và cài lại mà không mất gì**. Pi 5 không có "
        "snapshot; image thẻ nhớ là **đường rollback duy nhất**. Nếu không có, dừng lại.")

h2("3.2 Ghi thẻ nhớ")
p("Dùng Raspberry Pi Imager. Trước khi bấm Write, mở hộp thoại tuỳ chỉnh (Ctrl+Shift+X):")
table(["Mục", "Giá trị", "Vì sao"], [
    ["Hostname", "`pi5-em-target`", "Tên ổn định cho tài liệu"],
    ["Username", "`emlab`", "Tài khoản quản trị"],
    ["Password", "mật khẩu mạnh", "Cần cho lần SSH đầu"],
    ["Wireless LAN", "để trống", "Lab không dùng WiFi; `wlan0` phải down khi đo"],
    ["Enable SSH", "**bật**", "Cách duy nhất vào máy không cần bàn phím"],
    ["Password authentication", "**bật**", "Ban đầu; chuyển sang key ở bước 3.6"],
], widths=[4.0, 5.5, 7.5])

h2("3.3 Lần khởi động đầu và ghi nhận môi trường")
code("""uname -a
uname -r                     # ghi lại CHÍNH XÁC chuỗi này
cat /etc/os-release
vcgencmd get_throttled       # phải là throttled=0x0
grep -E 'arm_freq|overclock|force_turbo' /boot/firmware/config.txt   # phải rỗng
cat /proc/device-tree/model | tr -d '\\000'; echo""")
callout("warn", "Hai tài liệu đang ghi hai phiên bản nhân khác nhau",
        "`pi5_setup_report.md` ghi `6.18.34`, `BENCH_OPERATIONS.md` ghi `6.18.50`. Mọi lần build "
        "module đều gắn chặt với chuỗi `uname -r`, nên phải tự kiểm tra lại. Giả định một chuỗi "
        "sai sẽ dẫn tới module không nạp được ở bước sau.")

h2("3.4 Image thẻ nhớ — bước không được bỏ")
p("Thực hiện từ laptop, khi thẻ nhớ đang cắm vào đầu đọc:")
code("""lsblk -o NAME,SIZE,MODEL,MOUNTPOINT
sudo dd if=/dev/sdX of=pi5-prekeysniffer-$(date +%F).img \\
     bs=4M status=progress conv=fsync
sha256sum pi5-prekeysniffer-$(date +%F).img > pi5-prekeysniffer-$(date +%F).img.sha256""")
callout("danger", "Kiểm tra /dev/sdX hai lần trước khi dd",
        "`dd` ghi sai thiết bị sẽ xoá ổ của bạn. Đối chiếu dung lượng và MODEL với thẻ nhớ.")

h2("3.5 Đường khôi phục khi Pi panic")
p("Không có đường này thì không được nạp module. Chọn một và **ghi lại bạn có cái nào**:")
table(["Cách", "Cần gì", "Ghi chú"], [
    ["HDMI + bàn phím USB", "Màn hình, bàn phím", "Đơn giản nhất, cần nhìn được màn hình"],
    ["UART console", "USB-TTL, `enable_uart=1`", "Là thay đổi debug, **không phải** chỉnh xung nhịp — được phép"],
    ["Rút thẻ và flash lại", "Đầu đọc thẻ + file image ở 3.4", "Luôn có, nhưng chậm"],
], widths=[4.0, 5.0, 8.0])

h2("3.6 Link bench tĩnh và SSH")
code("""# trên Pi
sudo nmcli con add type ethernet ifname eth0 con-name bench-static \\
     ipv4.method manual ipv4.addresses 192.168.7.2/24 \\
     ipv4.never-default yes ipv6.method disabled
sudo nmcli con up bench-static
ip -4 addr show eth0          # 192.168.7.2/24
ip route                      # CHỈ 192.168.7.0/24 — không có default route""")
code("""# trên laptop
ssh-keygen -t ed25519 -C "emlab bench"
ssh-copy-id emlab@192.168.7.2
ssh emlab@192.168.7.2 'uname -m; id'""")
callout("warn", "Hai cái bẫy SSH (giống bản Bashlite)",
        "**(1)** Re-image Pi đổi host key → `ssh-keygen -R 192.168.7.2`. "
        "**(2)** Link tĩnh không có DNS/mDNS → `pi5-em-target.local` không phân giải, dùng IP.")

h2("3.7 Cài công cụ trên Pi — làm khi còn internet")
p("Bước này phải xong **trước** khi bật isolation, vì `apt` cần mạng.")
code("""sudo apt update
sudo apt install -y build-essential linux-headers-$(uname -r) \\
                    python3 python3-venv file binutils iptables iproute2 \\
                    git python3-gpiozero python3-lgpio
sudo modprobe uinput
ls -l /dev/uinput              # phải tồn tại
sudo chvt 1                    # đảm bảo có một VT đang hoạt động""")
p("`python3-gpiozero` + `python3-lgpio` là backend GPIO trên Pi 5. Thiếu chúng, runner "
  "vẫn chạy nhưng ghi `status: trigger-degraded` và **không phát xung trigger** — trace EM "
  "sẽ không có edge.")
p("Nếu `linux-headers-$(uname -r)` không có cho kernel của Raspberry Pi, thử gói meta:")
code("""apt-cache policy linux-headers-rpi-2712
ls -l /lib/modules/$(uname -r)/build        # phải trỏ tới /usr/src/linux-headers-<ver>
ls /lib/modules/$(uname -r)/Module.symvers  # cần nếu CONFIG_MODVERSIONS=y""")

h2("3.8 Quyết định chữ ký module")
p("Trước khi build, đọc cấu hình nhân để biết module có nạp được không:")
code("""zgrep -E 'CONFIG_MODVERSIONS|CONFIG_MODULE_SIG|CONFIG_MODULE_SIG_FORCE|CONFIG_MODULE_SIG_ALL|CONFIG_DEBUG_FS' \\
      /boot/config-$(uname -r)""")
table(["Cấu hình", "Ý nghĩa cho kế hoạch này"], [
    ["`CONFIG_MODVERSIONS=y`", "Phải build bằng `Module.symvers` của Pi; lệch sẽ báo *no symbol version for module_layout*"],
    ["`CONFIG_MODULE_SIG=y`, `FORCE` không đặt", "Module không ký vẫn nạp được; nhân bị taint (`G OE`) — bình thường"],
    ["`CONFIG_MODULE_SIG_FORCE=y`", "Module không ký **bị từ chối**. **Không tắt enforcement.** Báo blocker và dừng"],
    ["`CONFIG_DEBUG_FS=y`", "`/sys/kernel/debug/kisni/keys` sẽ tồn tại"],
], widths=[6.0, 11.0])
callout("danger", "Không bao giờ insmod --force",
        "Ép qua version magic là cách biến một bài thực tập thành một panic không gỡ được. "
        "Module bị từ chối thì báo blocker, không tìm đường vòng.")

h2("3.9 Chép công cụ lên Pi")
code("""# trên laptop, trong thư mục gốc repo
scp Keysniffer/kisni_runner.py Keysniffer/keysni_preflight.py \\
    Keysniffer/keysni_analyze.py Keysniffer/tools/keysynth.c \\
    Bashlite/isolation-on.sh isolation-off.sh preflight.sh capacity_plan.py \\
    emlab@192.168.7.2:/home/emlab/work/tools/""")
p("Trên Pi, tạo cấu trúc thư mục và tài khoản chạy:")
code("""sudo adduser --disabled-password --gecos "" emlab-run
sudo passwd -l emlab-run
sudo install -d -o emlab -g emlab -m 0750 \\
     /home/emlab/work/{tools,modules,keys,manifests}""")

page_break()

# ============================================================================
# CHUONG 4
# ============================================================================
h1("Chương 4 — Quy tắc an toàn — đọc kỹ")

h2("4.1 Bốn điều không bao giờ làm")
numbered("**Không nạp module trước khi có image thẻ nhớ.** Image là đường rollback duy nhất; Pi 5 không có snapshot.")
numbered("**Không `insmod --force`, không tắt module signature enforcement.** Bị từ chối là blocker phải báo, không phải chướng ngại phải lách.")
numbered("**Không nạp bản `.ko` của paper.** `kisni-4.19.57-v7+.ko` là ARMv7/kernel 4.19, sẽ bị từ chối — và nếu nạp được thì đó là bằng chứng bạn đang chạy kernel sai.")
numbered("**Không `maK_It`, dưới bất kỳ dạng nào.** Nguồn không công bố qua cùng đường, và nó thêm hidden-module, packet-sniffer, reverse-shell — nằm ngoài lập luận của lab.")

h2("4.2 Trước mỗi phiên đo")
table(["Kiểm tra", "Ngưỡng", "Vì sao"], [
    ["`vcgencmd get_throttled`", "`throttled=0x0`", "CPU throttle đổi tần số giữa chừng; trace trông vẫn hợp lệ"],
    ["`/proc/sys/kernel/tainted`", "`0` trước khi nạp", "Nếu đã taint vì thứ khác, mọi manifest sẽ quy nhầm cho `kisni`"],
    ["`wlan0`", "DOWN, radio soft-blocked", "Sóng WiFi lớn hơn tín hiệu CPU nhiều bậc, làm ngập probe"],
    ["`lsmod \\| grep kisni`", "rỗng", "Module còn sót từ phiên trước làm sai byte delta"],
    ["`/sys/kernel/debug/kisni`", "không tồn tại", "Cùng lý do"],
    ["`/dev/uinput`", "tồn tại", "Không có nó thì `keysynth` không gõ được"],
], widths=[5.0, 4.0, 8.0])

h2("4.3 Containment")
p("`kisni` **không làm gì trên mạng**. Vì vậy policy `OUTPUT DROP` mặc định của `isolation-on.sh` là "
  "đủ, và runner chấp nhận verdict `full` mà không cần mở port nào.")
callout("warn", "Đừng mở ngoại lệ C2 cho family này",
        "Khác Bashlite, ở đây không có C2 để giả lập. Mở thêm port chỉ tạo thêm một thứ phải giải "
        "thích trong luận văn, và không có lợi ích đo lường nào.")

h2("4.4 Taint — hiểu đúng để không bỏ sót")
p("Nạp một module ngoài cây nguồn **luôn** làm nhân bị taint. Đó là dự kiến, và manifest ghi lại. "
  "Nhưng nếu nhân **đã** taint trước lần nạp đầu tiên, nguyên nhân là thứ khác và mọi trace sẽ "
  "quy nhầm nó cho `kisni`.")
code("""cat /proc/sys/kernel/tainted      # 0 = sạch
sudo dmesg | grep -i taint""")
p("Bitmask này **cộng dồn** và chỉ xoá bằng reboot. Nên nếu khác 0, khởi động lại Pi trước khi đo — "
  "trừ khi bạn chấp nhận ghi rõ taint có sẵn trong từng manifest bằng `--allow-taint`.")

h2("4.5 Khi có sự cố khẩn cấp")
code("""# 1. Gỡ module ngay (nếu máy còn sống)
sudo rmmod kisni; lsmod | grep kisni || echo "unloaded"
# 2. Giết injector nếu còn chạy
sudo pkill -f keysynth
# 3. Nếu máy treo: tắt nguồn, đọc log, rồi flash lại image ở 3.4
# 4. Không xoá bằng chứng: giữ dmesg, manifest, image""")
p("Nếu đã panic: **không** cố sửa trên máy đang treo. Flash lại image, ghi lại nguyên nhân (dmesg cuối, "
  "số lần nạp/gỡ đã chạy), rồi mới làm lại từ đầu.")

page_break()

# ============================================================================
# CHUONG 5
# ============================================================================
h1("Chương 5 — Chạy: từng bước thực hành")

p("Thứ tự dưới đây là bắt buộc. Mỗi bước là điều kiện vào của bước sau — bỏ qua bước 5.1 rồi "
  "build module là làm ngược.", style=None)

h2("5.1 Preflight — cổng kiểm tra toàn bộ điều kiện")
p("Chạy trên Pi, **trước khi** làm bất cứ thứ gì với module. Công cụ chỉ đọc, không ghi gì.")
code("""python3 -I /home/emlab/work/tools/keysni_preflight.py""")
p("Kết quả có ba mức: `ok`, `warn`, `fail`. **Mọi `fail` phải sửa xong trước khi đi tiếp.** "
  "`warn` phải đọc, không được bỏ qua.")
callout("info", "Kiểm tra image ở đâu",
        "File image được tạo trên **laptop** (bước 3.4), không nằm trên Pi. Nếu chạy preflight trên "
        "Pi mà không truyền `--image`, công cụ trả `warn` và nhắc bạn xác nhận thủ công — đó là "
        "hành vi đúng, không phải lỗi. Chỉ truyền `--image PATH` khi file thật sự có trên máy đang "
        "chạy lệnh; một đường dẫn không tồn tại sẽ là `fail` và chặn bạn vô cớ.")
p("Công cụ kiểm tra, theo từng phase của kế hoạch:")
table(["Phase", "Kiểm tra gì"], [
    ["P1", "Image khôi phục có tồn tại và có file `.sha256`; throttle; không có chỉnh xung nhịp; đường khôi phục"],
    ["P3", "Headers của đúng kernel; `Module.symvers`; quyết định `CONFIG_MODULE_SIG*`; toolchain build"],
    ["P5", "`debugfs` đã mount và không có entry `kisni` cũ; `uinput`; nhân chưa bị taint"],
], widths=[3.0, 14.0])

h2("5.2 Lấy và ghim source")
p("Trên **máy phân tích cô lập**, không phải Windows, không phải Pi:")
code("""git clone https://github.com/jarun/spy.git
cd spy
git rev-parse HEAD > /tmp/src-rev.txt
sha256sum spy.c Makefile > /tmp/src.sha256
git log --oneline -1""")
callout("warn", "Ghim revision, đừng theo nhánh",
        "Nếu source thay đổi giữa hai lô trace, artifact thay đổi và dataset không còn đồng nhất. "
        "Revision đã ghim phải nằm trong `KEYSNIFFER_PROVENANCE.md` và trong mọi manifest.")

h2("5.3 Build cho đúng kernel đang chạy")
code("""cd spy
make -C /lib/modules/$(uname -r)/build M=$PWD modules
file kisni.ko
modinfo kisni.ko""")
p("Kết quả phải là `ELF 64-bit LSB relocatable, ARM aarch64` và `vermagic:` trùng **chính xác** "
  "chuỗi `uname -r`.")
p("Cảnh báo của compiler chấp nhận được. **Lỗi thì không được vá lặng lẽ.** Nếu source 4.19 không "
  "còn biên dịch, chỉ được sửa API cơ học (thay helper đã bị bỏ, sửa chữ ký hàm), mỗi sửa đổi ghi "
  "vào `PATCHES.md` kèm diff trước/sau.")

h2("5.4 Băm và đóng băng artifact")
code("""sha256sum kisni.ko > kisni.ko.sha256
cp kisni.ko /home/emlab/work/modules/kisni-$(uname -r)-$(sha256sum kisni.ko | cut -c1-12).ko
ls -l /home/emlab/work/modules/""")
p("Từ giờ **chỉ** dùng file trong `modules/`. Hash này là thứ runner đối chiếu ở mỗi trace; đổi file "
  "giữa campaign là làm hỏng dataset.")

h2("5.5 Đọc source trước khi nạp")
p("Nạp module nhân là hành động đặc quyền cao nhất trong dự án. Đọc source trước khi nó chạy.")
code("""grep -n "module_param\\|debugfs_create\\|register_keyboard_notifier\\|module_init\\|module_exit" spy.c""")
table(["#", "Phải kiểm tra"], [
    ["1", "`module_init` an toàn khi lỗi: gỡ thư mục debugfs và trả mã lỗi, không để notifier đã đăng ký dở"],
    ["2", "`module_exit` gỡ notifier **trước** khi xoá thư mục"],
    ["3", "Callback không deref thứ có thể NULL (nó chạy trong ngữ cảnh ngắt — lỗi ở đây panic cả máy)"],
    ["4", "Ghi buffer không vượt `BUF_LEN` (upstream có kiểm tra và quay vòng; xác nhận trong bản đã ghim)"],
    ["5", "Không networking, không ghi file ngoài debugfs, không tương tác tiến trình"],
    ["6", "Có `MODULE_LICENSE(\"GPL v2\")` — bắt buộc cho `EXPORT_SYMBOL_GPL`"],
], widths=[1.2, 15.8])
p("Ghi kết quả vào `Keysniffer/analysis_notes/KEYSNIFFER_STATIC_REVIEW.md`. File đó **cũng là hồ sơ** "
  "rằng lab đã cố ý nạp một keylogger.")

h2("5.6 Diễn tập nạp/gỡ 50 lần")
p("Làm trên trạng thái image dùng một lần, không có gì quý trên thẻ.")
code("""for i in $(seq 1 50); do
  sudo insmod /home/emlab/work/modules/kisni-<ver>-<hash>.ko codes=1 || { echo "FAIL load $i"; break; }
  sudo rmmod kisni || { echo "FAIL unload $i"; break; }
  echo "cycle $i ok"
done
lsmod | grep kisni || echo "clean"
sudo dmesg | tail -20""")
callout("info", "Vì sao 50 lần chứ không phải 1",
        "Module rò một notifier hoặc một dentry mỗi lần nạp sẽ panic ở lần thứ 60, không phải lần "
        "đầu. Một lần nạp/gỡ sạch không chứng minh được gì.")
p("Bảng xử lý lỗi:")
table(["Triệu chứng", "Ý nghĩa", "Hành động"], [
    ["`insmod: Invalid module format`", "Lệch vermagic", "Build lại cho đúng kernel; **không** ép"],
    ["`insmod: Unknown symbol module_layout`", "Lệch `Module.symvers` / modversions", "Cài headers đúng, build lại"],
    ["`Operation not permitted`", "Signature enforcement", "Xem bảng 3.8; **không** tắt enforcement"],
    ["dmesg có Oops khi nạp", "Đường `module_init` hỏng", "Lưu trace, sửa source, review lại"],
    ["Máy treo", "Panic", "Tắt nguồn, đọc log/serial, ghi lại, flash lại image"],
], widths=[5.5, 5.0, 6.5], font_size=8.5)
callout("warn", "Sau 50 chu trình, reboot trước trace thật đầu tiên",
        "Mỗi lần nạp module đều làm nhân bị taint, và cờ này chỉ xoá được bằng reboot. "
        "Trace đầu tiên **không** dùng `--allow-taint`, nên nếu bạn đi thẳng từ diễn tập "
        "sang trace thật, runner sẽ từ chối vì `kernel already tainted`. Đó là hành vi "
        "đúng: reboot, xác nhận `/proc/sys/kernel/tainted` = `0`, rồi mới đo.")

h2("5.7 Build keysynth và kiểm chứng ba trường hợp")
p("Trên Pi, sau khi đã cài `build-essential`:")
code("""cd /home/emlab/work/tools
gcc -O2 -Wall -Wextra -o keysynth keysynth.c
sudo modprobe uinput
sudo chvt 1
printf 'the quick brown fox jumps over the lazy dog 0123456789' > /home/emlab/work/keys/keys.txt
sha256sum /home/emlab/work/keys/keys.txt""")
p("Đây là **cổng quan trọng nhất của cả chương**. Phải chứng minh đủ ba trường hợp:")
table(["Trường hợp", "Lệnh", "Kỳ vọng"], [
    ["Module nạp + keysynth gõ", "`insmod` rồi `./keysynth --keyfile keys.txt`", "Byte count của `/sys/kernel/debug/kisni/keys` **tăng đúng** số phím"],
    ["Không có module", "`rmmod` rồi `./keysynth`", "File debugfs **không tồn tại** — không có gì tăng"],
    ["Chỉ SSH, không keysynth", "Gõ trong phiên SSH khi module đã nạp", "Byte count **không đổi** — chứng minh SSH không tới notifier"],
], widths=[4.5, 6.5, 6.0], font_size=8.5)
callout("warn", "Phải truyền --keyfile, đừng dựa vào chuỗi built-in",
        "Runner chỉ ghi `keystroke_file_sha256` khi keyfile tồn tại. Nếu cả hai cell typing "
        "đều không có keyfile, analyzer thấy `None` và báo *typing cells used different "
        "keyfiles* — dù thực tế cả hai dùng cùng chuỗi built-in. Dùng một file `keys.txt`, "
        "băm nó, và dùng đúng file đó cho mọi trace typing.")
code("""# đo byte count trước/sau mỗi trường hợp
sudo cat /sys/kernel/debug/kisni/keys | wc -c""")
callout("warn", "Không dùng stat -c %s (hay ls -l) để đếm byte",
        "debugfs tạo inode với i_size = 0 và handler đọc của module "
        "(simple_read_from_buffer) không cập nhật nó, nên trên kernel "
        "6.18.50+rpt-rpi-2712 stat báo 0 cả trước lẫn sau dù buffer đã có nội dung. "
        "Chỉ độ dài dữ liệu read trả về mới đúng; runner đo theo cách này.")
callout("danger", "Trường hợp thứ ba mà không đổi thì dừng lại",
        "Nếu gõ SSH mà byte count *có* tăng, mô hình của tài liệu này sai và phải xem lại trước khi "
        "chụp bất cứ trace nào. Nếu trường hợp một **không** tăng, `keysynth` hoặc VT chưa đúng — "
        "kiểm tra `chvt 1` và quyền `/dev/uinput`.")

h2("5.8 Dry run runner")
p("Chạy được trên bất kỳ host nào, không root, không module. Mục đích: kiểm tra CLI và shape manifest.")
code("""python3 -I /home/emlab/work/tools/kisni_runner.py \\
    --mode kisni-typing --count 2 --duration 0.1 \\
    --run-dir /tmp/kisni_dry""")
p("Manifest sinh ra có `dry_run: true` trong từng dòng. Analyzer sẽ **từ chối** dataset kiểu này — "
  "đúng như mong đợi, xem 5.10.")

h2("5.9 Trace thật đầu tiên")
p("Chỉ sau khi 5.1–5.7 đều đạt. `isolation-on.sh` nằm trong `Bashlite/` và đã được chép sang "
  "`tools/` ở 3.9. Bật isolation trước, với `--no-redirect`: `kisni` không mở kết nối "
  "nào, nên không cần DNAT các cổng botnet và không cần ngoại lệ C2.")
code("""sudo bash /home/emlab/work/tools/isolation-on.sh \\
     --admin 192.168.7.1 --owner-user emlab-run --no-redirect
sudo iptables -S OUTPUT | head          # phải thấy -P OUTPUT DROP""")
p("Script vẫn mở OUTPUT tới `C2_HOST` (mặc định `192.168.7.1`); `kisni` không dùng đường "
  "này. Nếu muốn siết hơn, đặt `--c2` vào một địa chỉ không tồn tại trên bench (ví dụ "
  "`192.0.2.1`); SSH vẫn hoạt động nhờ rule `ESTABLISHED,RELATED`.")
callout("warn", "Arm scope TRƯỚC khi chạy runner",
        "Runner nạp module, settle 1,0 s, rồi mới kéo GPIO 17 lên mức cao. Nếu scope chưa "
        "arm, edge sẽ bị bỏ lỡ. Cấu hình 2 MHz, cửa sổ 2,5 s, trigger rising edge trên "
        "EXT/AUX (hoặc channel B), arm single-shot, rồi mới chạy lệnh dưới. Phím đầu tiên "
        "đến khoảng 200 ms sau edge vì `keysynth` phải tạo thiết bị `uinput` — cắt cửa sổ "
        "đầu này khi phân tích.")
p("Rồi chạy **một** trace, không phải mười. Trace đầu tiên **không** truyền `--allow-taint`: nếu nhân "
  "đã taint sẵn vì thứ khác, runner phải từ chối, và bạn cần biết điều đó trước trace đầu chứ không "
  "phải sau 3000 trace.")
code("""sudo python3 -I /home/emlab/work/tools/kisni_runner.py \\
    --module /home/emlab/work/modules/kisni-<ver>-<hash>.ko \\
    --expected-hash <sha256 đầy đủ> --execute \\
    --mode kisni-typing --keysynth /home/emlab/work/tools/keysynth \\
    --keyfile /home/emlab/work/keys/keys.txt --rate 20 \\
    --count 1 --duration 2.5 \\
    --run-dir /home/emlab/work/manifests/smoke01""")
callout("warn", "Từ trace thứ hai trở đi phải có --allow-taint",
        "Việc nạp module làm nhân bị taint, và cờ này **chỉ xoá được bằng reboot**. Trace đầu chạy "
        "trên nhân sạch nên qua cổng baseline; trace thứ hai trở đi sẽ bị từ chối nếu không có "
        "`--allow-taint`. Đó không phải lỗi — nó ngăn mọi manifest quy nhầm một taint có sẵn cho "
        "`kisni`. Khi campaign chạy dài, chỉ reboot một lần ở đầu phiên, rồi thêm `--allow-taint` "
        "cho phần còn lại; giá trị mask thật được ghi trong từng dòng manifest.")
p("Kiểm tra kết quả trong manifest:")
table(["Trường", "Phải là", "Nghĩa"], [
    ["`status`", "`ok`", "Chu trình hoàn tất"],
    ["`debugfs_delta`", "**> 0**", "Module thật sự đã ghi thứ gì đó — đây là bằng chứng chính"],
    ["`keystroke_count`", "khoảng 50 (20 phím/s × 2,5 s)", "Injector thực sự đã gõ"],
    ["`lsmod_after`", "`false`", "Module đã được gỡ sạch"],
    ["`keysynth_leftover`", "`false`", "Không còn tiến trình injector"],
    ["`module_sha256`", "khớp hash đã ghim", "Đúng artifact"],
    ["`dmesg_taint`", "có `G OE`", "Bình thường với module ngoài cây nguồn"],
], widths=[3.5, 4.5, 9.0])
callout("danger", "debugfs_delta = 0 nghĩa là dừng lại",
        "Module nạp được nhưng không ghi gì: hoặc `keysynth` không tới được VT, hoặc module không "
        "nhận sự kiện. Trace khi đó gần giống nhân sạch và **không sửa được sau này**.")

h2("5.10 Kiểm tra dataset trước khi train")
code("""python3 -I /home/emlab/work/tools/keysni_analyze.py \\
    /home/emlab/work/manifests/smoke01/manifest.jsonl""")
p("Analyzer trả về khác 0 khi: ablation chưa đủ, hai cell typing khác keyfile hoặc khác rate, "
  "module buffer bị tái sử dụng, trace thất bại, hoặc module không ghi gì. Dataset chỉ có dry run "
  "cũng bị từ chối **rõ ràng** — đây là lỗi mà kiểm tra shape không bắt được. Từ bản sửa này, "
  "analyzer còn từ chối khi các manifest **không mô tả cùng một thí nghiệm** — khác "
  "`expected_hash`, `kernel_release`, `codes=`, `trigger`/`gpio_pin`, `rate`, `duration_s`, "
  "`injector`, `schema`/`runner_version`, hoặc `module_sha256` lệch giữa các trace.")
callout("info", "Smoke dataset một cell sẽ trả non-zero — đó là đúng",
        "`keysni_analyze.py` coi đủ bốn cell `{kisni-typing, typing-only, kisni-idle, idle}` "
        "là điều kiện của một dataset hoàn chỉnh. Vì vậy trace đầu tiên (chỉ một cell) sẽ bị "
        "báo `2x2 ablation incomplete` và exit khác 0. Điều cần kiểm tra ở bước này là "
        "**không có problem nào khác**: `status` sạch, `debugfs_delta > 0`, không có "
        "`no-activity`. Đừng bỏ qua cảnh báo ablation khi chụp dataset cuối.")

page_break()

# ============================================================================
# CHUONG 6
# ============================================================================
h1("Chương 6 — Bộ đối chứng 2×2 — vì sao phải có hai cell")

h2("6.1 Vấn đề nếu chỉ chụp một cell")
p("Cell `kisni-typing` là \"module đã nạp + có gõ phím\". Nếu đó là cell duy nhất của lớp malware, thì:")
table(["Trong dataset", "Malware", "Benign"], [
    ["Module", "có", "**không**"],
    ["Bàn phím", "**có gõ**", "không gõ (idle)"],
], widths=[7.0, 5.0, 5.0])
p("Classifier chỉ cần phát hiện *có tiếng gõ* là tách được hai lớp — chính xác cao và **vô nghĩa**. "
  "Nó học bàn phím, không học rootkit. Đây không phải rủi ro lý thuyết: trace EM của `uinput` có năng "
  "lượng rõ ràng, dễ tách hơn nhiều so với footprint của một module nằm im.")

h2("6.2 Bộ đối chứng đầy đủ")
table(["Cell", "Module", "Gõ phím", "Vai trò"], [
    ["`kisni-typing`", "có", "có", "**Lớp malware**"],
    ["`typing-only`", "không", "có", "Benign đối chứng **cùng workload**"],
    ["`kisni-idle`", "có", "không", "Footprint nền của module"],
    ["`idle`", "không", "không", "Tham chiếu idle sẵn có"],
], widths=[4.0, 2.5, 2.5, 8.0])
p("Campaign **tối thiểu** là hai cell đầu. Hai cell sau rẻ hơn và làm kết luận đứng vững hơn: "
  "`kisni-idle` cho biết module có tiêu thụ điện ngay cả khi không ai gõ, tức footprint là thuộc tính "
  "**thường trú** chứ không chỉ xuất hiện lúc xử lý phím.")
callout("warn", "Analyzer đòi đủ **bốn** cell, không phải hai",
        "`keysni_analyze.py` coi bộ `{kisni-typing, typing-only, kisni-idle, idle}` là bắt buộc và "
        "báo `2x2 ablation incomplete` nếu thiếu bất kỳ cell nào. Nghĩa là một dataset chỉ có hai "
        "cell typing **vẫn bị coi là chưa đủ** dù đó là mức tối thiểu theo kế hoạch. Đây không phải "
        "lỗi của công cụ: nếu bạn chỉ chụp hai cell, kết quả phải được ghi rõ là chưa hoàn chỉnh. "
        "Cách sạch nhất là chụp đủ bốn — `kisni-idle` và `idle` chỉ thêm khoảng 1,8 giờ và 80 GB.")
p("`typing-only` phải nằm trong **lớp benign** của dataset, không phải một thí nghiệm riêng, để "
  "classifier buộc phải tách module khỏi workload chứ không tách khỏi việc không có input.")

h2("6.3 Hai cell typing phải so sánh được")
p("`keysni_analyze.py` kiểm tra ba điều kiện. Vi phạm bất kỳ điều nào thì ablation mất hiệu lực:")
table(["Điều kiện", "Vì sao"], [
    ["**Cùng keyfile** (hash trùng)", "Khác chuỗi gõ thì classifier tách bằng nội dung phím, không bằng module"],
    ["**Cùng key rate**", "Khác nhịp gõ thì spectrogram khác nhau vì nhịp, không vì rootkit"],
    ["**Cùng kiểu injector** (`uinput` **hoặc** USB HID)", "USB HID thêm workload USB host-controller mà `uinput` không có — không được trộn trong một dataset"],
], widths=[6.0, 11.0])

h2("6.4 Volume và thời gian")
table(["Cell", "Trace", "Thời gian (~3,2 s/trace)", "Đĩa (float64 .npy)"], [
    ["`kisni-typing`", "3 000", "~2,7 h", "~120 GB"],
    ["`typing-only`", "3 000", "~2,7 h", "~120 GB"],
    ["`kisni-idle`", "1 000 (tuỳ chọn)", "~0,9 h", "~40 GB"],
    ["`idle`", "1 000 (tuỳ chọn)", "~0,9 h", "~40 GB"],
], widths=[4.5, 3.5, 5.0, 4.0])
callout("danger", "Kiểm tra dung lượng đĩa TRƯỚC trace đầu tiên",
        "Đủ bốn cell theo bảng trên là **8 000 trace ≈ 320 GB** (float64, ~40 MB/trace), "
        "cộng 10% headroom là khoảng **352 GB**. Riêng hai cell typing bắt buộc đã cần khoảng "
        "**240 GB**. Chạy `python3 -I capacity_plan.py --out <đích> --traces 2000 --cells 4` "
        "trước khi bắt đầu — công cụ nhân đều `traces × cells`, nên `2000 × 4` mô phỏng đúng "
        "8 000 trace chia không đều như bảng. Một đĩa đầy giữa campaign không báo lỗi — nó chỉ "
        "ghi thiếu.")
p("Nếu chỗ chứa buộc phải giảm: ghi `int16` thay vì `float64` giảm 4 lần — 8 000 trace còn "
  "khoảng **80 GB** (88 GB với headroom), thay vì 328 GB. Nhưng phải sửa **cả** "
  "`pico-em-capture/capture.py` **và** `em_analysis.py`, và phải làm "
  "**trước** trace đầu tiên — đổi định dạng giữa dataset là làm dữ liệu không còn so sánh được.")

h2("6.5 Thứ tự chụp — xen kẽ, không tuần tự")
p("Chụp `typing-only` và `kisni-typing` theo **block xen kẽ**, không chụp hết cell này rồi mới sang "
  "cell kia. Lý do: nhiệt độ và điều kiện môi trường trôi theo thời gian; chụp tuần tự thì drift "
  "thành \"khác biệt lớp\", còn xen kẽ thì drift ảnh hưởng đều cả hai.")
p("Tổng thời gian ghi vẫn khoảng 5,4 giờ, nhưng phải chia block và giữ nguyên vị trí Pi/probe suốt cả hai.")

h2("6.6 So sánh với Bashlite — cái gì giống, cái gì khác")
table(["Tiêu chí", "Bashlite", "Keysniffer"], [
    ["Trigger", "GPIO 17, mức cao", "**Giống hệt**"],
    ["Settle trước lần đo", "1,0 s", "**Giống hệt**"],
    ["Độ dài cửa sổ", "`--duration` (2,5 s)", "**Giống hệt**"],
    ["Shape manifest", "JSONL, header/trace/footer", "**Giống hệt** (thêm trường riêng của module)"],
    ["Cái được giám sát", "Tiến trình (có PID)", "**Module nhân — không có PID**"],
    ["Dọn dẹp giữa các trace", "Giết cây tiến trình + sweep `/proc`", "`rmmod` + xác nhận `lsmod` sạch"],
    ["Nguồn hoạt động", "C2 giả gửi lệnh", "`keysynth` gõ phím"],
    ["Rủi ro chính", "Mẫu thoát khỏi containment", "**Panic cả máy**"],
], widths=[4.0, 6.0, 7.0])

page_break()

# ============================================================================
# CHUONG 7
# ============================================================================
h1("Chương 7 — Xử lý sự cố")
table(["Triệu chứng", "Nguyên nhân thường gặp", "Cách sửa"], [
    ["`insmod: Invalid module format`", "Vermagic khác kernel đang chạy", "`modinfo -F vermagic` so với `uname -r`; build lại. Không dùng `--force`"],
    ["`Unknown symbol module_layout`", "Build không dùng `Module.symvers` của Pi", "Cài `linux-headers-$(uname -r)`, build lại"],
    ["`Operation not permitted` khi `insmod`", "`CONFIG_MODULE_SIG_FORCE=y`", "Ký bằng MOK cục bộ nếu có; nếu không, **báo blocker và dừng**"],
    ["`/sys/kernel/debug/kisni` không có", "debugfs chưa mount, hoặc `CONFIG_DEBUG_FS` tắt", "`mount -t debugfs none /sys/kernel/debug`; xem bảng 3.8"],
    ["`debugfs_delta = 0`", "Keysynth không tới VT, hoặc không ai gõ", "`sudo chvt 1`; chạy lại cổng 5.7; kiểm tra `/dev/uinput`"],
    ["`keysynth` rc=3", "Không mở được `/dev/uinput`", "`sudo modprobe uinput`; kiểm tra quyền"],
    ["`keysynth` rc=4", "Keyfile rỗng hoặc không đọc được", "Kiểm tra `--keyfile`, phải có ký tự ASCII in được"],
    ["`keysynth` rc=5", "Ghi thiết bị thất bại", "Kiểm tra thiết bị uinput bị gỡ giữa chừng"],
    ["`--allow-taint` bị đòi", "Nhân đã taint trước khi nạp", "**Reboot Pi** rồi đo lại; hoặc chấp nhận và ghi rõ trong manifest"],
    ["Runner từ chối containment", "Không có policy `OUTPUT DROP`", "Chạy `isolation-on.sh` trước"],
    ["Analyzer báo ablation thiếu cell", "Chưa chụp đủ `typing-only`", "Đúng như thiết kế — chụp thêm cell đó"],
    ["Analyzer từ chối dataset dry run", "Chỉ có trace `dry_run: true`", "Đúng như thiết kế — chạy trace thật"],
    ["Pi treo khi `rmmod`", "Rò notifier hoặc dentry", "Flash lại image ở 3.4; đọc dmesg; ghi lại số chu trình đã chạy"],
    ["`ssh` báo host key thay đổi", "Đã re-image", "`ssh-keygen -R 192.168.7.2`"],
], widths=[4.6, 5.4, 7.0], font_size=8.5)

page_break()

# ============================================================================
# PHU LUC A
# ============================================================================
h1("Phụ lục A — Toàn bộ lệnh theo thứ tự")
p("Dùng khi đã hiểu và chỉ cần chạy lại. Thay `<ver>` bằng `uname -r`, `<hash>` bằng hash thật.")
h3("Trên Pi — khi còn internet")
code("""sudo apt update
sudo apt install -y build-essential linux-headers-$(uname -r) \\
                    python3 python3-venv file binutils iptables iproute2 \\
                    git python3-gpiozero python3-lgpio
sudo modprobe uinput
sudo chvt 1

# Chỉ clone trên Pi nếu KHÔNG có máy phân tích cô lập; ghi lại deviation.
git clone https://github.com/jarun/spy.git /home/emlab/work/spy
cd /home/emlab/work/spy && git rev-parse HEAD
sha256sum spy.c Makefile""")
h3("Trên laptop — image và chép công cụ")
code("""lsblk -o NAME,SIZE,MODEL,MOUNTPOINT
sudo dd if=/dev/sdX of=pi5-prekeysniffer-$(date +%F).img bs=4M status=progress conv=fsync
sha256sum pi5-prekeysniffer-$(date +%F).img > pi5-prekeysniffer-$(date +%F).img.sha256

scp Keysniffer/kisni_runner.py Keysniffer/keysni_preflight.py \\
    Keysniffer/keysni_analyze.py Keysniffer/tools/keysynth.c \\
    Bashlite/isolation-on.sh isolation-off.sh preflight.sh capacity_plan.py \\
    emlab@192.168.7.2:/home/emlab/work/tools/""")
h3("Trên Pi — preflight, build, ghim")
code("""python3 -I /home/emlab/work/tools/keysni_preflight.py

cd /home/emlab/work/spy
make -C /lib/modules/$(uname -r)/build M=$PWD modules
file kisni.ko && modinfo kisni.ko
sha256sum kisni.ko
cp kisni.ko /home/emlab/work/modules/kisni-$(uname -r)-$(sha256sum kisni.ko | cut -c1-12).ko""")
h3("Trên Pi — diễn tập và build injector")
code("""for i in $(seq 1 50); do
  sudo insmod /home/emlab/work/modules/kisni-<ver>-<hash>.ko codes=1 || break
  sudo rmmod kisni || break
done

cd /home/emlab/work/tools
gcc -O2 -Wall -Wextra -o keysynth keysynth.c
printf 'the quick brown fox jumps over the lazy dog 0123456789' > /home/emlab/work/keys/keys.txt""")
h3("Trên Pi — trace đầu tiên")
code("""sudo bash /home/emlab/work/tools/isolation-on.sh \\
     --admin 192.168.7.1 --owner-user emlab-run --no-redirect

sudo python3 -I /home/emlab/work/tools/kisni_runner.py \\
    --module /home/emlab/work/modules/kisni-<ver>-<hash>.ko \\
    --expected-hash <sha256> --execute --mode kisni-typing \\
    --keysynth /home/emlab/work/tools/keysynth \\
    --keyfile /home/emlab/work/keys/keys.txt --rate 20 \\
    --count 1 --duration 2.5 \\
    --run-dir /home/emlab/work/manifests/smoke01

python3 -I /home/emlab/work/tools/keysni_analyze.py \\
    /home/emlab/work/manifests/smoke01/manifest.jsonl""")
h3("Dọn dẹp")
code("""sudo rmmod kisni; lsmod | grep kisni || echo "clean"
sudo pkill -f keysynth
sudo bash /home/emlab/work/tools/isolation-off.sh""")

# ============================================================================
# PHU LUC B
# ============================================================================
h1("Phụ lục B — Bản đồ file trên Pi")
code("""/home/emlab/work/
├── tools/            script + keysynth (KHÔNG để lẫn với .ko)
│   ├── kisni_runner.py
│   ├── keysni_preflight.py
│   ├── keysni_analyze.py
│   ├── keysynth.c
│   ├── keysynth
│   ├── isolation-on.sh
│   ├── isolation-off.sh
│   ├── capacity_plan.py
│   └── preflight.sh
├── spy/              source đã ghim (git clone, giữ .git để biết revision)
├── modules/          kisni-<ver>-<hash>.ko + .sha256
├── keys/             keys.txt (chuỗi gõ cố định)
└── manifests/        JSONL kết quả từng phiên""")
callout("info", "Vì sao tách thư mục",
        "Python nạp module từ thư mục hiện tại. Nếu để script chung với file lạ, một file độc hại "
        "tên `json.py` có thể được nạp thay cho thư viện thật. Cùng lý do như bản Bashlite.")

# ============================================================================
# PHU LUC C
# ============================================================================
h1("Phụ lục C — Checklist trước khi đo")
for item in [
    "Image thẻ nhớ đã chụp **và** có file `.sha256`",
    "Đường khôi phục sau panic đã xác định cụ thể (HDMI/UART/flash lại)",
    "`vcgencmd get_throttled` = `0x0`",
    "`/proc/sys/kernel/tainted` = `0`",
    "Không có `arm_freq` / `force_turbo` trong `/boot/firmware/config.txt`",
    "`ip route` trên Pi chỉ có `192.168.7.0/24`",
    "`rfkill block wifi` đã chạy, `wlan0` DOWN",
    "Isolation đã bật; `curl` / `nc` ra internet đều thất bại",
    "`keysni_preflight.py` không còn dòng `fail` nào",
    "Source đã ghim revision và hash",
    "`vermagic` của `.ko` trùng đúng `uname -r`",
    "Static review đã điền đủ 6 mục (5.5)",
    "50 chu trình nạp/gỡ sạch, `lsmod` không còn `kisni`, **đã reboot**",
    "`keysynth` biên dịch được, `/dev/uinput` mở được, `chvt 1` đã chạy",
    "Cổng 5.7 đã chứng minh đủ ba trường hợp (có module / không module / chỉ SSH)",
    "`debugfs_delta > 0` trên trace thật đầu tiên",
    "Analyzer đã chạy; biết rằng dataset một cell trả non-zero vì ablation incomplete",
    "Scope đã arm trước runner; trace bắt đầu đúng trigger edge",
    "Dung lượng đĩa đã kiểm tra bằng `capacity_plan.py`",
    "Vị trí Pi, probe, amplifier đã chụp ảnh/ghi lại và sẽ không đổi trong dataset",
]:
    p("☐  " + item)

# ============================================================================
# PHU LUC D
# ============================================================================
h1("Phụ lục D — Những gì phải ghi vào luận văn")
bullet("Revision nguồn đã ghim (`git rev-parse HEAD`) và `sha256sum spy.c Makefile`.")
bullet("Hash của `kisni.ko` đã build, và **vermagic** của nó.")
bullet("Việc đây là **same-source re-instantiation trên kernel 6.18**, không phải sao chép trace của paper.")
bullet("Suy luận danh tính nguồn là `jarun/spy` — ghi rõ là *inferred*, trừ khi đã đối chiếu được `.ko` gốc.")
bullet("`PATCHES.md` nếu có sửa API, kèm diff, và xác nhận **không sửa gì trong `spy_cb()`**.")
bullet("Cấu hình Pi: `uname -a`, `/etc/os-release`, `dpkg -l`, danh sách service đang chạy.")
bullet("`vcgencmd get_throttled` trước và sau mỗi phiên.")
bullet("`/proc/sys/kernel/tainted` trước khi nạp, và mask taint sau khi nạp.")
bullet("Keyfile đã dùng (hash), rate, số phím mỗi cửa sổ.")
bullet("Chọn injector (`uinput` hay USB HID) và lý do; xác nhận không trộn trong một dataset.")
bullet("2×2 ablation: cell nào đã chụp, cell nào không, và vì sao.")
bullet("Kết quả `keysni_analyze.py` trên dataset cuối.")
bullet("Dung lượng thực tế đã dùng và số trace mỗi cell.")
bullet("Hạn chế đã biết: một họ rootkit thay vì hai (paper); 6404E thay vì 6407; `uinput` thay vì gõ thật.")

doc.add_paragraph()
callout("warn", "Ghi chú về ngôn ngữ",
        "File này viết bằng tiếng Việt để dễ đọc trong lúc thực hành. Quy ước của repo "
        "(`.cursor/rules/em-lab-invariants.mdc`) yêu cầu **mọi output của dự án bằng tiếng Anh**, "
        "nên khi dán vào luận văn hãy dịch lại. Các file kỹ thuật trong `Keysniffer/` "
        "(`KEYSNIFFER_PLAN.md`, `README.md`) vẫn bằng tiếng Anh và là nguồn chuẩn khi có khác biệt.")

# ---- properties + footer ---------------------------------------------------
cp = doc.core_properties
cp.title = "Keysniffer (kisni) trên Raspberry Pi 5 — hướng dẫn vận hành"
cp.subject = "EM side-channel lab — module nhân, build lại từ nguồn GPL-2.0"
cp.author = "EM lab operator"
cp.language = "vi-VN"

footer()
doc.save(OUT)
print("WROTE", OUT)
