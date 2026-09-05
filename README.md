**繁體中文** | [English](./README.en.md)

# 直播開台自動通知機器人

這是一支放在電腦裡自己執行的小程式。它會一直盯著指定的 YouTube 頻道，發現開台、開了待機室、或發了新的直播週表，就自動把消息發到 Discord。

## 它會做什麼

- **開台通知** — 每分鐘檢查一次，偵測到直播就把標題、縮圖、連結發到粉絲直播提醒頻道，並標記主播本人和兩個身分組
- **待機室先問過你** — 偵測到待機室先發一則到管理頻道問你，你按 👍 才發粉絲頻道；不按就等正式開播再通知
- **週表也先問過你** — 每半小時掃一次社群貼文，發現新週表先問你，按 👍 才發粉絲週表頻道，同一週只發一次
- **每日狀態回報** — 晚上八點後當天沒開台，發一則簡短回報到管理頻道，讓你知道程式還活著

## 開始之前要準備什麼

**一台不會關機也不會睡著的電腦。** 這件事比什麼都重要。程式只有在電腦醒著的時候才會執行，筆電闔上蓋子的那段時間，它等於完全停住，那段時間開的台就會整場漏掉。如果你的電腦習慣用完就闔上，這支程式放在上面一定會漏。想要它真的二十四小時盯著，要嘛把電腦的睡眠關掉、蓋子闔上也不休眠，要嘛把程式放到一台永遠開著的機器上。

**Python。** 這是程式的執行環境，到 python.org 下載安裝就好，版本 3.9 以上都可以。安裝畫面第一頁下方有一個「Add python.exe to PATH」的勾選框，**一定要勾起來**，不勾之後會找不到程式。除此之外不用再裝任何東西。

## 安裝步驟

**第一步，把檔案抓下來。** 到 GitHub 頁面按綠色的 Code 按鈕，選 Download ZIP，解壓縮到你想放的地方，例如「文件」資料夾底下。

**第二步，建立設定檔。** 在程式資料夾的空白處按住 Shift 再按滑鼠右鍵，選「在這裡開啟 PowerShell 視窗」，貼上這兩行按 Enter：

```
Copy-Item .env.example .env
Copy-Item config.example.json config.json
```

資料夾裡會多出兩個檔：`.env` 放密鑰，`config.json` 放頻道設定。兩個都用記事本打開填。（直接在檔案總管改檔名有時會被 Windows 擋下來，用上面兩行最保險。）

**第三步，填設定值。** 每個值要去哪裡拿，下面一個一個說。

## .env 的六個值怎麼拿

**YT_API_KEY**

1. 進 console.cloud.google.com，用 Google 帳號登入
2. 建立新專案
3. 上方搜尋列打「YouTube Data API v3」，進去按啟用
4. 左邊選單「憑證」→「建立憑證」→「API 金鑰」
5. 複製那串字

**WEBHOOK_FAN、WEBHOOK_TEST、WEBHOOK_SCHEDULE**

1. 在 Discord 該頻道名稱旁按齒輪（編輯頻道）
2. 左邊「整合」→「Webhook」→「建立 Webhook」
3. 按「複製 Webhook 網址」

三個分別在這三個頻道各做一次：FAN 是粉絲的直播提醒頻道，TEST 是只有管理者看得到的頻道，SCHEDULE 是粉絲的週表頻道。

**DISCORD_TOKEN**

1. 進 discord.com/developers/applications，按 New Application，名字隨便取
2. 左邊點 Bot，按 Reset Token，複製那串字（等於密碼，別給別人）
3. 左邊點 OAuth2，在 URL Generator 的 SCOPES 勾 `bot`
4. 下面權限勾 View Channels 和 Read Message History
5. 複製產生的網址貼到瀏覽器，選你的伺服器把機器人加進去

沒做這一步的話，按 👍 不會有反應，只會收到通知。

**ADMIN_USER_IDS**（選填，填了會蓋掉 config.json 的 `admin_user_ids`）

1. Discord「使用者設定」→「進階」→ 打開開發者模式
2. 回到聊天畫面，在自己頭像按右鍵 →「複製使用者 ID」
3. 貼過來，多人用逗號隔開：`123456,789012`

## config.json 的設定值

這些都不是密鑰，是「換一個人用就要換」的值。

| 欄位 | 意思 |
| --- | --- |
| `channel_id` | 要監控的 YouTube 頻道 ID，UC 開頭 |
| `channel_url` | 頻道網址，例如 `https://www.youtube.com/@你的頻道代號` |
| `display_name` | 通知卡片上顯示的頻道全名 |
| `short_name` | 通知標題用的簡稱 |
| `bot_label` | 通知卡片頁尾顯示的機器人名稱 |
| `owner_user_id` | 開台通知要 tag 的主播 Discord user ID |
| `mention_role_ids` | 開台通知要 tag 的身分組 ID，可放多個，不需要就留空陣列 |
| `fan_channel_id` | 粉絲直播提醒頻道的 channel ID |
| `admin_channel_id` | 只有管理者看得到的管理頻道 channel ID |
| `reaction_emoji` | 發完通知要加的自訂 emoji，格式 `名稱:ID`，不需要就留空字串 |
| `admin_user_ids` | 按 👍 才算數的管理者 Discord user ID，可放多個 |

## 怎麼啟動

最簡單的方式：在程式資料夾的空白處按住 Shift 再按滑鼠右鍵，選「在這裡開啟 PowerShell 視窗」，輸入下面這行按 Enter。

```
python check_live.py
```

視窗會停在那裡沒反應，這是正常的，代表它正在盯著。這個視窗不能關，關掉程式就停了。

想讓它開機自動跑、而且不要一直有個視窗擋在桌面，改成輸入這行。

```
powershell -ExecutionPolicy Bypass -File setup_task.ps1
```

中間那段 `-ExecutionPolicy Bypass` 不能省略，Windows 預設會擋掉從網路下載回來的腳本。跑完之後程式會在背景執行，每次登入電腦都會自動啟動，不會有黑色視窗跳出來，也不需要系統管理員權限。

想確認它有沒有在做事，打開資料夾裡的 `check_live.log`，最底下會一直長出新的紀錄，每小時至少會有一行「存活」。如果最後一行的時間停在幾小時前，代表程式停了或電腦睡著了。

## 遇到狀況的時候

**沒收到開台通知。** 先看 `check_live.log` 最後一行的時間。如果停在幾小時前，就是電腦睡著或程式被關掉了，重新啟動一次。如果時間是剛剛，那就打開檔案往回找有沒有「本輪失敗」的字樣，那是網路連不上，通常會自己恢復。

**按了 👍 但沒發出去。** 確認 config.json 的 `admin_user_ids`（或 `.env` 的 `ADMIN_USER_IDS`）是不是你自己的 ID，還有機器人有沒有被邀進那個伺服器、看不看得到那個頻道。程式只認名單裡的人按的讚，別人按的不算。

**想換成別的頻道。** 改 config.json 就好，不用動程式碼。

## 給工程師的部分

程式只用 Python 標準庫，沒有任何第三方套件需要安裝。所有跟特定頻道／伺服器綁定的值都在 `config.json`，換頻道或換伺服器不需要改程式碼；密鑰在 `.env`，兩個檔都不進版控。

執行機制是每 60 秒抓一次頻道 RSS feed（零 API 配額），feed 有新條目才打 `videos.list`（1 unit）判斷 `liveBroadcastContent`。待機室進追蹤清單，接近預定開播時間改為每分鐘查。`state.json` 記錄已通知過的影片 ID 和待確認事項，換機器時一併複製過去就不會重複通知。

Linux 上長期運行建議寫成 systemd unit 設 `Restart=always`，或用 Docker 加 `restart: unless-stopped`，程式崩潰或主機重開都會自動拉回來。
