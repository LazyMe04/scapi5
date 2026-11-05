# Run 2 artifacts

| File | Purpose |
|---|---|
| `main_summary_run2.md` | Full run-2 record: MCP setup, transfer/GUI test, ARM64 VM rebuild |
| `mcp_token.txt` | Bearer token for the REMnux MCP HTTP server (keep private) |
| `make_test_image.py` | Pillow script that generates the transfer-test PNG |
| `em_test_image.png` | 900x600 test image used for the host->guest transfer check |
| `start-arm64.sh` | Boots the ARM64 guest (direct kernel mode) — copy lives in the guest at `~/arm64-vm/` |
| `wait-guest.sh` | Polls ARM64 guest SSH until ready; runs inside REMnux |
| `extract-kernel.sh` | Pulls vmlinuz/initrd out of the ARM64 base image; runs inside REMnux |

Authoritative copies of the scripts live in the REMnux guest at `~/arm64-vm/`. The copies here
are the source of truth for editing; re-upload with `scp` after a change.
