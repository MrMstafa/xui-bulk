#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import sys
import time
import json
import shutil
import os
import uuid
import subprocess
import datetime
import argparse
from pathlib import Path
from typing import Optional

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm, IntPrompt, FloatPrompt
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
    from rich import box
except ImportError:
    print("Installing rich...")
    os.system(f"{sys.executable} -m pip install rich --break-system-packages -q 2>/dev/null"
              f" || {sys.executable} -m pip install rich -q")
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm, IntPrompt, FloatPrompt
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
    from rich import box

console = Console()
DEFAULT_DB_PATH = "/etc/x-ui/x-ui.db"

def manage_xui_service(action: str):
    try:
        cmd = f"x-ui {action}" if shutil.which("x-ui") else f"systemctl {action} x-ui"
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def bytes_to_gb(b) -> float:
    if not b or b <= 0:
        return 0.0
    return round(b / (1024 ** 3), 2)

def gb_to_bytes(gb: float) -> int:
    if not gb:
        return 0
    return int(gb * (1024 ** 3))

def ms_to_date(ms) -> str:
    if not ms or ms <= 0:
        return "Unlimited"
    try:
        return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")
    except Exception:
        return "Invalid"

def now_ms() -> int:
    return int(time.time() * 1000)

def days_from_now(days: int) -> int:
    return now_ms() + days * 86_400_000

def extend_ms(current_expiry: int, days: int) -> int:
    n = now_ms()
    base = current_expiry if (current_expiry > 0) else n
    if 0 < current_expiry < n and days > 0:
        base = n
        
    new_exp = base + (days * 86_400_000)
    if new_exp <= 0:
        return 1
    return new_exp

def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def find_database(explicit: Optional[str] = None) -> str:
    if explicit:
        if not os.path.exists(explicit):
            console.print(f"[bold red]DB not found : {explicit}[/bold red]")
            sys.exit(1)
        return explicit
    if os.path.exists(DEFAULT_DB_PATH):
        return DEFAULT_DB_PATH
    files = sorted(Path(".").glob("*.db"))
    if not files:
        console.print("[bold red]No database found. Provide --db path.[/bold red]")
        sys.exit(1)
    if len(files) == 1:
        return str(files[0])
    console.print("[yellow]Multiple .db files found :[/yellow]")
    for i, f in enumerate(files):
        console.print(f"  [{i+1}] {f}")
    c = IntPrompt.ask("Select", choices=[str(i+1) for i in range(len(files))])
    return str(files[c - 1])

def create_backup(db_path: str) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = f"{db_path}.bak_{ts}"
    try:
        shutil.copy2(db_path, dst)
        console.print(f"[green]Backup created :[/green] [dim]{dst}[/dim]")
        return dst
    except Exception as e:
        console.print(f"[bold red]Backup failed : {e}[/bold red]")
        sys.exit(1)

def load_inbounds(conn: sqlite3.Connection) -> list:
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_id, remark, port, protocol, enable,
               expiry_time, up, down, total,
               settings, stream_settings, tag, sniffing, listen, allocate
        FROM inbounds ORDER BY port
    """)
    result = []
    for row in cur.fetchall():
        d = dict(row)
        try:
            d["clients"] = json.loads(d["settings"]).get("clients", [])
        except Exception:
            d["clients"] = []
        result.append(d)
    return result

def load_traffic_map(conn: sqlite3.Connection) -> dict:
    cur = conn.cursor()
    cur.execute("""
        SELECT id, inbound_id, email, up, down, total, expiry_time, enable, reset
        FROM client_traffics
    """)
    result = {}
    for row in cur.fetchall():
        email = row["email"]
        if email:
            result[email] = dict(row)
    return result

def client_status(client: dict, traffic: dict) -> dict:
    n = now_ms()
    email        = client.get("email", "")
    total_bytes  = client.get("totalGB", 0) or 0
    expiry_ms    = client.get("expiryTime", 0) or 0
    json_enable  = bool(client.get("enable", False))

    ct           = traffic.get(email, {})
    up_bytes     = ct.get("up",   0) or 0
    down_bytes   = ct.get("down", 0) or 0
    used_bytes   = up_bytes + down_bytes

    is_expired   = 0 < expiry_ms < n
    is_depleted  = total_bytes > 0 and used_bytes >= total_bytes

    time_ok      = (expiry_ms <= 0) or (expiry_ms > n)
    traffic_ok   = (total_bytes <= 0) or (used_bytes < total_bytes)
    active       = json_enable and time_ok and traffic_ok

    remaining    = max(0, total_bytes - used_bytes) if total_bytes > 0 else -1

    return {
        "email":         email,
        "uuid":          client.get("id", ""),
        "total_bytes":   total_bytes,
        "used_bytes":    used_bytes,
        "remaining":     remaining,
        "expiry_ms":     expiry_ms,
        "json_enable":   json_enable,
        "is_expired":    is_expired,
        "is_depleted":   is_depleted,
        "time_ok":       time_ok,
        "traffic_ok":    traffic_ok,
        "active":        active,
    }

def recalc_enable(client: dict, traffic: dict, reset: bool = False, is_manually_disabled: bool = False) -> bool:
    if is_manually_disabled:
        return False
        
    n            = now_ms()
    total_bytes  = client.get("totalGB", 0) or 0
    expiry_ms    = client.get("expiryTime", 0) or 0
    ct           = traffic.get(client.get("email",""), {})
    used_bytes   = 0 if reset else ((ct.get("up",0) or 0) + (ct.get("down",0) or 0))
    time_ok      = (expiry_ms <= 0) or (expiry_ms > n)
    traffic_ok   = (total_bytes <= 0) or (used_bytes < total_bytes)
    return time_ok and traffic_ok

def commit_all(conn: sqlite3.Connection, db_path: str, inbound_updates: dict, ct_updates: list, ct_resets: list) -> None:
    is_live_db = (os.path.abspath(db_path) == os.path.abspath(DEFAULT_DB_PATH))
    if is_live_db:
        manage_xui_service("stop")

    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        for inbound_id, new_clients in inbound_updates.items():
            cur.execute("SELECT settings FROM inbounds WHERE id=?", (inbound_id,))
            row = cur.fetchone()
            if not row:
                continue
            try:
                settings = json.loads(row["settings"])
            except Exception:
                settings = {}
            settings["clients"] = new_clients
            cur.execute("UPDATE inbounds SET settings=? WHERE id=?",
                        (json.dumps(settings, ensure_ascii=False), inbound_id))

        for upd in ct_updates:
            email      = upd["email"]
            total      = upd["total"]
            expiry     = upd["expiry_time"]
            enable_int = 1 if upd["enable"] else 0
            cur.execute("""
                UPDATE client_traffics
                   SET total=?, expiry_time=?, enable=?
                 WHERE email=?
            """, (total, expiry, enable_int, email))

        if ct_resets:
            ph = ",".join("?" for _ in ct_resets)
            cur.execute(f"UPDATE client_traffics SET up=0, down=0 WHERE email IN ({ph})",
                        ct_resets)

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"DB write failed : {e}") from e
    finally:
        if is_live_db:
            manage_xui_service("start")

PROTO_ICON = {
    "vmess": "●", "vless": "◆", "trojan": "▲",
    "shadowsocks": "■", "socks": "◇", "http": "○"
}

def clear():
    os.system("clear" if os.name != "nt" else "cls")

def header(db_path: str):
    console.print(Panel(
        f"[bold cyan]X-UI Bulk Manager[/bold cyan]  [dim]{db_path}[/dim]",
        subtitle="[dim]Professional Edition - Fully Optimized[/dim]",
        border_style="cyan", padding=(0, 3)
    ))

def fmt_expiry(st: dict) -> str:
    if st["expiry_ms"] <= 0:
        return "Unlimited"
    n = now_ms()
    days_left = (st["expiry_ms"] - n) // 86_400_000
    date = ms_to_date(st["expiry_ms"])
    if st["is_expired"]:
        return f"[red]{date} (expired)[/red]"
    return f"{date} (+{days_left}d)"

def fmt_usage(st: dict) -> str:
    used  = bytes_to_gb(st["used_bytes"])
    total = bytes_to_gb(st["total_bytes"]) if st["total_bytes"] > 0 else "∞"
    return f"{used}/{total} GB"

def color_of(st: dict) -> str:
    if not st["json_enable"]:
        return "dim"
    if st["is_expired"] or st["is_depleted"]:
        return "red"
    return "green"

def print_clients_table(clients: list, traffic: dict, title: str = "Clients") -> list:
    statuses = [client_status(c, traffic) for c in clients]

    t = Table(box=box.SIMPLE_HEAVY, show_header=True,
              header_style="bold cyan", title=title)
    t.add_column("#",       justify="right",  width=4)
    t.add_column("Email",   justify="left",   min_width=22)
    t.add_column("Usage",   justify="right",  width=16)
    t.add_column("Expiry",  justify="center", width=24)
    t.add_column("OK",      justify="center", width=4)

    for i, st in enumerate(statuses):
        col  = color_of(st)
        icon = "●" if st["active"] else ("○" if st["json_enable"] else "✕")
        t.add_row(
            f"[{col}]{i+1}[/{col}]",
            f"[{col}]{st['email']}[/{col}]",
            f"[{col}]{fmt_usage(st)}[/{col}]",
            fmt_expiry(st),
            icon,
        )

    console.print(t)
    console.print(
        f"[dim]Total :{len(statuses)}  "
        f"Active :[green]{sum(1 for s in statuses if s['active'])}[/green]  "
        f"Expired :[red]{sum(1 for s in statuses if s['is_expired'])}[/red]  "
        f"Depleted :[red]{sum(1 for s in statuses if s['is_depleted'])}[/red][/dim]"
    )
    return statuses

def edit_single_client(client: dict, traffic: dict) -> Optional[dict]:
    st = client_status(client, traffic)
    is_manually_disabled = (not st["json_enable"]) and st["time_ok"] and st["traffic_ok"]
    
    console.print(Panel(
        f"[bold]Email :[/bold]  {st['email']}\n"
        f"[bold]Status :[/bold] {'Active' if st['active'] else 'Inactive'}"
        f"{'  (expired)' if st['is_expired'] else ''}"
        f"{'  (depleted)' if st['is_depleted'] else ''}\n"
        f"[bold]Usage :[/bold]  {fmt_usage(st)}\n"
        f"[bold]Expiry :[/bold] {fmt_expiry(st)}",
        title="Client", border_style="blue"
    ))

    console.print("[1] Extend/Reduce time (+/- days)")
    console.print("[2] Revive (fresh start from now)")
    console.print("[3] Add/Reduce traffic (+/- GB)")
    console.print("[4] Reset usage (zero up/down)")
    console.print("[5] Manual settings")
    console.print("[6] Toggle enable/disable")
    console.print("[0] Back")

    action = IntPrompt.ask("Action", choices=["0","1","2","3","4","5","6"], default=0)
    if action == 0:
        return None

    c    = dict(client)
    do_reset = False

    if action == 1:
        days = IntPrompt.ask("Days to add/subtract (e.g. 30 or -5)", default=30)
        if days != 0:
            if st["expiry_ms"] <= 0 and days < 0:
                console.print("[yellow][!] Warning : This user is Unlimited. Reducing days will expire them immediately.[/yellow]")
            c["expiryTime"] = extend_ms(st["expiry_ms"], days)

    elif action == 2:
        if st["is_depleted"]:
            console.print("[yellow][!] Warning : This user is also depleted (Out of GB). Reviving time alone won't enable them. Tip: Also use Action 3 or 4.[/yellow]")
        days = IntPrompt.ask("Valid for (days from now)", default=30)
        if days > 0:
            c["expiryTime"] = days_from_now(days)

    elif action == 3:
        gb = FloatPrompt.ask("GB to add/subtract (e.g. 10 or -2.5)", default=10.0)
        if gb != 0:
            new_total = st["total_bytes"] + gb_to_bytes(gb)
            c["totalGB"] = new_total if new_total > 0 else 1

    elif action == 4:
        if Confirm.ask("Zero up/down for this client ?", default=False):
            do_reset = True

    elif action == 5:
        console.print("[dim]Enter -1 or leave blank to skip a field.[/dim]")
        days_s = Prompt.ask("New validity days from now (0=unlimited)", default="skip")
        if days_s not in ("skip", "-1", ""):
            try:
                d = int(days_s)
                c["expiryTime"] = 0 if d == 0 else days_from_now(d)
            except ValueError:
                pass

        gb_s = Prompt.ask("New total traffic GB (0=unlimited)", default="skip")
        if gb_s not in ("skip", "-1", ""):
            try:
                g = float(gb_s)
                c["totalGB"] = 0 if g == 0 else gb_to_bytes(g)
            except ValueError:
                pass

        if Confirm.ask("Also reset usage?", default=False):
            do_reset = True

    elif action == 6:
        c["enable"] = not bool(client.get("enable", False))
        console.print(f"[yellow]Enable → {c['enable']}[/yellow]")
        is_manually_disabled = not c["enable"]

    if action != 6:
        c["enable"] = recalc_enable(c, traffic, reset=do_reset, is_manually_disabled=is_manually_disabled)

    c["_reset"] = do_reset
    return c

def bulk_process(clients: list, traffic: dict,time_mode: int, time_days: int,traffic_mode: int, traffic_gb: float,reset_mode: int) -> tuple:
    n          = now_ms()
    add_ms_val = time_days * 86_400_000
    add_bytes  = gb_to_bytes(traffic_gb)

    new_clients    = []
    emails_to_reset = []

    for client in clients:
        st = client_status(client, traffic)
        is_manually_disabled = (not st["json_enable"]) and st["time_ok"] and st["traffic_ok"]
        
        c  = dict(client)

        # Time
        if time_mode == 1:
            c["expiryTime"] = extend_ms(st["expiry_ms"], time_days)
        elif time_mode == 2 and not st["is_expired"]:
            if st["expiry_ms"] > 0:
                c["expiryTime"] = extend_ms(st["expiry_ms"], time_days)
        elif time_mode == 3 and st["is_expired"]:
            c["expiryTime"] = days_from_now(time_days)

        # Traffic
        if add_bytes != 0:
            if traffic_mode == 1 and st["total_bytes"] > 0:
                new_total = st["total_bytes"] + add_bytes
                c["totalGB"] = new_total if new_total > 0 else 1
            elif traffic_mode == 2 and st["is_depleted"]:
                new_total = st["total_bytes"] + add_bytes
                c["totalGB"] = new_total if new_total > 0 else 1
            elif traffic_mode == 3 and st["active"]:
                if st["total_bytes"] > 0:
                    new_total = st["total_bytes"] + add_bytes
                    c["totalGB"] = new_total if new_total > 0 else 1

        will_reset = (reset_mode == 1) or (reset_mode == 2 and st["is_depleted"])
        if will_reset:
            emails_to_reset.append(st["email"])

        c["enable"] = recalc_enable(c, traffic, reset=will_reset, is_manually_disabled=is_manually_disabled)

        new_clients.append(c)

    return new_clients, emails_to_reset

def merge_databases(source_paths: list, target_path: str) -> None:
    console.print(Panel(
        f"[bold]Merging {len(source_paths)} source(s) → target[/bold]\n"
        f"Target : [cyan]{target_path}[/cyan]\n"
        + "\n".join(f"Source {i+1}: [dim]{p}[/dim]" for i, p in enumerate(source_paths)),
        border_style="yellow", title="DB Merge"
    ))

    tgt_conn   = open_db(target_path)
    tgt_cur    = tgt_conn.cursor()
    tgt_ibs    = load_inbounds(tgt_conn)
    tgt_traffic = load_traffic_map(tgt_conn)
    tgt_by_port: dict = {ib["port"]: ib for ib in tgt_ibs}
    tgt_by_email: dict = {}
    for ib in tgt_ibs:
        for c in ib["clients"]:
            e = c.get("email", "")
            if e:
                tgt_by_email[e] = c

    all_uuids: set = {
        c.get("id", "")
        for ib in tgt_ibs
        for c in ib["clients"]
        if c.get("id")
    }

    stats = dict(sources=0, matched=0, skipped_port=0,
                 merged=0, inserted=0, skipped_email=0)

    for src_path in source_paths:
        if not os.path.exists(src_path):
            console.print(f"[red]  Source not found : {src_path}[/red]")
            continue

        console.print(f"\n[cyan]Source : {src_path}[/cyan]")
        src_conn    = open_db(src_path)
        src_ibs     = load_inbounds(src_conn)
        src_traffic = load_traffic_map(src_conn)
        stats["sources"] += 1

        for src_ib in src_ibs:
            port = src_ib["port"]
            if port not in tgt_by_port:
                console.print(f"  [yellow]Port {port} not in target — skip '{src_ib['remark']}'[/yellow]")
                stats["skipped_port"] += 1
                continue

            tgt_ib = tgt_by_port[port]
            stats["matched"] += 1
            console.print(f"  Port {port}: '{src_ib['remark']}' → '{tgt_ib['remark']}'  "
                          f"({len(src_ib['clients'])} clients)")

            for sc in src_ib["clients"]:
                email = sc.get("email", "")
                if not email:
                    stats["skipped_email"] += 1
                    continue

                s_ct    = src_traffic.get(email, {})
                s_up    = s_ct.get("up",    0) or 0
                s_down  = s_ct.get("down",  0) or 0
                s_total = sc.get("totalGB", 0) or 0
                s_exp   = sc.get("expiryTime", 0) or 0

                if email in tgt_by_email:
                    tc      = tgt_by_email[email]
                    t_ct    = tgt_traffic.get(email, {})
                    t_up    = t_ct.get("up",   0) or 0
                    t_down  = t_ct.get("down", 0) or 0
                    t_total = tc.get("totalGB", 0) or 0
                    t_exp   = tc.get("expiryTime", 0) or 0

                    merged_total = max(s_total, t_total)
                    merged_exp   = max(s_exp,   t_exp)
                    merged_up    = t_up   + s_up
                    merged_down  = t_down + s_down

                    tc["totalGB"]    = merged_total
                    tc["expiryTime"] = merged_exp
                    n = now_ms()
                    time_ok    = (merged_exp <= 0) or (merged_exp > n)
                    traffic_ok = (merged_total <= 0) or ((merged_up + merged_down) < merged_total)
                    tc["enable"] = time_ok and traffic_ok

                    tgt_traffic[email] = {
                        **(t_ct if t_ct else {}),
                        "up":          merged_up,
                        "down":        merged_down,
                        "total":       merged_total,
                        "expiry_time": merged_exp,
                        "enable":      1 if tc["enable"] else 0,
                    }
                    stats["merged"] += 1

                else:
                    nc = dict(sc)
                    src_uuid = nc.get("id", "")
                    if src_uuid in all_uuids:
                        new_uuid = str(uuid.uuid4())
                        nc["id"] = new_uuid
                        all_uuids.add(new_uuid)
                    else:
                        all_uuids.add(src_uuid)

                    n = now_ms()
                    time_ok    = (s_exp <= 0) or (s_exp > n)
                    traffic_ok = (s_total <= 0) or ((s_up + s_down) < s_total)
                    nc["enable"] = time_ok and traffic_ok

                    tgt_ib["clients"].append(nc)
                    tgt_by_email[email] = nc

                    tgt_traffic[email] = {
                        "inbound_id":  tgt_ib["id"],
                        "email":       email,
                        "up":          s_up,
                        "down":        s_down,
                        "total":       s_total,
                        "expiry_time": s_exp,
                        "enable":      1 if nc["enable"] else 0,
                        "reset":       0,
                        "_new":        True,
                    }
                    stats["inserted"] += 1

        src_conn.close()

    console.print(Panel(
        f"Sources processed : {stats['sources']}\n"
        f"Inbounds matched  : {stats['matched']}\n"
        f"Inbounds skipped  : {stats['skipped_port']}\n"
        f"Clients merged    : {stats['merged']}\n"
        f"Clients inserted  : {stats['inserted']}\n"
        f"Clients skipped   : {stats['skipped_email']}",
        title="Merge Summary", border_style="green"
    ))

    if not Confirm.ask("\nWrite merged data to target database ?", default=False):
        console.print("[yellow]Aborted. Nothing written.[/yellow]")
        tgt_conn.close()
        return

    is_live_db = (os.path.abspath(target_path) == os.path.abspath(DEFAULT_DB_PATH))
    if is_live_db:
        manage_xui_service("stop")

    try:
        tgt_cur.execute("BEGIN IMMEDIATE")
        for ib in tgt_ibs:
            tgt_cur.execute("SELECT settings FROM inbounds WHERE id=?", (ib["id"],))
            row = tgt_cur.fetchone()
            if not row:
                continue
            try:
                settings = json.loads(row["settings"])
            except Exception:
                settings = {}
            settings["clients"] = ib["clients"]
            tgt_cur.execute(
                "UPDATE inbounds SET settings=? WHERE id=?",
                (json.dumps(settings, ensure_ascii=False), ib["id"])
            )

        for email, ct in tgt_traffic.items():
            if ct.get("_new"):
                tgt_cur.execute("""
                    INSERT OR IGNORE INTO client_traffics
                        (inbound_id, enable, email, up, down, expiry_time, total, reset)
                    VALUES (?,?,?,?,?,?,?,0)
                """, (
                    ct["inbound_id"], ct["enable"], email,
                    ct.get("up", 0), ct.get("down", 0),
                    ct.get("expiry_time", 0), ct.get("total", 0)
                ))
            else:
                tgt_cur.execute("""
                    UPDATE client_traffics
                       SET up=?, down=?, total=?, expiry_time=?, enable=?
                     WHERE email=?
                """, (
                    ct.get("up", 0), ct.get("down", 0),
                    ct.get("total", 0), ct.get("expiry_time", 0),
                    ct.get("enable", 0), email
                ))

        tgt_conn.commit()
        console.print("[bold green]Merge written successfully (RAM Overwrite Protected).[/bold green]")
    except Exception as e:
        tgt_conn.rollback()
        console.print(f"[bold red]Merge write failed : {e}[/bold red]")
        raise
    finally:
        tgt_conn.close()
        if is_live_db:
            manage_xui_service("start")

def flow_single_client(inbound: dict, traffic: dict, conn: sqlite3.Connection, db_path: str) -> None:
    clients = inbound["clients"]
    if not clients:
        console.print("[yellow]No clients.[/yellow]")
        return

    while True:
        print_clients_table(clients, traffic, title=f"Inbound: {inbound['remark']}")
        console.print("[dim]0 = back[/dim]")
        choice = IntPrompt.ask("Client #", default=0)
        if choice == 0:
            return
        if not (1 <= choice <= len(clients)):
            console.print("[red]Invalid number.[/red]")
            continue

        client  = clients[choice - 1]
        updated = edit_single_client(client, traffic)
        if updated is None:
            continue

        do_reset = updated.pop("_reset", False)
        email    = updated.get("email", "")

        console.print(Panel(
            f"Email  : {email}\n"
            f"Total  : {bytes_to_gb(updated.get('totalGB',0))} GB\n"
            f"Expiry : {ms_to_date(updated.get('expiryTime',0))}\n"
            f"Enable : {updated.get('enable')}\n"
            f"Reset  : {do_reset}",
            title="Confirm", border_style="yellow"
        ))

        if not Confirm.ask("Save?", default=True):
            console.print("[yellow]Cancelled.[/yellow]")
            continue

        new_clients = [
            updated if c.get("email") == email else c
            for c in clients
        ]
        ct_upd = [{
            "email":       email,
            "total":       updated.get("totalGB", 0),
            "expiry_time": updated.get("expiryTime", 0),
            "enable":      updated.get("enable", False),
        }]

        try:
            commit_all(conn, db_path,
                       inbound_updates={inbound["id"]: new_clients},
                       ct_updates=ct_upd,
                       ct_resets=[email] if do_reset else [])

            inbound["clients"] = new_clients
            if do_reset and email in traffic:
                traffic[email]["up"]   = 0
                traffic[email]["down"] = 0
            console.print("[bold green]Saved.[/bold green]")
        except Exception as e:
            console.print(f"[bold red]{e}[/bold red]")

def flow_bulk(target_inbound: Optional[dict],
              all_inbounds: list,
              traffic: dict,
              conn: sqlite3.Connection,
              db_path: str) -> None:
    scope = f"Inbound: {target_inbound['remark']}" if target_inbound else "ALL Inbounds"
    console.print(Panel(f"[bold]Bulk — {scope}[/bold]", border_style="cyan"))

    console.print("\n[bold yellow]Time mode:[/bold yellow]")
    console.print("  [0] No change")
    console.print("  [1] Add/Subtract days for all (active : from current, expired : from now)")
    console.print("  [2] Add/Subtract active only")
    console.print("  [3] Revive expired only (from now)")
    time_mode = IntPrompt.ask("Select", choices=["0","1","2","3"], default=0)
    time_days = 0
    if time_mode:
        time_days = IntPrompt.ask("Days (+ to add, - to subtract)", default=30)

    console.print("\n[bold yellow]Traffic mode :[/bold yellow]")
    console.print("  [0] No change")
    console.print("  [1] Add/Subtract GB for all with quota")
    console.print("  [2] Add GB to depleted only")
    console.print("  [3] Add/Subtract GB to active non-depleted only")
    traffic_mode = IntPrompt.ask("Select", choices=["0","1","2","3"], default=0)
    traffic_gb = 0.0
    if traffic_mode:
        traffic_gb = FloatPrompt.ask("GB (+ to add, - to subtract)", default=10.0)

    console.print("\n[bold yellow]Usage reset :[/bold yellow]")
    console.print("  [0] No reset")
    console.print("  [1] Reset all")
    console.print("  [2] Reset depleted only")
    reset_mode = IntPrompt.ask("Select", choices=["0","1","2"], default=0)

    if not time_mode and not traffic_mode and not reset_mode:
        console.print("[yellow]Nothing to do.[/yellow]")
        return

    targets = [target_inbound] if target_inbound else all_inbounds
    total_c = sum(len(ib["clients"]) for ib in targets)
    console.print(f"\n[dim]Scope : {len(targets)} inbound(s), {total_c} clients.[/dim]")

    if not Confirm.ask("Continue?", default=False):
        return

    all_ib_updates: dict = {}
    all_ct_updates: list = []
    all_resets:     list = []

    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  BarColumn(), console=console) as prog:
        task = prog.add_task("Processing clients...", total=len(targets))
        for ib in targets:
            new_clients, resets = bulk_process(
                ib["clients"], traffic,
                time_mode, time_days,
                traffic_mode, traffic_gb,
                reset_mode
            )
            all_ib_updates[ib["id"]] = new_clients
            all_resets.extend(resets)
            for nc in new_clients:
                all_ct_updates.append({
                    "email":       nc.get("email", ""),
                    "total":       nc.get("totalGB", 0),
                    "expiry_time": nc.get("expiryTime", 0),
                    "enable":      nc.get("enable", False),
                })
            prog.advance(task)

    console.print(Panel(
        f"Clients to update : {len(all_ct_updates)}\n"
        f"Usage resets      : {len(all_resets)}",
        title="Preview", border_style="green"
    ))

    if not Confirm.ask("Save to database?", default=False):
        console.print("[yellow]Cancelled.[/yellow]")
        return

    try:
        commit_all(conn, db_path, all_ib_updates, all_ct_updates, all_resets)
        console.print("[bold green]Done. Changes written and applied automatically.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]{e}[/bold red]")

def flow_stats(all_inbounds: list, traffic: dict) -> None:
    total = active = expired = depleted = 0
    up_total = down_total = 0
    for ct in traffic.values():
        up_total   += ct.get("up",   0) or 0
        down_total += ct.get("down", 0) or 0

    for ib in all_inbounds:
        for c in ib["clients"]:
            total += 1
            st = client_status(c, traffic)
            if st["active"]:    active   += 1
            if st["is_expired"]:expired  += 1
            if st["is_depleted"]:depleted += 1

    t = Table(box=box.SIMPLE, show_header=False)
    t.add_column("K", style="bold cyan")
    t.add_column("V", style="white")
    t.add_row("Inbounds",       str(len(all_inbounds)))
    t.add_row("Total Clients",  str(total))
    t.add_row("Active",         f"[green]{active}[/green]")
    t.add_row("Expired",        f"[red]{expired}[/red]")
    t.add_row("Depleted",       f"[red]{depleted}[/red]")
    t.add_row("Upload Total",   f"{bytes_to_gb(up_total) :.1f} GB")
    t.add_row("Download Total", f"{bytes_to_gb(down_total) :.1f} GB")
    console.print(Panel(t, title="Statistics", border_style="cyan"))
    Prompt.ask("Press Enter to continue")

def flow_merge(db_path: str) -> None:
    console.print(Panel(
        "[bold]Database Merge Wizard[/bold]\n"
        f"[dim]Target : {db_path}[/dim]\n\n"
        "Inbounds are matched by [bold]PORT[/bold].\n"
        "Clients are matched by [bold]EMAIL[/bold].\n"
        "For duplicates : max(quota), max(expiry), sum(traffic).",
        border_style="magenta"
    ))

    sources = []
    while True:
        console.print(f"[dim]Sources so far : {len(sources)}[/dim]")
        p = Prompt.ask("Source DB path (blank to finish)").strip()
        if not p:
            break
        if not os.path.exists(p):
            console.print(f"[red]Not found : {p}[/red]")
        elif os.path.abspath(p) == os.path.abspath(db_path):
            console.print("[red]Target and source cannot be the same file.[/red]")
        else:
            sources.append(p)
            console.print(f"[green]Added.[/green]")

    if not sources:
        console.print("[yellow]No sources. Cancelled.[/yellow]")
        return

    create_backup(db_path)
    merge_databases(sources, db_path)

def main():
    parser = argparse.ArgumentParser(description="X-UI Bulk Manager")
    parser.add_argument("--db", help="Path to x-ui.db", default=None)
    parser.add_argument("--merge", nargs="+",
                        help="Non-interactive merge : --merge src1.db src2.db --db target.db")
    args = parser.parse_args()

    db_path = find_database(args.db)
    if args.merge:
        create_backup(db_path)
        merge_databases(args.merge, db_path)
        return

    while True:
        clear()
        conn        = open_db(db_path)
        all_inbounds = load_inbounds(conn)
        traffic     = load_traffic_map(conn)

        header(db_path)

        t = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")
        t.add_column("Key",     justify="center", width=5)
        t.add_column("Name",    justify="left",   min_width=22)
        t.add_column("Port",    justify="center", width=7)
        t.add_column("Clients", justify="center", width=8)
        t.add_column("Active",  justify="center", width=8)

        t.add_row("[yellow]S[/yellow]",  "Statistics",            "", "", "")
        t.add_row("[yellow]M[/yellow]",  "Merge databases",       "", "", "")
        t.add_row("[yellow]A[/yellow]",  "Bulk — ALL inbounds",  "", "", "")
        t.add_row("[yellow]0[/yellow]",  "Exit",                  "", "", "")
        t.add_section()

        menu_map = {}
        for idx, ib in enumerate(all_inbounds):
            key = str(idx + 1)
            menu_map[key] = ib
            icon = PROTO_ICON.get(ib["protocol"], "?")
            cnt  = len(ib["clients"])
            act  = sum(1 for c in ib["clients"]
                       if client_status(c, traffic)["active"])
            t.add_row(
                f"[yellow]{key}[/yellow]",
                f"{icon} {ib['remark']}",
                str(ib["port"]),
                str(cnt),
                f"[green]{act}[/green]",
            )

        console.print(t)
        choice = Prompt.ask("Select").strip().upper()

        if choice == "0":
            conn.close()
            console.print("[dim]Bye.[/dim]")
            break

        elif choice == "S":
            flow_stats(all_inbounds, traffic)
            conn.close()

        elif choice == "M":
            conn.close()
            flow_merge(db_path)

        elif choice == "A":
            create_backup(db_path)
            flow_bulk(None, all_inbounds, traffic, conn, db_path)
            conn.close()
            time.sleep(1)

        elif choice in menu_map:
            ib = menu_map[choice]
            console.print(f"\n[bold cyan]{ib['remark']}  (port {ib['port']})[/bold cyan]")
            console.print("[1] Manage single client")
            console.print("[2] Bulk operation (this inbound)")
            console.print("[0] Back")
            sub = IntPrompt.ask("Action", choices=["0","1","2"], default=0)

            if sub == 1:
                create_backup(db_path)
                flow_single_client(ib, traffic, conn, db_path)
            elif sub == 2:
                create_backup(db_path)
                flow_bulk(ib, all_inbounds, traffic, conn, db_path)
            
            conn.close()
            time.sleep(1)

        else:
            console.print("[red]Invalid. Try again.[/red]")
            time.sleep(1)
            conn.close()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
