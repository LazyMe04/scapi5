import re
import sys

path = sys.argv[1]
src = open(path, encoding="utf-8").read()

s = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
s = re.sub("//[^\\n]*", "", s)
s = re.sub(r'"(?:[^"\\]|\\.)*"', '""', s)

print("braces:", s.count("{"), s.count("}"),
      "OK" if s.count("{") == s.count("}") else "MISMATCH")
print("parens:", s.count("("), s.count(")"),
      "OK" if s.count("(") == s.count(")") else "MISMATCH")

need = ["usage", "ascii_to_key", "emit", "setup_device", "sleep_until",
        "timespec_add_ms", "filter_typable", "load_keyfile", "emit_key", "main"]
bad = False
for fn in need:
    defined = re.search(r"^static\s+[\w\s\*]+?\b" + fn + r"\s*\([^;{]*\)\s*\{", s,
                        re.M) is not None
    if fn == "main":
        defined = re.search(r"^int\s+main\s*\(", s, re.M) is not None
    calls = len(re.findall(r"\b" + fn + r"\s*\(", s))
    flag = "ok" if defined else "MISSING"
    if not defined:
        bad = True
    print(f"  {fn:<16} defined={flag:<8} call-sites={calls}")

# Every function used must be defined or be a libc symbol.
print("\nundefined-behaviour scan:")
for pat, label in [
    (r"\bstrcpy\s*\(", "strcpy (banned: unbounded)"),
    (r"\bsprintf\s*\(", "sprintf (banned: unbounded)"),
    (r"\bgets\s*\(", "gets (banned)"),
]:
    hits = len(re.findall(pat, s))
    print(f"  {label}: {hits}")

sys.exit(1 if bad else 0)
