"""手動把 state.json 裡的 pending_schedule 發到粉絲週表頻道。

用法：python -u send_pending.py
（管理者在管理頻道按 👍 確認後跑這支；自動偵測 👍 的機制上線前的人工流程）
"""

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# check_live import 時就要讀環境變數，先把 .env 灌進去
with open(os.path.join(SCRIPT_DIR, ".env"), encoding="utf-8-sig") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

sys.path.insert(0, SCRIPT_DIR)
import check_live  # noqa: E402

state = check_live.load_state()
pending = state.get("pending_schedule")
if not pending:
    print("state.json 沒有 pending_schedule，沒東西可發")
    sys.exit(1)

print(f"要發的貼文：{pending['id']}")
print(pending["text"])
print("---")
ok = check_live.send_schedule_to_fan(pending)
print("發送成功" if ok else "發送失敗")
sys.exit(0 if ok else 2)
