"""
YouTube 直播偵測 daemon
全天候常駐：每 60 秒輪詢頻道 RSS feed（零配額），feed 有新條目才用
videos.list（1 單位/次）分類；待機室進追蹤清單，開播立刻雙通道通知。

用法：
    python check_live.py          常駐（Task Scheduler 登入時啟動）
    python check_live.py --once   只跑一輪掃描後退出（測試用）
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Windows UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

# ===== 強制 IPv4 =====
# 這台機器到 Google 的 IPv6 全是死路：getaddrinfo 排前面的 8 個 IPv6
# 各吃 21 秒連線逾時才輪到 IPv4，每個請求固定卡 168 秒（2026-08-01 實測）。
# 過濾成只剩 IPv4 後 feed/API 都在 0.2 秒內完成。查無 IPv4 時退回原結果。
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    infos = _orig_getaddrinfo(host, port, family, type, proto, flags)
    v4 = [i for i in infos if i[0] == socket.AF_INET]
    return v4 or infos


socket.getaddrinfo = _ipv4_only_getaddrinfo

# ===== 設定 =====

def _load_config() -> dict:
    """讀 config.json：頻道、身分組、Discord 頻道 ID 這類「換一個人用就要換」的設定。
    非機密但因人而異，所以不進版控；複製 config.example.json 改名成 config.json 再填。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if not os.path.exists(path):
        print("設定還沒完成：找不到 config.json。")
        print("請把資料夾裡的 config.example.json 複製一份改名成 config.json，")
        print("再把裡面的頻道 ID、身分組 ID、顯示名稱填成你自己的值。")
        print("每個欄位的意思，README 的「給工程師的部分」有說明。")
        sys.exit(1)
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


CFG = _load_config()

# 要監控的 YouTube 頻道
CHANNEL_ID = CFG["channel_id"]
CHANNEL_URL = CFG["channel_url"].rstrip("/")
DISPLAY_NAME = CFG["display_name"]                  # 通知 embed 的作者名
SHORT_NAME = CFG["short_name"]                      # 通知標題用的簡稱
BOT_LABEL = CFG.get("bot_label", "LiveNotifyBot")   # footer 與 User-Agent 用的名稱
FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"

def _load_env_file():
    """把程式所在資料夾的 .env 讀進環境變數。
    已經設定過的變數不會被覆蓋（排程啟動器會先灌一次）。"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_env_file()


def _require(name: str) -> str:
    """必填設定沒填時，印白話說明後結束，不要丟一串英文錯誤給使用者"""
    val = os.environ.get(name, "").strip()
    if not val:
        print("設定還沒完成：" + name + " 是空的。")
        print("請打開程式資料夾裡的 .env 檔（如果沒有，先複製一份 .env.example 改名成 .env），")
        print("在 " + name + " 的等號後面填上對應的值，存檔以後再啟動一次。")
        print("每個值要去哪裡拿，README 的「六個設定值怎麼拿」有一步一步的說明。")
        sys.exit(1)
    return val


YT_API_KEY = _require("YT_API_KEY")

WEBHOOK_FAN = _require("WEBHOOK_FAN")
WEBHOOK_TEST = _require("WEBHOOK_TEST")
WEBHOOK_SCHEDULE = _require("WEBHOOK_SCHEDULE")

# 開台通知的 tag 對象：主播本人 + 設定檔列出的身分組
VT_USER_ID = CFG["owner_user_id"]
MENTION_ROLE_IDS = CFG.get("mention_role_ids", [])
LIVE_MENTION = " ".join([f"<@{VT_USER_ID}>"] + [f"<@&{r}>" for r in MENTION_ROLE_IDS])

# 管理者 Discord user id：管理頻道通知會 tag 這些人，名單內任一人按 👍 都算確認
# 預設讀 config.json 的 admin_user_ids；.env 寫 ADMIN_USER_IDS=id1,id2 可覆蓋，不必改程式
ADMIN_USER_IDS = [
    i.strip()
    for i in (os.environ.get("ADMIN_USER_IDS") or ",".join(CFG.get("admin_user_ids", []))).split(",")
    if i.strip()
]
# 通知內文用的 mention 字串（多人時全部 tag）
ADMIN_MENTION = " ".join(f"<@{i}>" for i in ADMIN_USER_IDS)

# 發完訊息要加的自訂 emoji（格式「名稱:ID」，留空就不加）
VT_EMOJI = CFG.get("reaction_emoji", "")

# 管理者 在管理頻道按這個 emoji = 確認發週表到粉絲頻道
CONFIRM_EMOJI = "\U0001f44d"  # 👍

# 粉絲伺服器的直播提醒頻道 ID（加反應用）
FAN_CHANNEL_ID = CFG["fan_channel_id"]
# 管理頻道 ID（只有管理者看得到，用來問要不要發）
TEST_CHANNEL_ID = CFG["admin_channel_id"]

# 輪詢節奏
FEED_POLL_INTERVAL = 60      # feed 輪詢間隔（零配額，實測 0.15 秒/次）
WAIT_POLL_NEAR = 60          # 待機室接近開播（30 分內或已過預定時間）的 API 輪詢間隔
WAIT_POLL_FAR = 600          # 預定開播還很遠時的 API 輪詢間隔（省配額）
NEAR_WINDOW = 30 * 60
HEARTBEAT_HOUR = 20          # 每天 20:00 後發一次心跳（當天沒開台才發）
POST_CHECK_INTERVAL = 1800   # 社群貼文每 30 分鐘檢查一次
SCHEDULE_KEYWORDS = ["週表", "周表", "直播排程"]
POSTS_URL = f"{CHANNEL_URL}/posts"
HTTP_TIMEOUT = 30

# 狀態檔
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, "state.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "check_live.log")

ATOM = "{http://www.w3.org/2005/Atom}"
YT_NS = "{http://www.youtube.com/xml/schemas/2015}"


def log(msg: str):
    """寫 log"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def fetch_feed() -> list[tuple[str, str]]:
    """抓頻道 RSS feed，回傳 [(video_id, title), ...]，新的在前"""
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": f"{BOT_LABEL}/1.0"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        root = ET.fromstring(resp.read())
    out = []
    for e in root.findall(f"{ATOM}entry"):
        vid = e.findtext(f"{YT_NS}videoId")
        title = e.findtext(f"{ATOM}title") or ""
        if vid:
            out.append((vid, title))
    return out


def videos_lookup(ids: list[str]) -> dict:
    """videos.list 一次查多支（1 quota unit），回傳 {video_id: item}"""
    url = (
        "https://www.googleapis.com/youtube/v3/videos"
        f"?part=snippet,liveStreamingDetails&id={','.join(ids)}&key={YT_API_KEY}"
    )
    with urllib.request.urlopen(urllib.request.Request(url), timeout=HTTP_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return {item["id"]: item for item in data.get("items", [])}


def parse_iso_utc(s: str) -> float | None:
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return None


def fmt_local(ts: float | None) -> str:
    if ts is None:
        return "時間未定"
    return time.strftime("%m/%d %H:%M", time.localtime(ts))


def send_webhook(webhook_url: str, payload: dict, max_retries: int = 3, wait: bool = False) -> bool | str:
    """POST Discord webhook，碰 403 自動重試。
    wait=True 時帶 ?wait=true，回傳建立的訊息 id 字串（失敗回空字串）"""
    if wait:
        webhook_url += ("&" if "?" in webhook_url else "?") + "wait=true"
    json_data = json.dumps(payload).encode("utf-8")
    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(
            webhook_url,
            data=json_data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"{BOT_LABEL}/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read()
                log(f"Webhook 發送成功 (HTTP {resp.status})")
                if not wait:
                    return True
                try:
                    return str(json.loads(body.decode("utf-8")).get("id", ""))
                except Exception:
                    return ""
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            log(f"Webhook 失敗 (第{attempt}次): HTTP {e.code} {body}")
            if e.code == 403 and attempt < max_retries:
                time.sleep(30)
                continue
            return "" if wait else False
    return "" if wait else False


def add_reaction_via_bot(channel_id: str, message_id: str, emoji: str):
    """用 Discord Bot API 幫 webhook 發的訊息加反應"""
    # Bot token 從環境變數讀（跟 MCP server 共用同一個）
    bot_token = os.environ.get("DISCORD_TOKEN", "")
    if not bot_token:
        log("DISCORD_TOKEN 沒設定，跳過加反應")
        return

    # emoji 要 URL encode（自訂 emoji 格式：name:id）
    encoded_emoji = urllib.request.quote(emoji)
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}/@me"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bot {bot_token}"},
        method="PUT",
    )
    # PUT 反應 API 回傳 204 No Content
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            log(f"反應已加 ({emoji})")
    except urllib.error.HTTPError as e:
        log(f"加反應失敗: HTTP {e.code}")


def get_reaction_user_ids(channel_id: str, message_id: str, emoji: str) -> list[str]:
    """用 Discord Bot API 讀某訊息上某 emoji 的反應者 user id 清單（沒 token 回空清單）"""
    bot_token = os.environ.get("DISCORD_TOKEN", "")
    if not bot_token:
        return []
    encoded_emoji = urllib.request.quote(emoji)
    url = (
        f"https://discord.com/api/v10/channels/{channel_id}"
        f"/messages/{message_id}/reactions/{encoded_emoji}?limit=100"
    )
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bot {bot_token}", "User-Agent": f"{BOT_LABEL}/1.0"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        users = json.loads(resp.read().decode("utf-8"))
    return [str(u.get("id", "")) for u in users]


def send_live_notification(video_id: str, title: str):
    """發直播通知到粉絲伺服器"""
    yt_url = f"https://www.youtube.com/watch?v={video_id}"
    thumbnail = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"

    payload = {
        "content": LIVE_MENTION,
        "embeds": [{
            "title": f"\U0001f534 {SHORT_NAME}開台啦！",
            "url": yt_url,
            "description": f"**{title}**\n\U0001f449 [點我進入直播]({yt_url})",
            "color": 0xFF0000,
            "image": {"url": thumbnail},
            "author": {
                "name": DISPLAY_NAME,
                "url": CHANNEL_URL,
            },
            "footer": {"text": f"{BOT_LABEL} 直播通知"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }],
    }

    return send_webhook(WEBHOOK_FAN, payload)


def notify_live(video_id: str, title: str):
    """開播：發粉絲伺服器 + 管理頻道各一則"""
    send_live_notification(video_id, title)
    yt_url = f"https://www.youtube.com/watch?v={video_id}"
    send_webhook(WEBHOOK_TEST, {
        "content": f"{ADMIN_MENTION} 偵測到開台，已發粉絲伺服器通知。",
        "embeds": [{
            "title": f"\U0001f534 {SHORT_NAME}開台啦！",
            "url": yt_url,
            "description": f"**{title}**",
            "color": 0xFF0000,
            "footer": {"text": f"{BOT_LABEL} 直播通知"},
        }],
    })


def ask_waiting_preannounce(video_id: str, title: str, scheduled: float | None) -> str:
    """偵測到待機室 → 發管理頻道問 管理者 要不要先發粉絲頻道。
    回傳管理頻道那則訊息的 id（之後輪詢 👍 用；失敗回空字串）"""
    yt_url = f"https://www.youtube.com/watch?v={video_id}"
    payload = {
        "content": f"{ADMIN_MENTION} {SHORT_NAME}開了待機室，按 \U0001f44d 我就先發到粉絲頻道。",
        "embeds": [{
            "title": "\U0001f4e2 偵測到待機室（待確認）",
            "url": yt_url,
            "description": f"**{title}**\n預定開播：{fmt_local(scheduled)}\n\n⏳ **按 \U0001f44d 才會先發到粉絲頻道；不按就等正式開播再通知**",
            "color": 0xFFA500,
            "image": {"url": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"},
            "footer": {"text": f"{BOT_LABEL} 待機室偵測"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }],
    }
    return send_webhook(WEBHOOK_TEST, payload, wait=True)


def send_waiting_preannounce(video_id: str, title: str, scheduled: float | None) -> bool:
    """管理者 按 👍 後：先發待機室通知到粉絲伺服器直播提醒頻道"""
    yt_url = f"https://www.youtube.com/watch?v={video_id}"
    payload = {
        "content": LIVE_MENTION,
        "embeds": [{
            "title": f"\U0001f4e2 {SHORT_NAME}開了待機室！",
            "url": yt_url,
            "description": f"**{title}**\n\U0001f552 預定開播：{fmt_local(scheduled)}\n\U0001f449 [點我進入待機室]({yt_url})",
            "color": 0xFFA500,
            "image": {"url": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"},
            "author": {
                "name": DISPLAY_NAME,
                "url": CHANNEL_URL,
            },
            "footer": {"text": f"{BOT_LABEL} 待機室通知"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }],
    }
    return bool(send_webhook(WEBHOOK_FAN, payload))


def send_heartbeat(waiting: dict):
    """每天 20:00 後的心跳：當天還沒開台時發到管理頻道，tag 管理者"""
    desc = "常駐偵測運作中（feed 每分鐘掃描、待機室開播即通知）。今天到目前為止沒有偵測到開台。"
    if waiting:
        lines = "\n".join(
            f"• {w.get('title', '(無標題)')}（預定 {fmt_local(w.get('scheduled'))}）"
            for w in waiting.values()
        )
        desc += f"\n\n追蹤中的待機室：\n{lines}"
    payload = {
        "content": f"{ADMIN_MENTION}",
        "embeds": [{
            "title": "\U0001f4cb 今日直播掃描狀態",
            "description": desc,
            "color": 0x808080,
            "footer": {"text": f"{BOT_LABEL} 每日心跳"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }],
    }
    send_webhook(WEBHOOK_TEST, payload)


def fetch_community_posts() -> list[dict]:
    """抓 YouTube 社群貼文頁，回傳 [{id, text, url}, ...]"""
    req = urllib.request.Request(POSTS_URL, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "zh-TW,zh;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    import re as _re
    m = _re.search(r'var ytInitialData\s*=\s*(\{.+?\});\s*</script>', html, _re.DOTALL)
    if not m:
        return []
    data = json.loads(m.group(1))
    tabs = data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
    for tab in tabs:
        tr = tab.get("tabRenderer", {})
        if not tr.get("selected"):
            continue
        sections = tr.get("content", {}).get("sectionListRenderer", {}).get("contents", [])
        if not sections:
            return []
        items = sections[0].get("itemSectionRenderer", {}).get("contents", [])
        posts = []
        for item in items:
            post = item.get("backstagePostThreadRenderer", {}).get("post", {}).get("backstagePostRenderer", {})
            if not post:
                continue
            pid = post.get("postId", "")
            text_runs = post.get("contentText", {}).get("runs", [])
            text = "".join(r.get("text", "") for r in text_runs)
            img_url = ""
            att = post.get("backstageAttachment", {})
            bir = att.get("backstageImageRenderer", {})
            thumbs = bir.get("image", {}).get("thumbnails", [])
            if thumbs:
                img_url = max(thumbs, key=lambda x: x.get("width", 0)).get("url", "")
            posts.append({
                "id": pid,
                "text": text,
                "url": f"https://www.youtube.com/post/{pid}",
                "image": img_url,
            })
        return posts
    return []


def send_schedule_to_fan(post: dict):
    """發週表通知到粉絲週表頻道"""
    embed = {
        "title": f"\U0001f4cb {SHORT_NAME}發新週表了！",
        "url": post["url"],
        "description": post["text"][:2000],
        "color": 0x3A4B22,
        "author": {
            "name": DISPLAY_NAME,
            "url": CHANNEL_URL,
        },
        "footer": {"text": f"{BOT_LABEL} 週表通知"},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if post.get("image"):
        embed["image"] = {"url": post["image"]}
    payload = {"embeds": [embed]}
    return send_webhook(WEBHOOK_SCHEDULE, payload)


def notify_schedule_pending(post: dict) -> str:
    """偵測到新週表 → 先通知管理頻道等 管理者 確認，不直接發粉絲頻道。
    回傳管理頻道那則訊息的 id（之後輪詢 👍 用；失敗回空字串）"""
    embed = {
        "title": "\U0001f4cb 偵測到新週表（待確認）",
        "url": post["url"],
        "description": post["text"][:1500] + "\n\n⏳ **等 管理者 確認後才會發到粉絲頻道**",
        "color": 0xFFA500,
        "footer": {"text": f"{BOT_LABEL} 週表偵測"},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if post.get("image"):
        embed["image"] = {"url": post["image"]}
    payload = {
        "content": f"{ADMIN_MENTION} {SHORT_NAME}發了新週表，按 \U0001f44d 我就發到粉絲頻道。",
        "embeds": [embed],
    }
    return send_webhook(WEBHOOK_TEST, payload, wait=True)


def this_week_key() -> str:
    """回傳本週的 ISO week key（如 2026-W31），限制每週最多發一則"""
    now = time.localtime()
    iso = datetime.fromtimestamp(time.mktime(now)).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def check_schedule_posts(state: dict):
    """每 30 分鐘查社群貼文，偵測到新週表先通知管理頻道"""
    now = time.time()
    if now - state.get("last_post_check", 0) < POST_CHECK_INTERVAL:
        return

    state["last_post_check"] = now
    notified_posts: list = state.setdefault("notified_post_ids", [])

    try:
        posts = fetch_community_posts()
    except Exception as e:
        log(f"社群貼文抓取失敗: {type(e).__name__}: {e}")
        return

    if not posts:
        return

    week_key = this_week_key()
    already_sent_this_week = state.get("schedule_sent_week") == week_key

    for post in posts:
        if post["id"] in notified_posts:
            continue
        if any(kw in post["text"] for kw in SCHEDULE_KEYWORDS):
            log(f"偵測到新週表：{post['id']} {post['text'][:60]}")
            if already_sent_this_week:
                log(f"本週（{week_key}）已發過週表，跳過")
            else:
                msg_id = notify_schedule_pending(post)
                state["pending_schedule"] = {
                    "id": post["id"],
                    "text": post["text"],
                    "url": post["url"],
                    "image": post.get("image", ""),
                    "message_id": msg_id or "",
                }
            notified_posts.append(post["id"])

    state["notified_post_ids"] = notified_posts[-30:]


def check_pending_confirmation(state: dict):
    """待確認週表存在時，每輪查管理頻道那則通知有沒有 管理者 的 👍，有就發粉絲頻道"""
    pending = state.get("pending_schedule")
    if not pending or not pending.get("message_id"):
        return
    try:
        users = get_reaction_user_ids(TEST_CHANNEL_ID, pending["message_id"], CONFIRM_EMOJI)
    except Exception as e:
        log(f"查 \U0001f44d 反應失敗: {type(e).__name__}: {e}")
        return
    if not any(uid in users for uid in ADMIN_USER_IDS):
        return
    week_key = this_week_key()
    if state.get("schedule_sent_week") == week_key:
        log(f"收到 \U0001f44d 但本週（{week_key}）已發過週表，清掉待確認")
        state.pop("pending_schedule", None)
        return
    log(f"管理者 按了 \U0001f44d，發週表到粉絲頻道：{pending['id']}")
    if send_schedule_to_fan(pending):
        state["schedule_sent_week"] = week_key
        state.pop("pending_schedule", None)
        send_webhook(WEBHOOK_TEST, {"content": "✅ 收到 \U0001f44d，週表已發到粉絲頻道。"})
    else:
        log("週表發送失敗，保留待確認下一輪重試")


def check_waiting_confirmation(state: dict):
    """待機室問過 管理者 但還沒先發的，每輪查管理頻道那則訊息有沒有 管理者 的 👍，有就先發粉絲頻道"""
    waiting: dict = state.get("waiting", {})
    for vid, w in waiting.items():
        msg_id = w.get("ask_msg_id")
        if not msg_id or w.get("pre_sent"):
            continue
        try:
            users = get_reaction_user_ids(TEST_CHANNEL_ID, msg_id, CONFIRM_EMOJI)
        except Exception as e:
            log(f"查待機室 \U0001f44d 反應失敗: {type(e).__name__}: {e}")
            continue
        if not any(uid in users for uid in ADMIN_USER_IDS):
            continue
        log(f"管理者 按了 \U0001f44d，先發待機室通知到粉絲頻道：{vid}")
        if send_waiting_preannounce(vid, w.get("title", ""), w.get("scheduled")):
            w["pre_sent"] = True
            send_webhook(WEBHOOK_TEST, {"content": f"✅ 收到 \U0001f44d，待機室通知已先發到粉絲頻道：{w.get('title', '')}"})
        else:
            log("待機室先發失敗，下一輪重試")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def today_str() -> str:
    return time.strftime("%Y-%m-%d")


def waiting_interval(scheduled_ts: float | None, now: float) -> int:
    """預定開播還很遠就慢慢查，接近（或沒排時間、已超時）就每分鐘查"""
    if scheduled_ts is None or scheduled_ts - now <= NEAR_WINDOW:
        return WAIT_POLL_NEAR
    return WAIT_POLL_FAR


def run_cycle(state: dict):
    """一輪掃描：feed 找新條目 + 待機清單到期檢查，合併成最多一次 videos.list"""
    now = time.time()
    known: list = state.setdefault("known_ids", [])
    waiting: dict = state.setdefault("waiting", {})
    notified: list = state.setdefault("notified_ids", [])

    entries = fetch_feed()
    feed_titles = dict(entries)
    new_ids = [vid for vid, _ in entries if vid not in known]

    due_ids = [vid for vid, w in waiting.items() if now >= w.get("next_check", 0)]
    lookup_ids = new_ids + [vid for vid in due_ids if vid not in new_ids]
    if not lookup_ids:
        return

    if new_ids:
        log(f"feed 新條目 {len(new_ids)} 支：{', '.join(new_ids)}")
    info = videos_lookup(lookup_ids)

    for vid in lookup_ids:
        item = info.get(vid)
        if item is None:
            if vid in waiting:
                log(f"待機室 {vid} 已消失（刪除或轉私人），移除追蹤")
                waiting.pop(vid)
            else:
                log(f"{vid} 查無資料（可能會限或已刪）：{feed_titles.get(vid, '')}")
            continue

        sn = item.get("snippet", {})
        lbc = sn.get("liveBroadcastContent")
        title = sn.get("title", "") or feed_titles.get(vid, "")
        lsd = item.get("liveStreamingDetails") or {}

        if lbc == "live":
            waiting.pop(vid, None)
            if vid not in notified:
                log(f"開播！{vid} {title}")
                notify_live(vid, title)
                notified.append(vid)
                state["last_live_date"] = today_str()
        elif lbc == "upcoming":
            sched = parse_iso_utc(lsd.get("scheduledStartTime", ""))
            iv = waiting_interval(sched, now)
            if vid not in waiting:
                log(f"發現待機室：{vid} {title}（預定 {fmt_local(sched)}，輪詢 {iv} 秒）")
                ask_msg_id = ask_waiting_preannounce(vid, title, sched)
                waiting[vid] = {"ask_msg_id": ask_msg_id or "", "pre_sent": False}
            waiting[vid].update({"title": title, "scheduled": sched, "next_check": now + iv})
        else:
            if vid in waiting:
                if lsd.get("actualEndTime"):
                    log(f"待機室 {vid} 已開播並結束於輪詢間隔內，未及通知：{title}")
                else:
                    log(f"待機室 {vid} 已取消：{title}")
                waiting.pop(vid)
            elif vid in new_ids:
                log(f"新影片（非直播）：{vid} {title}")

    for vid in new_ids:
        if vid not in known:
            known.append(vid)
    state["known_ids"] = known[-100:]
    state["notified_ids"] = notified[-50:]


def maybe_heartbeat(state: dict):
    now = time.localtime()
    today = time.strftime("%Y-%m-%d", now)
    if now.tm_hour < HEARTBEAT_HOUR:
        return
    if state.get("last_heartbeat_date") == today or state.get("last_live_date") == today:
        return
    log("20:00 心跳：今天尚未偵測到開台")
    send_heartbeat(state.get("waiting", {}))
    state["last_heartbeat_date"] = today


def main():
    once = "--once" in sys.argv
    state = load_state()
    log(f"daemon 啟動（IPv4 強制、feed 每 {FEED_POLL_INTERVAL} 秒）" + ("（--once 測試模式）" if once else ""))
    if os.environ.get("DISCORD_TOKEN"):
        log("DISCORD_TOKEN 已載入，\U0001f44d 自動發週表啟用")
    else:
        log("DISCORD_TOKEN 未設定，\U0001f44d 自動發週表停用（偵測到週表仍會通知管理頻道，需手動發）")
    last_alive = time.time()

    while True:
        try:
            run_cycle(state)
            check_schedule_posts(state)
            check_pending_confirmation(state)
            check_waiting_confirmation(state)
            maybe_heartbeat(state)
            save_state(state)
        except Exception as e:
            log(f"本輪失敗: {type(e).__name__}: {e}")

        if once:
            log(f"--once 完成：known={len(state.get('known_ids', []))} "
                f"waiting={len(state.get('waiting', {}))} notified={len(state.get('notified_ids', []))}")
            return

        if time.time() - last_alive >= 3600:
            log(f"存活：known={len(state.get('known_ids', []))} waiting={len(state.get('waiting', {}))}")
            last_alive = time.time()

        time.sleep(FEED_POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("手動中止")
    except Exception as e:
        log(f"daemon 崩潰: {type(e).__name__}: {e}")
        raise
