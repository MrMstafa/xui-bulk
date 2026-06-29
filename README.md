# 🚀 X-UI Bulk Manager

<div align="center">

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=flat-square)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Ubuntu-green?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-orange?style=flat-square)

**A professional CLI tool for bulk management of X-UI panel users**
**Supports single-client editing, bulk operations, and multi-database merging**

[![Telegram Channel](https://img.shields.io/badge/Telegram-Join%20Channel-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/Xray_Unknown)
[![GitHub stars](https://img.shields.io/github/stars/MrMstafa/xui-bulk?style=for-the-badge&logo=github&color=181717&labelColor=181717)](https://github.com/MrMstafa/xui-bulk)

</div>

---

> ⚠️ **Important:**
> This script must be run on the **same server** where your X-UI panel is installed, or pointed to a local copy of `x-ui.db`.
> A backup is created automatically before every write operation.

---

## ✨ Features

### 👤 Single Client Management
Edit any individual client with full control:

| Action | Description |
|--------|-------------|
| Extend time | Add days — active clients extend from current expiry; expired clients revive from now |
| Revive | Set a fresh expiry starting from now regardless of current state |
| Subtract time | Reduce expiry by N days (unlimited clients are not affected) |
| Add traffic | Add GB to quota (unlimited clients are not affected) |
| Subtract traffic | Reduce quota by GB (floored at 1 GB minimum, never set to 0) |
| Reset usage | Zero the up/down counters for this client |
| Manual | Set absolute values for expiry days and total GB directly |
| Toggle | Enable or disable client manually |

After every change, enable/disable is **automatically recomputed** based on actual state (time OK AND traffic OK).

---

### 📦 Bulk Operations
Apply changes to **all inbounds at once** or **a specific inbound**:

**Time modes:**
| Mode | Behavior |
|------|----------|
| Add to all | Active clients: extend from expiry. Expired clients: revive from now. |
| Add to active only | Only clients whose expiry has not passed yet |
| Revive expired only | Only clients who are currently expired |
| Subtract from all | Reduce expiry for all clients with a set quota (unlimited skipped) |
| Subtract from active only | Only reduce expiry for currently active clients |

**Traffic modes:**
| Mode | Behavior |
|------|----------|
| Add to all with quota | Only clients with a GB limit (unlimited skipped) |
| Add to depleted only | Clients who have used up their full quota |
| Add to active only | Clients who are active (not expired, not depleted) |
| Subtract from all with quota | Reduce quota (floor: 1 GB minimum) |
| Subtract from active only | Only reduce quota for currently active clients |

**Usage reset modes:**
| Mode | Behavior |
|------|----------|
| No reset | Leave up/down counters untouched |
| Reset all | Zero up/down for all clients in scope |
| Reset depleted only | Zero up/down only for clients who have run out of traffic |

All changes are applied in **one atomic database transaction** — either everything succeeds or nothing is written.

---

### 🔀 Database Merge
Merge 2 or 3 X-UI panel databases into one target database.

**Use case:** You run multiple panels on shared ports and want to consolidate them into one panel without losing any client data.

**How matching works:**

```
Inbounds → matched by: port + protocol + stream config (network, security, path)
Clients  → matched by: email (primary key across panels)
UUIDs    → deduplicated globally
```

**Merge rules for duplicate emails (same user, multi-panel):**

| Field | Rule |
|-------|------|
| Total GB quota | `max(source, target)` — keep the larger quota |
| Expiry time | `max(source, target)` — keep the later expiry |
| up + down usage | `sum(source + target)` — aggregate real usage |
| Enable state | Recomputed from merged values |

**Port conflict handling:**
If a source inbound has the same port+protocol as the target but a different stream config (e.g. different WebSocket path), it is created as a **new inbound on the next free port** with a `(srcN-conflict)` suffix in the remark. No data is lost.

**Email collision (different person, same email):**
If a source client has an email that already exists in the target but with a different UUID, the incoming email is renamed to `email_m1`, `email_m2`, etc.

**Before writing, a full dry-run simulation is shown** with expected counts so you can confirm before any data is touched.

**CLI usage (non-interactive):**
```bash
xui-bulk --merge /path/to/panel2.db /path/to/panel3.db --db /etc/x-ui/x-ui.db
```

---

### 📊 Statistics
Overview of the entire server:
- Total inbounds and clients
- Active / expired / depleted counts
- Total upload, download, and combined traffic across all clients

---

### 🛡️ Safety & Reliability

- **Atomic writes** — every operation uses `BEGIN IMMEDIATE … COMMIT`. On any error, a full rollback is performed and the database is left unchanged.
- **Both tables always synced** — `inbounds.settings` (JSON, source of truth for xray) and `client_traffics` (panel display cache) are always written together in the same transaction.
- **Auto backup** — a timestamped `.bak_YYYYMMDD_HHMMSS` file is created before every write. The 5 most recent backups are kept automatically.
- **WAL mode** — SQLite WAL journal mode is enabled for safe concurrent access.
- **No recursion** — the menu is a clean `while True` loop with no recursive calls.

---

## 📥 Installation

Run this command on your server (as root):

```bash
bash <(curl -Ls https://raw.githubusercontent.com/MrMstafa/xui-bulk/main/install.sh)
```

After the first install, simply type:
```bash
xui-bulk
```

To point at a specific database:
```bash
xui-bulk --db /path/to/x-ui.db
```

---

## 🖥️ Usage

```
X-UI Bulk Manager
─────────────────────────────────────────────
Key    Action
─────────────────────────────────────────────
 S     Statistics
 M     Merge databases
 A     Bulk — ALL inbounds
 D     Change active database
 0     Exit
─────────────────────────────────────────────
 1     [VLE] My Inbound         port:443   clients:120  active:98
 2     [TRO] Another Inbound    port:8443  clients:45   active:40
...
```

Selecting an inbound gives two options:
1. **Manage single client** — search, select, and edit one client
2. **Bulk operation** — apply time/traffic/reset rules to the entire inbound

---

## ⚙️ Requirements

- Python 3.8 or later
- `rich` library (installed automatically)
- Root access on the server

---

## ⚖️ Disclaimer

1. This script is open-source. Use it at your own risk.
2. The developer is not responsible for data loss, database corruption, or panel disruption.
3. Always keep an independent backup of your panel before running bulk operations.
4. The automatic backup built into this tool is a convenience feature, not a substitute for your own backup strategy.

---

<div align="center">
Made with ❤️ for the X-UI community
</div>
