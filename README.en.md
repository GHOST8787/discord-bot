[繁體中文](./README.md) | **English**

# YouTube Live Notification Bot

A small program that runs on your own computer. It keeps watching a YouTube channel, and when the channel goes live, opens a waiting room, or posts a new weekly stream schedule, it sends the news to Discord automatically.

## What it does

- **Live notification** — checks once a minute; when a stream is detected it posts the title, thumbnail and link to the fan live-alert channel, and mentions the streamer plus two roles
- **Waiting room asks you first** — when a waiting room appears it posts to the admin channel and asks you; it only announces to the fan channel after you react with 👍, otherwise it waits for the real start
- **Weekly schedule asks you first** — scans community posts every half hour; when a new schedule shows up it asks you first, posts to the fan schedule channel after your 👍, and never posts twice in the same week
- **Daily status report** — if nothing went live that day, it posts a short report to the admin channel after 8pm so you know the program is still alive

## Before you start

**A computer that never shuts down or falls asleep.** This matters more than anything else. The program only runs while the machine is awake, so a laptop with the lid closed is completely stopped, and any stream during that window is missed entirely. If you usually close your laptop when you are done, this program will miss streams on it. To have it really watch around the clock, either turn off sleep and lid-close hibernation, or put the program on a machine that stays on.

**Python.** This is the runtime. Download it from python.org; any version 3.9 or newer works. On the first page of the installer there is an **"Add python.exe to PATH"** checkbox at the bottom — **you must tick it**, otherwise the program will not be found later. Nothing else needs to be installed.

## Installation

**Step 1, download the files.** On the GitHub page press the green Code button, choose Download ZIP, and extract it wherever you like, for example under your Documents folder.

**Step 2, create the config files.** Hold Shift, right-click the empty space inside the program folder, choose "Open PowerShell window here", then paste these two lines and press Enter:

```
Copy-Item .env.example .env
Copy-Item config.example.json config.json
```

Two new files appear. `.env` holds the secrets, `config.json` holds the channel settings. Open both with Notepad and fill in the values. (Renaming files directly in Explorer sometimes gets blocked by Windows, so the commands above are the safer route.)

**Step 3, fill in the values.** Where to get each one is explained below.

## The six values in .env

**YT_API_KEY**

1. Go to console.cloud.google.com and sign in with a Google account
2. Create a new project
3. Search "YouTube Data API v3" in the top bar, open it and press Enable
4. Left menu "Credentials" → "Create credentials" → "API key"
5. Copy the string

**WEBHOOK_FAN, WEBHOOK_TEST, WEBHOOK_SCHEDULE**

1. Press the gear icon next to the Discord channel name (Edit Channel)
2. "Integrations" → "Webhooks" → "New Webhook"
3. Press "Copy Webhook URL"

Do this once in each of the three channels: FAN is the fan live-alert channel, TEST is the channel only admins can see, SCHEDULE is the fan weekly-schedule channel.

**DISCORD_TOKEN**

1. Go to discord.com/developers/applications, press New Application, any name will do
2. Click Bot on the left, press Reset Token, copy the string (this is a password, do not share it)
3. Click OAuth2 on the left, tick `bot` under SCOPES in the URL Generator
4. Tick View Channels and Read Message History under permissions
5. Paste the generated URL into a browser and add the bot to your server

Without this step the 👍 reaction does nothing and you only receive notifications.

**ADMIN_USER_IDS** (optional, overrides `admin_user_ids` in config.json)

1. Discord "User Settings" → "Advanced" → turn on Developer Mode
2. Back in chat, right-click your own avatar → "Copy User ID"
3. Paste it here; separate multiple people with commas: `123456,789012`

## The settings in config.json

None of these are secrets — they are the values that change when someone else uses the program.

| Field | Meaning |
| --- | --- |
| `channel_id` | The YouTube channel ID to watch, starts with UC |
| `channel_url` | The channel URL, e.g. `https://www.youtube.com/@your_handle` |
| `display_name` | Full channel name shown on the notification card |
| `short_name` | Short name used in notification titles |
| `bot_label` | Bot name shown in the card footer |
| `owner_user_id` | Discord user ID of the streamer, mentioned on live notifications |
| `mention_role_ids` | Role IDs to mention on live notifications; empty array for none |
| `fan_channel_id` | Channel ID of the fan live-alert channel |
| `admin_channel_id` | Channel ID of the admin-only channel |
| `reaction_emoji` | Custom emoji added after posting, format `name:id`; empty string for none |
| `admin_user_ids` | Discord user IDs whose 👍 counts as confirmation |

## How to start it

The simplest way: hold Shift, right-click the empty space in the program folder, choose "Open PowerShell window here", type the line below and press Enter.

```
python check_live.py
```

The window will just sit there doing nothing visible. That is normal — it means the program is watching. Do not close that window, closing it stops the program.

To have it start automatically at logon without a window sitting on your desktop, run this instead.

```
powershell -ExecutionPolicy Bypass -File setup_task.ps1
```

The `-ExecutionPolicy Bypass` part cannot be omitted; Windows blocks downloaded scripts by default. After it finishes the program runs in the background, starts automatically every time you log in, shows no black window, and needs no administrator rights.

To check that it is working, open `check_live.log` in the folder. New lines keep appearing at the bottom, with at least one "alive" line every hour. If the last line is hours old, the program stopped or the computer went to sleep.

## When something goes wrong

**No live notification arrived.** Look at the timestamp on the last line of `check_live.log` first. If it is hours old, the computer slept or the program was killed — start it again. If the timestamp is recent, search backwards in the file for "本輪失敗" (round failed); that is a network problem and usually recovers on its own.

**Pressed 👍 but nothing was posted.** Check that `admin_user_ids` in config.json (or `ADMIN_USER_IDS` in .env) really is your own ID, and that the bot was invited to that server and can see that channel. Only reactions from people on the list count.

**Want to watch a different channel.** Edit config.json — no code changes needed.

## For engineers

The program uses only the Python standard library, no third-party packages to install. Everything installation-specific lives in `config.json`, so switching channel or server never requires touching the code.

The mechanism: fetch the channel RSS feed every 60 seconds (zero API quota), and only call `videos.list` (1 unit) when the feed has a new entry, to read `liveBroadcastContent`. Waiting rooms go into a tracking list and switch to one API check per minute as the scheduled start approaches. `state.json` records which video IDs were already announced and what is pending confirmation; copy it along when moving to another machine and nothing gets announced twice.

For long-running use on Linux, write a systemd unit with `Restart=always`, or use Docker with `restart: unless-stopped`, so the daemon comes back after a crash or a host reboot.
