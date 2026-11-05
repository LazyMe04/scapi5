"""Generate test image for REMnux MCP transfer check."""
from PIL import Image, ImageDraw

W, H = 900, 600
img = Image.new("RGB", (W, H), "#101418")
d = ImageDraw.Draw(img)

# Title bar
d.rectangle([0, 0, W, 70], fill="#1f6feb")
d.text((24, 26), "EM LAB - RUN 2 TRANSFER TEST", fill="#ffffff")

# Diagonal gradient band
for i in range(0, 360):
    t = i / 360
    r = int(30 + 200 * t)
    g = int(90 + 120 * t)
    b = int(200 - 120 * t)
    d.line([(i, 70), (i, 130)], fill=(r, g, b))

# Fake EM trace
points = []
for x in range(0, W, 2):
    y = 300
    y += int(70 * (0.5 + 0.5) * __import__("math").sin(x / 55.0) ** 3)
    y += int(35 * __import__("math").sin(x / 17.0))
    y += int(12 * __import__("math").sin(x / 5.0))
    points.append((x, y))
d.line(points, fill="#7ee787", width=2)

# Axes
d.line([(60, 170), (60, 520)], fill="#8b949e", width=2)
d.line([(60, 520), (860, 520)], fill="#8b949e", width=2)

# Legend box
d.rectangle([620, 360, 860, 520], fill="#161b22", outline="#30363d")
d.text((636, 374), "SOURCE: Windows host", fill="#58a6ff")
d.text((636, 398), "DEST:   REMnux guest", fill="#58a6ff")
d.text((636, 422), "SIZE:   900 x 600 px", fill="#58a6ff")
d.text((636, 446), "MODE:   scp over :2222", fill="#58a6ff")
d.text((636, 470), "STATUS: OK", fill="#7ee787")

# Footer
d.rectangle([0, H - 44, W, H], fill="#010409")
d.text((24, H - 30), "IoT Malware EM Side-Channel Analysis Lab - 2026-09-25", fill="#8b949e")

out = r"C:\Users\VJU_LONGBCSE2023\Desktop\EM\second_run\em_test_image.png"
img.save(out)
print("WROTE", out)
