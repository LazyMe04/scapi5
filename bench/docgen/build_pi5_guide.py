#!/usr/bin/env python3
"""Generate the Vietnamese operator guide for the Pi 5 Bashlite run.

Build:  uv run --no-project --with python-docx python -I bench/docgen/build_pi5_guide.py
Output: PI5_Bashlite_HuongDan.docx in the repo root.
"""
import re
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

OUT = r"C:\Users\Minh_Trinh\Downloads\bench\PI5_Bashlite_HuongDan.docx"

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
    run = par.add_run("Pi 5 + Bashlite (Gafgyt) — Hướng dẫn vận hành   |   trang ")
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
r = t.add_run("Chạy Bashlite (Gafgyt) trên Pi 5\nqua SSH từ laptop")
r.font.size = Pt(26); r.bold = True; r.font.color.rgb = RGBColor.from_string("1F3864")

s = doc.add_paragraph(); s.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = s.add_run("Hướng dẫn thực hành cho người mới — từ cấu hình đến lần chạy đầu tiên")
r.font.size = Pt(13); r.italic = True; r.font.color.rgb = RGBColor.from_string("2F5496")

doc.add_paragraph()
kv_block([
    ["Mẫu malware", "SHA-256 `349d2476…b777` — Gafgyt, ELF32 ARM, static, 147 686 byte"],
    ["Họ malware", "Gafgyt / Qbot (dòng Bashlite) — build modular, source `snoopy.c`"],
    ["C2 nhúng trong mẫu", "`181.214.147.11:999` (được chuyển hướng sang lab)"],
    ["Thiết bị đo", "Raspberry Pi 5, Debian 13 aarch64, chạy 32-bit qua CONFIG_COMPAT"],
    ["Máy điều khiển", "Laptop Windows, `192.168.7.1`, chạy C2 server của lab"],
    ["Ngày soạn", "2026-11-05"],
])
doc.add_paragraph()

callout("danger", "Đọc chương 4 trước khi chạy bất cứ thứ gì",
        "Mẫu này là malware thật và **có khả năng tấn công** (35 lệnh flood). Nó chỉ được chạy "
        "khi Pi đã bật isolation và link bench không có default route. Không bao giờ chạy trên "
        "Windows, không bao giờ trỏ vào C2 thật.")

callout("info", "Tài liệu này dành cho ai",
        "Người vận hành chưa quen với malware analysis. Mỗi bước đều có giải thích **vì sao**, "
        "không chỉ **làm gì**. Nếu bạn chỉ muốn chạy nhanh, dùng Phụ lục A (toàn bộ lệnh theo thứ tự) "
        "và quay lại đọc chương 2, 4, 6 để hiểu mình đang làm gì.")

page_break()

# ============================================================================
# TOC
# ============================================================================
h1("Mục lục")
toc = [
    ("Chương 1", "Hiểu nhanh trước khi làm"),
    ("Chương 2", "Con malware này là gì và gồm những phần nào"),
    ("Chương 3", "Cấu hình Raspberry Pi 5"),
    ("Chương 4", "Quy tắc an toàn — đọc kỹ"),
    ("Chương 5", "Chạy: từng bước thực hành"),
    ("Chương 6", "Có phù hợp để đo EM liên tục như goodware_runner?"),
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
  "malware, rồi so sánh với tín hiệu khi chạy phần mềm lành. Máy phân loại sau này sẽ học từ "
  "hai tập tín hiệu đó.")
p("Vì vậy có ba yêu cầu không thể bỏ:")
numbered("Malware phải **thực sự chạy** trên silicon thật — không phải trong QEMU, không phải trên Windows.")
numbered("Nó phải **làm việc thật** trong suốt cửa sổ đo — một tiến trình ngồi chờ thì tín hiệu giống hệt lúc máy rảnh.")
numbered("Mọi thứ nó gửi ra ngoài phải bị **chặn hoặc chuyển hướng** vào lab của ta.")

h2("1.2 Cái gì chạy ở đâu")
table(["Máy", "Vai trò", "Chạy gì"], [
    ["Laptop Windows (192.168.7.1)", "Điều khiển, C2 giả, nơi lưu tài liệu", "`c2_server.py`, SSH client, trình soạn tài liệu"],
    ["Raspberry Pi 5 (192.168.7.2)", "Nạn nhân — nơi malware chạy thật", "`bashlite_runner.py`, `iptables`, sample"],
    ["Oscilloscope (chưa có)", "Đo tín hiệu EM", "—"],
], widths=[5.0, 6.0, 6.0])
p("Điểm quan trọng: **laptop không bao giờ chạy malware**. Nó chỉ nói chuyện với malware qua mạng bench.")

h2("1.3 Từ điển tối thiểu")
table(["Thuật ngữ", "Nghĩa đơn giản"], [
    ["ELF", "Định dạng file thực thi của Linux. Sample này là ELF 32-bit ARM."],
    ["static (liên kết tĩnh)", "Mọi thư viện được nhúng vào một file duy nhất, không cần cài thêm gì để chạy."],
    ["aarch64 / ARM32", "Pi 5 chạy hệ điều hành 64-bit (aarch64); nhân Linux vẫn chạy được chương trình 32-bit ARM nhờ CONFIG_COMPAT."],
    ["C2 (command & control)", "Máy chủ điều khiển botnet. Trong lab, ta giả lập nó."],
    ["DNAT", "Kỹ thuật viết lại địa chỉ đích của gói tin. Dùng để lái malware sang C2 giả mà không sửa file."],
    ["iptables", "Tường lửa của Linux. Dùng để chặn và đếm gói tin."],
    ["tmpfs", "Thư mục nằm trong RAM. Tắt máy là mất, không để lại dấu trên thẻ nhớ."],
    ["fork", "Tiến trình tự nhân bản thành tiến trình con. Malware dùng để chạy nhiều cuộc tấn công song song."],
    ["GPIO trigger", "Một chân của Pi phát xung báo cho oscilloscope bắt đầu ghi."],
], widths=[4.0, 13.0])

page_break()

# ============================================================================
# CHUONG 2
# ============================================================================
h1("Chương 2 — Con malware này là gì và gồm những phần nào")

h2("2.1 Danh tính")
kv_block([
    ["Tên họ", "Gafgyt (còn gọi Qbot, Bashlite, Lizkebash)"],
    ["Thế hệ", "Build modular đời sau (2016+), **không phải** Bashlite 2014"],
    ["Tên file nguồn", "`snoopy.c` (còn trong bảng symbol vì file không bị strip)"],
    ["Kích thước", "147 686 byte"],
    ["Kiến trúc", "ELF 32-bit, ARM, EABI v4, ARMv4T"],
    ["Liên kết", "Static — không cần `ld-linux-armhf.so.3`"],
    ["Đóng gói", "Không. Không UPX, không nén."],
    ["Toolchain", "uClibc + GCC 4.2.1"],
    ["Dấu vết tác giả", "Chuỗi `YakuzaBotnet`, `Scarface1337`"],
])
p("Vì sao điều này quan trọng: **cùng họ nhưng khác thế hệ**. Bashlite 2014 nói chuyện với C2 "
  "theo kiểu IRC (`NICK`, `USER`, `PRIVMSG`) và ra lệnh bằng dấu chấm (`.tcp`, `.udp`). "
  "Mẫu này dùng giao thức dòng lệnh thô: dấu `!`, một dấu cách, tên lệnh, rồi tham số. "
  "Trong file không có một chuỗi `NICK`, `PRIVMSG`, `.tcp`, `.udp` nào (đã đếm: bằng 0).")
callout("warn", "Đừng viết \"Bashlite 2014\" trong luận văn",
        "Hãy viết: *Gafgyt (dòng Bashlite/Qbot), build modular, source `snoopy.c`*. "
        "Người phản biện sẽ đối chiếu chuỗi trong file và thấy ngay sự khác biệt.")

h2("2.2 Các thành phần bên trong")
p("Mỗi dòng dưới đây là một hàm thật trong file, kèm địa chỉ để bạn đối chiếu khi cần.")
table(["Thành phần", "Địa chỉ", "Nhiệm vụ"], [
    ["`main`", "~0x12600", "Vòng lặp vô hạn: kết nối C2 → gửi banner → đọc lệnh → lặp lại khi mất kết nối"],
    ["`initConnection`", "0x123cc", "Đọc chuỗi cấu hình, tách `IP:port`, gọi kết nối"],
    ["`connectTimeout`", "0x95f0", "Kết nối TCP có giới hạn thời gian (30 giây)"],
    ["`sockprintf`", "0x912c", "Gửi một dòng văn bản qua socket (dùng cho banner)"],
    ["`recvLine`", "0x9318", "Đọc từng dòng từ C2, chặn (block) đến khi có dữ liệu"],
    ["`trim`", "0x87fc", "Cắt khoảng trắng ở hai đầu dòng"],
    ["`toupper`", "0x13428", "Viết hoa tên lệnh (nhờ vậy lệnh không phân biệt hoa/thường)"],
    ["`strtok`", "thư viện", "Tách tham số theo dấu cách (chỉ dấu cách, không phải dấu phẩy)"],
    ["`processCmd`", "0xe820", "So sánh tên lệnh với 35 chuỗi, gọi module tương ứng"],
    ["`listFork`", "0x9864", "Tạo tiến trình con cho mỗi cuộc tấn công"],
    ["`SendSTDHEX`", "0x9d44", "Tấn công TCP: gửi liên tục gói 1460 byte"],
    ["`sendCNC`", "0x9fbc", "Tấn công TCP: mở/đóng kết nối liên tục"],
    ["`gethostbyname`", "0x157e4", "Phân giải tên miền (STDHEX dùng)"],
    ["`inet_addr`", "0x157bc", "Đổi chuỗi IP thành số (CNC dùng)"],
], widths=[4.2, 2.4, 10.4])

h2("2.3 Cấu hình C2 nằm ở đâu")
p("Chuỗi `181.214.147.11:999` nằm ở `0x1e310`. Ngay cạnh đó là một bảng 8 con trỏ tại `0x2a568`:")
table(["Vị trí", "Nội dung"], [
    ["`[0]` 0x1e310", "`181.214.147.11:999` ← địa chỉ C2 duy nhất được dùng"],
    ["`[1]`–`[7]`", "Các chuỗi `User-Agent` của trình duyệt, dùng cho module HTTP flood"],
], widths=[4.0, 13.0])
p("Bộ đếm chỉ số nằm ở `0x2a588`, khởi tạo `-1`, và logic cập nhật là *nếu đã bằng 0 thì giữ 0*, "
  "nên nó **kẹt ở 0** và luôn thử lại đúng một địa chỉ. Đây không phải cơ chế xoay vòng C2.")
p("Giao thức C2 dùng cổng **999**. Nếu chuỗi cấu hình không có dấu hai chấm, port mặc định là 6982.")

h2("2.4 Một lần chạy diễn ra như thế nào")
p("Đây là phần quan trọng nhất để hiểu vì sao cần C2 giả. Nếu không có C2, mẫu gần như ngồi im.")
table(["Thời điểm", "Diễn biến"], [
    ["0 ms", "Runner bật GPIO 17 (trigger) và khởi động sample"],
    ["~0–50 ms", "Sample khởi động, `setsid()`, đọc `/proc/net/route` để đoán IP của chính nó, rồi `connect()` tới `181.214.147.11:999`"],
    ["~50 ms", "Gói tin bị DNAT đổi đích thành `192.168.7.1:999` → tới C2 giả"],
    ["~50 ms", "Sample gửi **banner** trước, rồi block ở `recvLine` chờ lệnh"],
    ["60 ms", "C2 giả gửi `! STDHEX 192.168.7.1 9999 3`"],
    ["60–70 ms", "Parser nhận lệnh → `listFork()` tạo tiến trình con → con bắt đầu gửi TCP liên tục; tiến trình cha quay lại chờ lệnh"],
    ["1200 ms", "C2 gửi `! CNC 192.168.7.1 9999 3` → tiến trình con thứ hai mở/đóng kết nối liên tục"],
    ["2200 ms", "C2 gửi `! STOP`"],
    ["2450 ms", "C2 đóng kết nối"],
    ["2500 ms", "Runner kết thúc cửa sổ: giết cả cây tiến trình, rồi quét `/proc` để giết process con đã thoát khỏi nhóm"],
], widths=[3.0, 14.0])
callout("info", "Vì sao phải có C2 giả",
        "Nếu C2 không trả lời, sample chỉ gửi banner rồi **ngồi chờ**. CPU gần 0 %, tín hiệu EM "
        "gần như không có gì để học. C2 giả là thứ biến một tiến trình đang ngủ thành một cỗ máy "
        "đang tấn công.")

h2("2.5 Vì sao lệnh phải có dấu `!` và đúng một dấu cách")
p("Parser của sample làm đúng thứ tự sau, và mỗi bước đều có thể làm hỏng lệnh:")
numbered("Cắt khoảng trắng hai đầu dòng (`trim`).")
numbered("Kiểm tra ký tự đầu tiên có phải `!`. Không phải thì **bỏ qua cả dòng**.")
numbered("Bỏ qua `!`, nhảy tới dấu cách đầu tiên, **đặt ký tự NUL tại đó** — tức là cắt tên lệnh ra.")
numbered("Viết hoa tên lệnh vừa cắt.")
numbered("`strtok` phần còn lại theo dấu cách để lấy tham số.")
p("Hệ quả, đã kiểm chứng bằng cách **chạy chính các lệnh ARM của sample** trên một stack giả:")
table(["Dòng C2 gửi", "Kết quả"], [
    ["`! STDHEX a b c`", "✅ Được thực thi (4 tham số)"],
    ["`! stdhex a b c`", "✅ Được thực thi (tên lệnh không phân biệt hoa/thường)"],
    ["`!STDHEX a b c`", "❌ Bị bỏ qua — mất luôn tên lệnh"],
    ["`!  STDHEX a b c` (hai dấu cách)", "❌ Bị bỏ qua — tham số đầu rỗng"],
    ["`! STDHEX a,b,c`", "❌ Bị bỏ qua — dồn thành một token quá dài"],
    ["`STDHEX a b c` (không có `!`)", "❌ Không bao giờ được parse"],
], widths=[7.0, 10.0])

h2("2.6 Bộ 35 lệnh — malware này làm được gì")
p("`processCmd` so sánh tên lệnh với 35 chuỗi theo thứ tự cố định. Nhóm theo chức năng:")
table(["Nhóm", "Lệnh", "Chức năng"], [
    ["TCP flood", "`STDHEX`, `CNC`, `TCP`, `TCP-H`", "Làm ngập kết nối TCP; `STDHEX` gửi dữ liệu, `CNC` mở/đóng liên tục"],
    ["UDP flood", "`UDPHIT`, `UDPFULL`, `UDPKILL`, `UDPBYPASS`, `UDPCUSTOM`, `C-UDP`, `IPS-UDP`, `U-BYPASS`, `U-PPS`, `U-GBPS`", "Các biến thể làm ngập gói UDP, khác nhau về cách sinh gói và tốc độ"],
    ["Kiểu OVH", "`OVH`, `OVH-SMACK`, `OVH-SAS`, `OVH-SMELL`", "Các kỹ thuật flood được đặt tên theo nhà cung cấp bị nhắm tới"],
    ["Nhắm ứng dụng/game", "`DISCORD`, `GAME`, `FORTNITE`, `MINECRAFT`, `VALVE`, `FIVEM`, `HANDSHAKE`, `TS3`, `S4MP`, `SAMP`, `SAMP2`, `PTS3`", "Tấn công theo giao thức của dịch vụ cụ thể"],
    ["Tiện ích", "`SUBNET`, `RAND`", "Quét dải mạng nội bộ / chọn mục tiêu ngẫu nhiên"],
    ["Dừng", "`STOP`, `stop`, `Stop`", "Kết thúc"],
], widths=[3.2, 7.0, 6.8])
p("Lưu ý: các lệnh flood chỉ được thực thi khi `argc > 3`, tức là phải có đủ mục tiêu, cổng và thời lượng.")

h2("2.7 Hai module đã được dịch ngược chi tiết")
h3("STDHEX — tấn công TCP có dữ liệu")
p("Gọi `gethostbyname` để đổi mục tiêu thành địa chỉ, mở `socket(AF_INET, SOCK_STREAM)`, `connect`, "
  "rồi gửi lặp đi lặp lại các gói **1460 byte** cho tới khi hết thời lượng. Sau đó `close` và "
  "`_exit(0)` trong tiến trình con. Đây là workload nặng và đều — tốt cho đo EM.")
h3("CNC — tấn công TCP bằng số lượng kết nối")
p("Dùng `inet_addr` (không cần DNS), rồi lặp `socket` → `connect` → `sleep(1)` → `close` cho tới "
  "khi hết thời lượng. Sinh ra nhiều kết nối ngắn thay vì một dòng dữ liệu lớn.")
callout("warn", "Mục tiêu phải là địa chỉ số",
        "`processCmd` gọi `atoi()` trên tham số mục tiêu và yêu cầu kết quả `> 0`. Với "
        "`192.168.7.1` thì `atoi` trả 192 → hợp lệ. Với `google.com` thì trả 0 → **bị từ chối**. "
        "Đây là lý do C2 script luôn dùng địa chỉ IP.")

h2("2.8 Cơ chế ẩn mình và các tính năng khác")
bullet("**Không ghi lên đĩa.** Không `crontab`, không `rc.local`, không `/etc/init.d`. Nó sống trong RAM bằng `setsid()` + `fork`. Vì vậy dọn dẹp chỉ cần giết tiến trình, không cần xoá file.")
bullet("**Tự thử lại mãi mãi.** Mất kết nối C2 thì `sleep(5)` rồi thử lại, không bao giờ bỏ cuộc.")
bullet("**Diệt đối thủ.** Trong `.rodata` có đường dẫn `/usr/bin/python`, `/usr/bin/python3`, `/usr/bin/perl`, `/usr/sbin/telnetd` — đây là danh sách tiến trình nó tìm và giết để chiếm tài nguyên.")
bullet("**HTTP flood có Host giả.** Có bảng tên miền giả (`www.google.com`, `discord.com`, `salesforce.com`…) ở dạng DNS wire-format, dùng để ngụy trang request.")
bullet("**Đa tiến trình.** Mỗi lệnh tấn công là một tiến trình con riêng, nên một lần chạy có thể có 1 tiến trình cha + nhiều con.")
bullet("**Không có kernel module.** Không giống các mẫu rootkit khác, mẫu này chạy hoàn toàn ở user space.")

h2("2.9 Vì sao cấu trúc này tạo ra tín hiệu EM")
p("Tín hiệu EM phản ánh **dòng điện thay đổi theo hoạt động của CPU và bus bộ nhớ**. Một tiến trình "
  "đang chờ mạng gần như không tạo ra tín hiệu khác biệt so với máy rảnh. Ngược lại:")
bullet("Vòng lặp `send()` 1460 byte tạo ra hoạt động CPU + bus liên tục và đều.")
bullet("`fork()` tạo ra các đỉnh (spike) rõ ràng tại thời điểm chia tiến trình.")
bullet("`connect`/`close` liên tục tạo ra mẫu truy cập syscall đều đặn.")
bullet("Việc chuyển qua lại giữa nhiều tiến trình khiến bộ định thời (scheduler) hoạt động — cũng là tín hiệu.")
p("Đó là lý do chương 5 bắt bạn **chứng minh cửa sổ không rảnh** trước khi tin vào bất kỳ trace nào.")

page_break()

# ============================================================================
# CHUONG 3
# ============================================================================
h1("Chương 3 — Cấu hình Raspberry Pi 5")

h2("3.1 Phần cứng và nguồn")
bullet("Nguồn chính thức 5 V / 5 A. Nguồn yếu gây throttle, làm hỏng toàn bộ dataset.")
bullet("Tản nhiệt chủ động. Chạy liên tục 10 lần sẽ làm SoC nóng lên đáng kể.")
bullet("Thẻ microSD riêng cho lab — bạn sẽ phải re-image sau khi chạy xong.")
callout("warn", "Điều kiện tiên quyết",
        "Pi phải là thiết bị bạn **có thể xoá sạch và cài lại mà không mất gì**. Nếu không, "
        "hãy dùng máy ảo thay vì chạy trên Pi.")

h2("3.2 Ghi thẻ nhớ")
p("Dùng Raspberry Pi Imager. **Trước khi bấm Write**, mở hộp thoại tuỳ chỉnh (Ctrl+Shift+X):")
table(["Mục", "Giá trị", "Vì sao"], [
    ["Hostname", "`pi5-em-target`", "Tên ổn định cho tài liệu"],
    ["Username", "`emlab`", "Tài khoản quản trị của bạn"],
    ["Password", "mật khẩu mạnh, lưu vào trình quản lý", "Cần cho lần SSH đầu"],
    ["Wireless LAN", "để trống", "Lab không dùng WiFi"],
    ["Enable SSH", "**bật**", "Cách duy nhất vào máy không cần bàn phím"],
    ["Password authentication", "**bật**", "Ban đầu; sẽ chuyển sang key ở bước 3.7"],
], widths=[4.0, 5.5, 7.5])

h2("3.3 Lần khởi động đầu")
numbered("Cắm thẻ, cắm mạng có DHCP (không phải link bench), cắm nguồn.")
numbered("Đợi đèn ACT ngừng nháy thất thường — khoảng 2 phút cho lần đầu.")
numbered("Tìm địa chỉ IP trên router, hoặc thử `ssh emlab@pi5-em-target.local`.")
numbered("Kiểm tra danh tính:")

code("""uname -m                     # phải là aarch64
uname -a
tr -d '\\000' < /proc/device-tree/model; echo
cat /etc/os-release
vcgencmd get_throttled       # phải là 0x0""")

h2("3.4 Cổng kiểm tra 32-bit")
p("Đây là bước quyết định toàn bộ dự án. Cấu hình nhân có thể nói dối — phải chạy thử binary thật.")
code("""sudo apt update
sudo apt install -y gcc-arm-linux-gnueabihf
echo 'int main(){return 42;}' > /tmp/t.c
arm-linux-gnueabihf-gcc -static /tmp/t.c -o /tmp/t32
file /tmp/t32                # phải ghi ELF 32-bit LSB executable, ARM
/tmp/t32; echo "exit=$?"     # phải in exit=42""")
p("Nếu ra `Exec format error` (exit 126), Pi này không chạy được mẫu — dừng lại và báo cáo. "
  "**Không** rebuild sample sang 64-bit; điều đó làm nó không còn là malware in-the-wild.")
callout("info", "Kết quả trên Pi của bạn",
        "Test này đã chạy và trả về `exit=42`. Nghĩa là 32-bit ARM chạy native, không cần QEMU.")

h2("3.5 Tạo tài khoản chạy mẫu")
p("Sau khi ghi thẻ, chỉ có `emlab`. Ta cần thêm `victim` — tài khoản không mật khẩu, không sudo, "
  "chỉ tồn tại để sở hữu tiến trình malware.")
code("""sudo adduser --disabled-password --gecos "" victim
sudo passwd -l victim
sudo install -d -o victim -g victim -m 0750 \\
     /home/victim/work/{tools,staging,shmsamples,manifests}""")
p("Vì sao tách ba vai: `emlab` là bạn; `victim` là mẫu; `root` là runner (cần quyền cho GPIO và "
  "iptables). Nếu mẫu chạy bằng `emlab` thì nó có quyền của tài khoản quản trị — không bao giờ làm vậy.")

h2("3.6 Link bench tĩnh")
p("Rút cáp mạng thường, nối cáp trực tiếp laptop ↔ Pi. Trên Pi:")
code("""sudo nmcli con add type ethernet ifname eth0 con-name bench-static \\
     ipv4.method manual ipv4.addresses 192.168.7.2/24 \\
     ipv4.never-default yes ipv6.method disabled
sudo nmcli con up bench-static
ip -4 addr show eth0          # 192.168.7.2/24
ip route                      # CHỈ có 192.168.7.0/24 - không có default route""")
p("Trên laptop Windows: vào IPv4 properties của adapter USB-Ethernet, đặt `192.168.7.1/24`, "
  "**để trống Default gateway và DNS**. WiFi vẫn giữ cho internet của laptop.")
callout("danger", "Dòng `ip route` là cổng an toàn",
        "Nếu trên Pi còn default route, malware có thể tấn công người thứ ba. Không có default route "
        "thì mọi địa chỉ ngoài `192.168.7.0/24` đều không có đường đi.")

h2("3.7 SSH từ laptop")
code("""ssh-keygen -t ed25519 -C "emlab bench"
ssh-copy-id emlab@192.168.7.2
ssh emlab@192.168.7.2 'uname -m; id'""")
p("Tạo file `C:\\Users\\<bạn>\\.ssh\\config` trên laptop:")
code("""Host bench-pi
    HostName 192.168.7.2
    User emlab
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes""")
p("Từ giờ chỉ cần `ssh bench-pi`.")
callout("warn", "Hai cái bẫy SSH",
        "**(1)** Re-image Pi sẽ đổi host key → chạy `ssh-keygen -R 192.168.7.2` rồi kết nối lại. "
        "**(2)** Trên link tĩnh không có DHCP/DNS nên `pi5-em-target.local` không phân giải được — "
        "dùng địa chỉ IP.")

h2("3.8 Cài công cụ trên Pi")
p("Làm bước này khi Pi còn internet, **trước** khi bật isolation.")
code("""sudo apt install -y python3 python3-venv file binutils strace procps \\
                    iptables iproute2 gpiod
python3 -m venv /home/victim/work/tools/venv
/home/victim/work/tools/venv/bin/pip install pyzipper capstone""")

h2("3.9 Chép công cụ và sample lên Pi")
p("Công cụ chép trước (đi vào `tools/`, không bao giờ nằm cạnh sample):")
code("""# chạy trên laptop, trong thư mục bench/
scp bench/bashlite_runner.py bench/isolation-on.sh bench/isolation-off.sh \\
    bench/preflight.sh emlab@192.168.7.2:/home/victim/work/tools/""")
p("Sample chép dưới dạng **zip đã mã hoá**, không phải file ELF:")
code("""sha256sum 349d24768645262ce4bc0d75cdbd4b5b16c20c64a423b966a8215ed70740b777.zip
scp 349d2476*.zip emlab@192.168.7.2:/home/victim/work/staging/""")
p("Trên Pi, giải nén thẳng vào tmpfs (RAM) — cần kiểm tra tmpfs có cho phép thực thi:")
code("""findmnt -no OPTIONS /dev/shm        # nếu có 'noexec' thì làm bước dưới
sudo install -d -o victim -g victim -m 0750 /home/victim/work/shmsamples
sudo mount -t tmpfs -o rw,nosuid,nodev,size=64m,mode=0750 \\
     -o uid=$(id -u victim),gid=$(id -g victim) emlab /home/victim/work/shmsamples""")
callout("info", "Vì sao dùng tmpfs",
        "File ELF giải mã ra chỉ nằm trong RAM. Reboot là mất. Thẻ nhớ không bao giờ chứa malware "
        "ở dạng plaintext, nên không có gì để \"xoá\" một cách không chắc chắn.")

page_break()

# ============================================================================
# CHUONG 4
# ============================================================================
h1("Chương 4 — Quy tắc an toàn — đọc kỹ")

h2("4.1 Ba điều không bao giờ làm")
numbered("**Không chạy sample trên Windows.** Windows Defender có thể tự gửi file lên Microsoft — đó là rò rỉ mẫu ra ngoài.")
numbered("**Không chạy khi chưa bật isolation.** Không có ngoại lệ.")
numbered("**Không trỏ sample vào C2 thật.** `181.214.147.11` là hạ tầng botnet đang hoạt động.")

h2("4.2 `isolation-on.sh` làm gì")
table(["Bước", "Tác dụng"], [
    ["DNAT các cổng botnet", "Chuyển hướng TCP tới 999, 6667, 2323, 23, 80, 443 sang C2 giả — chỉ áp dụng cho gói tin của user `victim`"],
    ["Đặt policy DROP", "Chặn toàn bộ chiều ra mặc định"],
    ["Cho phép tối thiểu", "loopback, gói phản hồi, SSH từ `192.168.7.1`, và đúng một đích là C2"],
    ["DROP rõ ràng", "Luật riêng cho các cổng hay bị quét — để có bộ đếm"],
    ["DROP C2 thật", "Chặn mọi gói tới `181.214.147.11` trên mọi cổng/giao thức"],
    ["Tắt IPv6", "Tránh đường vòng không bị kiểm soát"],
    ["Tự rollback nếu lỗi", "Nếu một bước thất bại, khôi phục cấu hình permissive"],
], widths=[5.0, 12.0])

h2("4.3 DNAT: vì sao sample vẫn \"thấy\" C2")
p("Ta **không sửa file malware**. Thay vào đó, khi sample gọi `connect()` tới `181.214.147.11:999`, "
  "nhân Linux viết lại địa chỉ đích thành `192.168.7.1:999` **trước khi** tường lửa lọc gói. "
  "Sample không biết gì; nó tưởng đang nói chuyện với botnet thật.")
p("Thứ tự xử lý: `nat/OUTPUT` (viết lại địa chỉ) → `filter/OUTPUT` (cho qua hoặc chặn).")

h2("4.4 Kiểm chứng sau khi bật isolation")
code("""curl -m 5 -s http://1.1.1.1 >/dev/null; echo "curl=$?"   # phải khác 0
nc -z -w 3 1.1.1.1 80;                echo "nc=$?"        # phải khác 0
sudo iptables -L OUTPUT -n -v | head   # policy DROP
sudo iptables -t nat -L OUTPUT -n -v   # các luật DNAT đã có""")

h2("4.5 Đọc bộ đếm đúng cách")
callout("warn", "Điểm dễ hiểu sai nhất",
        "Khi sample gọi C2 thật trên cổng 999, gói tin **đã bị DNAT** nên nó **không bao giờ chạm** "
        "luật `DROP -d 181.214.147.11`. Vì vậy bộ đếm DROP có thể bằng 0 dù sample có gọi về nhà. "
        "Bằng chứng nằm ở bộ đếm của luật **DNAT**, không phải luật DROP.")
table(["Cần chứng minh", "Xem ở đâu"], [
    ["Sample đã gọi về C2 thật", "`sudo iptables -t nat -L OUTPUT -n -v` — đếm gói tăng dần"],
    ["Sample có thử gì khác không", "`sudo iptables -L OUTPUT -n -v` — các luật DROP"],
], widths=[7.0, 10.0])

h2("4.6 Khi có sự cố khẩn cấp")
code("""# 1. Giết mọi thứ liên quan
sudo pkill -f bashlite.bin; sudo pgrep -a bashlite
# 2. Tắt isolation, trả mạng về bình thường
sudo bash /home/victim/work/tools/isolation-off.sh
# 3. Xoá sample khỏi RAM
sudo umount /home/victim/work/shmsamples""")
p("Nếu nghi ngờ đã có kết nối ra ngoài: tắt nguồn Pi ngay, sau đó đọc lại log C2 và bộ đếm trước khi "
  "làm gì khác. Không xoá bằng chứng.")

page_break()

# ============================================================================
# CHUONG 5
# ============================================================================
h1("Chương 5 — Chạy: từng bước thực hành")

h2("5.1 Bước 0 — kiểm tra trước")
p("Trên Pi, sau khi đã bật isolation:")
code("""sudo bash /home/victim/work/tools/isolation-on.sh \\
     --admin 192.168.7.1 --c2 192.168.7.1 --c2-port 999 --owner-user victim""")
p("Trên laptop, mở một cửa sổ riêng cho C2 (để nguyên trong suốt quá trình chạy):")
code("""cd bench
python3 c2_server.py --mode serve --bind 192.168.7.1 --port 999 \\
        --script c2_script.json --sink-port 9999 --flood-seconds 3 \\
        --log runs/run01.jsonl --summary runs/run01.json""")

h2("5.2 Bước 1 — containment dry-run (không chạy malware)")
p("Mục đích: kiểm tra runner nhìn thấy ruleset là kín, **trước khi** có malware trên máy.")
code("""sudo python3 /home/victim/work/tools/bashlite_runner.py \\
  --sample /home/victim/work/shmsamples/bashlite.bin \\
  --count 1 --duration 2.5 \\
  --manifest /home/victim/work/manifests/e0.json""")
p("Kết quả mong đợi: exit 0 và verdict `full`. Nếu không, **dừng lại** — không dùng "
  "`--skip-containment-check` để đi tiếp.")

h2("5.3 Bước 2 — mimic (chạy thật, nhưng không phải malware)")
p("Đây là bước quan trọng nhất mà người mới hay bỏ qua. Một chương trình nhỏ tự viết, kết nối tới "
  "đúng địa chỉ C2 thật, giúp chứng minh DNAT + drop quyền + dọn dẹp hoạt động — mà không cần malware.")
code("""cat > /tmp/mimic.c <<'EOF'
#include <arpa/inet.h>
#include <string.h>
#include <unistd.h>
int main(void) {
    char b[] = "mimic: hello\\n";
    int s = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in a = {0};
    a.sin_family = AF_INET;
    a.sin_port = htons(999);
    a.sin_addr.s_addr = inet_addr("181.214.147.11");
    if (connect(s, (void *)&a, sizeof a) < 0) return 1;
    write(s, b, strlen(b));
    sleep(2);
    return 0;
}
EOF
arm-linux-gnueabihf-gcc -static /tmp/mimic.c -o /home/victim/work/tools/mimic""")
p("Trên laptop, C2 phải đang chạy. Sau đó trên Pi:")
code("""sudo python3 /home/victim/work/tools/bashlite_runner.py \\
  --sample /home/victim/work/tools/mimic \\
  --expected-hash $(sha256sum /home/victim/work/tools/mimic | cut -d' ' -f1) \\
  --execute --run-as victim --software-trigger \\
  --count 1 --duration 2.5 \\
  --manifest /home/victim/work/manifests/e1.json""")
p("Nếu C2 log có dòng `accept` và một dòng `recv`, toàn bộ đường đi đã thông.")

h2("5.4 Bước 3 — chế độ quan sát")
p("**Chế độ quan sát** (`--mode observe`) là C2 giả chỉ *nhận và ghi log*, không bao giờ gửi lệnh. "
  "Mục đích là xem sample tự nó làm gì trước khi ta ép nó làm bất cứ điều gì.")
p("Khởi động trên laptop:")
code("""python3 c2_server.py --mode observe --bind 192.168.7.1 --port 999 \\
        --log runs/discover-$(date +%H%M).jsonl""")
p("Trên Pi chạy sample đúng **một** lần:")
code("""sudo python3 /home/victim/work/tools/bashlite_runner.py \\
  --sample /home/victim/work/shmsamples/bashlite.bin \\
  --expected-hash 349d24768645262ce4bc0d75cdbd4b5b16c20c64a423b966a8215ed70740b777 \\
  --execute --run-as victim --gpio-pin 17 \\
  --count 1 --duration 2.5 \\
  --manifest /home/victim/work/manifests/e2-observe.json""")
p("Đọc log trên laptop:")
table(["Bạn thấy gì", "Ý nghĩa"], [
    ["`accept` từ `192.168.7.2`", "Sample đã kết nối được — DNAT hoạt động"],
    ["`recv` ngay sau đó, có nội dung", "**Banner** — bot nói trước, đúng như phân tích"],
    ["Không có gì thêm", "Bình thường: bot đang block chờ lệnh, mà observe không gửi lệnh"],
    ["Không có `accept` nào", "Có lỗi: kiểm tra DNAT, port, hoặc sample có chạy không"],
], widths=[6.5, 10.5])
callout("info", "Vì sao phải observe trước",
        "Nếu bạn bỏ bước này và C2 serve gửi sai định dạng, sample sẽ **im lặng bỏ qua** — bạn sẽ "
        "tưởng mình đã chạy đúng trong khi thực ra chẳng có gì xảy ra. Observe cho bạn một baseline "
        "để so sánh.")

h2("5.5 Bước 4 — chế độ serve, chạy theo kịch bản")
p("Tắt C2 observe, khởi động lại ở chế độ serve (lệnh ở bước 5.1), rồi chạy sample 3 lần:")
code("""sudo python3 /home/victim/work/tools/bashlite_runner.py \\
  --sample /home/victim/work/shmsamples/bashlite.bin \\
  --expected-hash 349d24768645262ce4bc0d75cdbd4b5b16c20c64a423b966a8215ed70740b777 \\
  --execute --run-as victim --gpio-pin 17 \\
  --count 3 --duration 2.5 --cooldown 0.5 \\
  --manifest /home/victim/work/manifests/run01.json""")
p("Kiểm tra C2 đã gửi đúng thứ mình nghĩ:")
code("""python3 c2_server.py --print-script""")

h2("5.6 Bước 5 — chứng minh cửa sổ không rảnh")
p("Đây là bước quyết định trace có dùng được hay không. C2 phải đang chạy.")
code("""sudo -u victim bash -c 'timeout 2.5 /home/victim/work/shmsamples/bashlite.bin & \\
                        sleep 0.4; ps -o pid,pcpu,cmd -C bashlite.bin'
sudo -u victim strace -f -c -o /tmp/syscalls.txt -w timeout 2.5 \\
     /home/victim/work/shmsamples/bashlite.bin
grep -E 'socket|connect|sendto|recvfrom' /tmp/syscalls.txt""")
p("Tiêu chí đạt:")
bullet("CPU của tiến trình khoảng trên 5 % tại thời điểm 0.4 s.")
bullet("Hàng nghìn syscall, trong đó có `socket`, `connect`, `sendto`.")
bullet("Sau khi chạy, `pgrep -a bashlite` không in ra gì.")
callout("danger", "CPU gần 0 nghĩa là dừng lại",
        "Nếu CPU gần 0, sample đang chờ C2 hoặc kịch bản sai. Trace khi đó gần giống máy rảnh và "
        "**không thể sửa được sau này**. Đây là lỗi phổ biến nhất của lần chạy đầu tiên.")

h2("5.7 Bước 6 — dọn dẹp")
code("""sudo pkill -f bashlite.bin; sudo pgrep -a bashlite
sudo umount /home/victim/work/shmsamples
sudo bash /home/victim/work/tools/isolation-off.sh""")
p("Sau đó, cách dọn dẹp **duy nhất đáng tin** là ghi lại ảnh thẻ nhớ đã chụp ở bước 0. `shred` trên "
  "thẻ SD không xoá được thật vì cơ chế cân bằng hao mòn giữ lại các khối cũ.")

page_break()

# ============================================================================
# CHUONG 6
# ============================================================================
h1("Chương 6 — Có phù hợp để đo EM liên tục như goodware_runner?")

h2("6.1 Câu trả lời ngắn")
callout("info", "Kết luận",
        "**Có** — với điều kiện hiểu \"liên tục\" là *một chuỗi N lần đo có trigger*, mỗi lần 2,5 giây, "
        "giống hệt cách `goodware_runner` làm. **Không** phù hợp với kiểu chạy nền liên tục không "
        "ngắt, vì bản chất malware này là event-driven: nó chỉ hoạt động khi có lệnh từ C2.")

h2("6.2 `goodware_runner` làm gì")
bullet("Bật GPIO 17 (mức cao) để báo oscilloscope bắt đầu ghi.")
bullet("Chờ 1,0 giây cho mọi thứ ổn định (settle) trước lần đo đầu.")
bullet("Chạy workload trong đúng `duration`, rồi tắt trigger.")
bullet("Nghỉ `cooldown`, lặp lại `count` lần.")
bullet("Workload là Python 64-bit, tính toán liên tục, một tiến trình.")

h2("6.3 `bashlite_runner` làm gì")
bullet("Cùng chân GPIO 17, cùng settle 1,0 giây, cùng thứ tự on → chạy → off.")
bullet("Sau mỗi cửa sổ: giết cả cây tiến trình, **rồi quét `/proc` tìm process con đã daemon hoá** và giết nốt.")
bullet("Ghi manifest JSON: hash, kiến trúc, verdict containment, thời gian từng lần, số process bị giết.")
bullet("Sample chạy bằng user `victim`, không phải root.")

h2("6.4 Bảng so sánh")
table(["Tiêu chí", "goodware_runner", "bashlite_runner"], [
    ["Trigger", "GPIO 17, mức cao", "**Giống hệt** — trace so sánh được"],
    ["Settle trước lần đầu", "1,0 s", "**Giống hệt**"],
    ["Độ dài cửa sổ", "`--duration`", "`--duration`"],
    ["Kiến trúc workload", "64-bit aarch64 (Python)", "**32-bit ARM** — khác"],
    ["Số tiến trình", "Thường 1", "1 cha + N con (mỗi lệnh flood một con)"],
    ["Mức hoạt động", "Liên tục, đều", "Theo lệnh: có giai đoạn chờ C2"],
    ["Dọn dẹp giữa các lần", "Không cần", "Bắt buộc — có sweep tự động"],
    ["Tính lặp lại", "Cao", "Cao **nếu** kịch bản C2 cố định"],
], widths=[3.6, 5.2, 8.2])

h2("6.5 Ba điểm khác biệt ảnh hưởng tới đo liên tục")
h3("(1) Đuôi tiến trình con — đã được xử lý")
p("`STDHEX` chạy 3 giây trong khi cửa sổ chỉ 2,5 giây, nên về lý thuyết con sẽ sống thêm ~0,5 giây. "
  "Nhưng runner **giết cả cây tiến trình ngay khi hết cửa sổ**, rồi quét `/proc` theo biến môi trường "
  "`EMLAB_RUN_ID` bắt nốt những con đã thoát khỏi nhóm. Vì vậy lần chạy sau **không** bị nhiễm.")
callout("info", "Vì sao `--flood-seconds 3` là đúng",
        "Cố ý đặt thời lượng flood **dài hơn** cửa sổ đo, để cuộc tấn công vẫn đang chạy khi cửa sổ "
        "đóng lại. Nếu đặt ngắn hơn, phần cuối cửa sổ sẽ rảnh và trace bị \"lõm\".")
h3("(2) Khoảng rảnh do bản chất mạng")
p("Từ 0 đến ~50 ms, sample chỉ khởi động. Nếu C2 trả lời chậm (ví dụ mất kết nối, phải `sleep(5)` thử "
  "lại), cửa sổ gần như rảnh hoàn toàn. Vì vậy bước 5.6 là bắt buộc, không phải tuỳ chọn.")
h3("(3) Khác kiến trúc — vấn đề lớn nhất, chưa giải quyết")
p("Tập goodware hiện tại là Python 64-bit. Malware là ARM 32-bit. Một bộ phân loại huấn luyện trên "
  "hai tập này **có thể học \"32-bit vs 64-bit\" thay vì \"malware vs lành\"**. Điều này không phụ "
  "thuộc vào việc chạy trên Pi hay trên máy ảo — nó là hạn chế của thiết kế dataset.")
p("Cách xử lý trước khi huấn luyện (chọn một):")
bullet("Bổ sung nhóm goodware 32-bit ARM cùng kích thước, cùng kiểu workload.")
bullet("Hoặc ghi rõ trong luận văn đây là hạn chế đã biết và không kết luận vượt quá dữ liệu.")
bullet("Hoặc chuyển sang mẫu aarch64 tự nhiên cho cả hai lớp (không rebuild mẫu hiện có).")

h2("6.6 Cấu hình khuyến nghị cho một chuỗi đo")
code("""# Trên Pi — 10 lần đo, cửa sổ 2,5 s
sudo python3 /home/victim/work/tools/bashlite_runner.py \\
  --sample /home/victim/work/shmsamples/bashlite.bin \\
  --expected-hash 349d2476...b777 \\
  --execute --run-as victim --gpio-pin 17 \\
  --count 10 --duration 2.5 --cooldown 0.8 \\
  --manifest /home/victim/work/manifests/series01.json""")
p("Vì sao `--cooldown 0.8` chứ không phải 0.5: mỗi lần chạy sinh 2–3 tiến trình và hàng nghìn syscall; "
  "0,8 giây cho SoC hạ nhiệt và cho sweep hoàn tất. Chạy 10 lần liên tiếp mà cooldown quá ngắn sẽ "
  "làm nhiệt tăng dần — và nhiệt thay đổi làm thay đổi tín hiệu.")
p("Trước và sau mỗi chuỗi, kiểm tra:")
code("""vcgencmd get_throttled     # phải là 0x0
pgrep -a bashlite         # phải rỗng""")

h2("6.7 Tiêu chí chất lượng cho từng trace")
table(["Chỉ số", "Ngưỡng", "Cách đo"], [
    ["CPU đỉnh trong cửa sổ", "> 5 %", "`ps` tại 0,4 s"],
    ["Số syscall", "hàng nghìn", "`strace -c`"],
    ["Có `connect`/`sendto`", "có", "`strace -c`"],
    ["Process còn sống sau trace", "0", "`pgrep -a bashlite`"],
    ["Throttle", "`0x0`", "`vcgencmd get_throttled`"],
    ["DNAT counter tăng", "có", "`iptables -t nat -L OUTPUT -n -v`"],
], widths=[5.0, 3.5, 8.5])

h2("6.8 Tóm lại")
p("Về mặt **cơ chế đo**, `bashlite_runner` tương thích với `goodware_runner`: cùng trigger, cùng "
  "settle, cùng độ dài cửa sổ, cùng manifest. Về mặt **nội dung tín hiệu**, malware có cấu trúc "
  "khác (nhiều tiến trình, có khoảng chờ, 32-bit). Hai điều này không mâu thuẫn — chúng là hai câu "
  "hỏi khác nhau: *đo có so sánh được không* (có) và *hai lớp có thực sự khác nhau vì malware không* "
  "(chưa chứng minh được cho tới khi giải quyết vấn đề kiến trúc).")

page_break()

# ============================================================================
# CHUONG 7
# ============================================================================
h1("Chương 7 — Xử lý sự cố")
table(["Triệu chứng", "Nguyên nhân thường gặp", "Cách sửa"], [
    ["Exit 126, \"Exec format error\"", "Thiếu hỗ trợ 32-bit", "Chạy lại test 3.4; nếu vẫn lỗi, dừng dự án trên máy này"],
    ["CPU gần 0 %", "C2 không chạy, hoặc không kết nối được", "Kiểm tra C2 đang listen; xem DNAT counter; chạy observe"],
    ["C2 log không có `accept`", "DNAT sai cổng, hoặc sample không chạy", "`iptables -t nat -L OUTPUT -n -v`; thử mimic trước"],
    ["Sample bị bỏ qua lệnh", "Sai định dạng (thiếu dấu cách sau `!`, dùng dấu phẩy)", "Xem bảng 2.5"],
    ["SSH báo host key thay đổi", "Đã re-image Pi", "`ssh-keygen -R 192.168.7.2`"],
    ["`pi5-em-target.local` không phân giải", "Link tĩnh không có mDNS/DNS", "Dùng `192.168.7.2`"],
    ["Thao tác thực thi thất bại", "`/dev/shm` hoặc tmpfs có `noexec`", "Mount tmpfs riêng không có `noexec`"],
    ["`pgrep -a bashlite` còn process", "Sweep không bắt được", "`sudo pkill -9 -f bashlite.bin`; kiểm tra biến môi trường có bị xoá không"],
    ["Hash không khớp", "File hỏng khi truyền", "Xoá, truyền lại; **không** sửa rồi chạy tiếp"],
    ["`apt` không chạy được", "Đã bật isolation", "Cài đặt xong trước khi bật; hoặc tạm `isolation-off.sh`"],
], widths=[4.6, 5.4, 7.0], font_size=8.5)

page_break()

# ============================================================================
# PHU LUC A
# ============================================================================
h1("Phụ lục A — Toàn bộ lệnh theo thứ tự")
p("Dùng khi bạn đã hiểu và chỉ cần chạy lại. Thay `349d2476...b777` bằng hash đầy đủ.")
h3("Trên Pi — sau khi đã flash và có internet")
code("""sudo apt update
sudo apt install -y python3 python3-venv file binutils strace procps iptables iproute2 gpiod
python3 -m venv /home/victim/work/tools/venv
/home/victim/work/tools/venv/bin/pip install pyzipper capstone
sudo adduser --disabled-password --gecos "" victim
sudo passwd -l victim
sudo install -d -o victim -g victim -m 0750 /home/victim/work/{tools,staging,shmsamples,manifests}
sudo bash /home/victim/work/tools/preflight.sh""")
h3("Trên laptop — chép file")
code("""scp bench/bashlite_runner.py bench/isolation-on.sh bench/isolation-off.sh \\
    bench/preflight.sh emlab@192.168.7.2:/home/victim/work/tools/
scp 349d2476*.zip emlab@192.168.7.2:/home/victim/work/staging/""")
h3("Trên Pi — giải mã vào RAM")
code("""findmnt -no OPTIONS /dev/shm
sudo install -d -o victim -g victim -m 0750 /home/victim/work/shmsamples
sudo mount -t tmpfs -o rw,nosuid,nodev,size=64m,mode=0750 \\
     -o uid=$(id -u victim),gid=$(id -g victim) emlab /home/victim/work/shmsamples
/home/victim/work/tools/venv/bin/python -I /home/victim/work/tools/decrypt_zip.py \\
  /home/victim/work/staging/349d2476*.zip 349d2476...b777.elf \\
  /home/victim/work/shmsamples/bashlite.bin infected
sudo chown victim:victim /home/victim/work/shmsamples/bashlite.bin
sudo chmod 0750 /home/victim/work/shmsamples/bashlite.bin
sha256sum /home/victim/work/shmsamples/bashlite.bin      # phải khớp""")
h3("Trên Pi — isolation và chạy")
code("""sudo bash /home/victim/work/tools/isolation-on.sh \\
     --admin 192.168.7.1 --c2 192.168.7.1 --c2-port 999 --owner-user victim

sudo python3 /home/victim/work/tools/bashlite_runner.py \\
  --sample /home/victim/work/shmsamples/bashlite.bin --count 1 --duration 2.5 \\
  --manifest /home/victim/work/manifests/e0.json

sudo python3 /home/victim/work/tools/bashlite_runner.py \\
  --sample /home/victim/work/shmsamples/bashlite.bin --expected-hash 349d2476...b777 \\
  --execute --run-as victim --gpio-pin 17 --count 3 --duration 2.5 --cooldown 0.8 \\
  --manifest /home/victim/work/manifests/run01.json""")
h3("Dọn dẹp")
code("""sudo pkill -f bashlite.bin; sudo pgrep -a bashlite
sudo umount /home/victim/work/shmsamples
sudo bash /home/victim/work/tools/isolation-off.sh""")

# ============================================================================
# PHU LUC B
# ============================================================================
h1("Phụ lục B — Bản đồ file trên Pi")
code("""/home/victim/work/
├── tools/            script + venv  (KHÔNG bao giờ để lẫn với sample)
│   ├── bashlite_runner.py
│   ├── isolation-on.sh
│   ├── isolation-off.sh
│   ├── preflight.sh
│   ├── decrypt_zip.py
│   ├── mimic
│   └── venv/
├── staging/          chỉ chứa file zip đã mã hoá
├── shmsamples/       tmpfs - chứa bashlite.bin, mất khi reboot
└── manifests/        JSON kết quả từng lần chạy""")
callout("info", "Vì sao tách thư mục",
        "Python và các công cụ nạp module từ thư mục hiện tại. Nếu để script chung với file lạ, một "
        "file độc hại tên `json.py` có thể được nạp thay cho thư viện thật.")

# ============================================================================
# PHU LUC C
# ============================================================================
h1("Phụ lục C — Checklist trước khi đo")
for item in [
    "Ảnh thẻ nhớ (restore point) đã chụp và kiểm tra hash",
    "`vcgencmd get_throttled` = `0x0`",
    "Không có `arm_freq` / `force_turbo` trong `/boot/firmware/config.txt`",
    "`ip route` trên Pi chỉ có `192.168.7.0/24`",
    "`rfkill block wifi` đã chạy, `wlan0` DOWN",
    "Isolation đã bật và `curl` / `nc` ra internet đều thất bại",
    "Containment dry-run trả verdict `full`",
    "Mimic đã chạy thành công và C2 log có `accept`",
    "Observe mode đã chạy và thấy banner từ bot",
    "Chế độ serve đã chạy và sink counter tăng",
    "CPU > 5 % và có syscall `sendto`/`connect` trong cửa sổ",
    "`pgrep -a bashlite` rỗng sau mỗi lần chạy",
    "Manifest JSON đã ghi cho từng lần",
    "DNAT counter tăng — bằng chứng sample đã gọi về C2 thật",
]:
    p("☐  " + item)

# ============================================================================
# PHU LUC D
# ============================================================================
h1("Phụ lục D — Những gì phải ghi vào luận văn")
bullet("SHA-256 của sample, nguồn tải, ngày tải, first-seen.")
bullet("Kết luận phân loại họ: *Gafgyt (dòng Bashlite/Qbot), build modular, source `snoopy.c`* — không gọi là Bashlite 2014.")
bullet("Lý do không rebuild sample sang 64-bit, và việc chạy 32-bit qua CONFIG_COMPAT.")
bullet("Cấu hình Pi: `uname -a`, `/etc/os-release`, `dpkg -l`, danh sách service đang chạy.")
bullet("`vcgencmd get_throttled` trước và sau mỗi phiên.")
bullet("Nội dung `c2_script.json` và phiên bản của nó.")
bullet("Log JSONL của C2 và file summary cho từng lần chạy.")
bullet("Manifest của runner cho từng lần chạy.")
bullet("Bất kỳ sai lệch nào: nhiệt độ, cooldown, số lần chạy, lệnh C2 phải đổi.")
bullet("Hạn chế đã biết: goodware 64-bit vs malware 32-bit.")
bullet("Việc dùng iptables thay VLAN, và lý do.")

doc.add_paragraph()
callout("warn", "Ghi chú về ngôn ngữ",
        "File này viết bằng tiếng Việt để bạn dễ đọc trong lúc thực hành. Quy ước của repo "
        "(`.cursor/rules/em-lab-invariants.mdc`) yêu cầu **mọi output của dự án bằng tiếng Anh**, "
        "nên khi dán nội dung vào luận văn hoặc phụ lục, hãy dịch lại — hoặc yêu cầu tôi xuất một "
        "bản tiếng Anh của tài liệu này.")

# ---- properties + footer ---------------------------------------------------
cp = doc.core_properties
cp.title = "Chạy Bashlite (Gafgyt) trên Raspberry Pi 5 qua SSH"
cp.subject = "EM side-channel lab — hướng dẫn vận hành"
cp.author = "EM lab operator"
cp.language = "vi-VN"

footer()
doc.save(OUT)
print("WROTE", OUT)
