#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import sys
import time
import json
import shutil
import os
import subprocess
import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm, IntPrompt, FloatPrompt
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich import box

# --- تنظیمات ---
DEFAULT_DB_PATH = "/etc/x-ui/x-ui.db"
console = Console()

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    console.print(Panel(
        "[bold cyan]X-UI Bulk Smart Manager[/bold cyan]",
        subtitle="[dim]مدیریت هوشمند کاربران[/dim]",
        border_style="green",
        padding=(0, 2)
    ))

def get_protocol_icon(protocol):
    icons = {
        "vmess": "🟣", "vless": "🔵", "trojan": "🟢", 
        "shadowsocks": "🟠", "dokodemo-door": "🚪", "socks": "🧦", "http": "🌐"
    }
    return icons.get(protocol, "📡")

def find_database():
    if os.path.exists(DEFAULT_DB_PATH): return DEFAULT_DB_PATH
    files = [f for f in os.listdir('.') if f.endswith('.db')]
    if not files:
        console.print("[bold red]❌ دیتابیس یافت نشد ![/bold red]")
        sys.exit(1)
    if len(files) == 1: return files[0]
    
    console.print(f"[yellow]چند فایل پیدا شد. لطفا انتخاب کنید :[/yellow]")
    for i, f in enumerate(files):
        console.print(f"[{i+1}] {f}")
    choice = IntPrompt.ask("شماره فایل", choices=[str(i+1) for i in range(len(files))])
    return files[choice-1]

def create_backup(db_path):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup_{timestamp}"
    try:
        shutil.copy(db_path, backup_path)
        console.print(f"[green]✔ بکاپ گرفته شد :[/green] [dim]{backup_path}[/dim]")
    except Exception as e:
        console.print(f"[bold red]❌ خطا در بکاپ : {e}[/bold red]"); sys.exit(1)

def restart_panel():
    if Confirm.ask("\n[bold yellow]🔄 آیا پنل ریستارت شود؟[/bold yellow]"):
        try:
            with console.status("[bold green]در حال ریستارت سرویس...[/bold green]"):
                cmd = "x-ui restart"
                if shutil.which("x-ui") is None: cmd = "systemctl restart x-ui"
                subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            console.print("[bold green]✔ انجام شد.[/bold green]")
        except Exception as e: console.print(f"[bold red]❌ خطا: {e}[/bold red]")

def get_real_usage_map(cursor):
    usage = {}
    try:
        cursor.execute("SELECT email, up, down FROM client_traffics")
        for row in cursor.fetchall():
            if row['email']: usage[row['email']] = row['up'] + row['down']
    except: pass
    return usage

def timestamp_to_date(ts):
    if ts <= 0: return "نامحدود"
    return datetime.datetime.fromtimestamp(ts/1000).strftime('%Y-%m-%d')

def bytes_to_gb(b):
    if b <= 0: return 0
    return round(b / (1024**3), 2)

def select_client_interactive(clients, real_usage):
    while True:
        console.print(Panel("اینتر بزنید تا همه نمایش داده شوند یا جستجو کنید", title="جستجو", border_style="blue"))
        search_query = Prompt.ask("جستجو").strip().lower()
        
        filtered = []
        for idx, c in enumerate(clients):
            email = c.get('email', '')
            if search_query in email.lower(): filtered.append((idx, c))
        
        if not filtered:
            console.print("[red]یافت نشد.[/red]"); continue

        # ساخت جدول ساده
        table = Table(show_header=True, header_style="bold magenta", box=box.SIMPLE)
        table.add_column("#", justify="center", width=4)
        table.add_column("ایمیل", justify="left", style="white")
        table.add_column("انقضا", justify="center", style="yellow")
        table.add_column("حجم", justify="right", style="green")
        table.add_column("وضعیت", justify="center")

        for local_idx, (real_idx, c) in enumerate(filtered):
            email = c.get('email', 'no-email')
            exp = timestamp_to_date(c.get('expiryTime', 0))
            u_val = real_usage.get(email, 0)
            t_val = c.get('totalGB', c.get('total', 0))
            usage_str = f"{bytes_to_gb(u_val)}/{'∞' if t_val<=0 else bytes_to_gb(t_val)}"
            status = "🟢" if c.get('enable') else "🔴"
            
            table.add_row(str(local_idx+1), email, exp, usage_str, status)

        console.print(table)
        console.print(f"[dim]تعداد نتایج: {len(filtered)}[/dim]")

        choice = IntPrompt.ask("\nشماره ردیف (0 بازگشت)", default=0)
        if choice == 0: return None
        if 1 <= choice <= len(filtered): return filtered[choice-1][1]
        else: console.print("[red]شماره نامعتبر[/red]")

def process_single_user_menu(client, usage_map):
    email = client['email']
    used = usage_map.get(email, 0)
    total = client.get('totalGB', client.get('total', 0))
    expiry = client.get('expiryTime', 0)
    enable = client.get('enable', False)
    
    status_icon = "🟢 فعال" if enable else "🔴 غیرفعال"
    
    console.print(Panel(
        f"📧 {email}\n"
        f"📊 {status_icon} | 📅 {timestamp_to_date(expiry)}\n"
        f"💾 {bytes_to_gb(used)} / {'∞' if total<=0 else bytes_to_gb(total)} GB",
        title="مشخصات کاربر", border_style="blue"
    ))

    console.print("[1] تمدید زمان (+روز)")
    console.print("[2] احیا کردن (شروع از الان)")
    console.print("[3] افزایش حجم (+GB)")
    console.print("[4] ریست مصرف")
    console.print("[5] تنظیم دستی")
    console.print("[0] بازگشت")

    action = IntPrompt.ask("انتخاب", choices=["0", "1", "2", "3", "4", "5"], default=0)
    if action == 0: return None
    updates = {} 

    if action == 1:
        days = IntPrompt.ask("تعداد روز تمدید")
        if days > 0:
            current_time = int(time.time() * 1000)
            base = max(current_time, expiry) if expiry > 0 else current_time
            updates['expiryTime'] = base + (days * 86400000)
    elif action == 2:
        days = IntPrompt.ask("روز اعتبار (از الان)")
        if days > 0: updates['expiryTime'] = int(time.time() * 1000) + (days * 86400000)
    elif action == 3:
        gb = FloatPrompt.ask("گیگابایت افزودنی")
        if gb > 0:
            updates['totalGB'] = total + int(gb * 1073741824)
            updates['total'] = updates['totalGB']
    elif action == 4:
        if Confirm.ask("مطمئنید؟"): updates['RESET_USAGE'] = True
    elif action == 5:
        new_days = IntPrompt.ask("روز اعتبار (0=نامحدود)", default=-1)
        if new_days >= 0: updates['expiryTime'] = 0 if new_days==0 else int(time.time()*1000) + (new_days*86400000)
        new_gb = FloatPrompt.ask("حجم کل (0=نامحدود)", default=-1.0)
        if new_gb >= 0:
            updates['totalGB'] = int(new_gb * 1073741824)
            updates['total'] = updates['totalGB']
    return updates

def main():
    clear_screen()
    print_header()
    db_file = find_database()
    create_backup(db_file)
    
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    real_usage = get_real_usage_map(cursor)

    try:
        cursor.execute("SELECT id, remark, port, protocol, settings FROM inbounds")
        inbounds = cursor.fetchall()
    except Exception as e:
        console.print(f"[red]خطا: {e}[/red]"); sys.exit(1)

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("کد", justify="center", style="bold yellow")
    table.add_column("نام اینباند", justify="right", style="white")
    table.add_column("جزئیات", justify="right", style="green")

    table.add_row("0", "خروج", "---")
    table.add_row("1", "همه اینباندها", "کل سرور")
    table.add_section()

    menu_map = {} 
    for idx, row in enumerate(inbounds):
        menu_idx = idx + 2
        try:
            client_count = len(json.loads(row['settings']).get('clients', []))
        except: client_count = 0
        
        icon = get_protocol_icon(row['protocol'])
        
        remark_str = f"{icon} {row['remark']}"
        detail_str = f"Port: {row['port']} | {client_count} User"
        
        table.add_row(str(menu_idx), remark_str, detail_str)
        menu_map[menu_idx] = row['id']
        
    console.print(Panel(table, title="منوی اصلی", border_style="cyan"))
    
    valid_choices = ["0", "1"] + [str(k) for k in menu_map.keys()]
    main_choice = IntPrompt.ask("گزینه مورد نظر", choices=valid_choices, default=0)
    
    if main_choice == 0: sys.exit(0)
    
    target_inbound_id = 0
    target_email = None
    
    if main_choice > 1:
        target_inbound_id = menu_map[main_choice]
        console.print(f"\n[bold green]--- مدیریت اینباند {target_inbound_id} ---[/bold green]")
        console.print("[1] اعمال گروهی (همه کاربران)")
        console.print("[2] انتخاب کاربر خاص")
        console.print("[0] بازگشت")
        
        sub_choice = IntPrompt.ask("انتخاب", choices=["0", "1", "2"], default=0)
        if sub_choice == 0: main(); return
        elif sub_choice == 2:
            target_row = next((r for r in inbounds if r['id'] == target_inbound_id), None)
            clients = json.loads(target_row['settings']).get('clients', [])
            selected_client = select_client_interactive(clients, real_usage)
            if not selected_client: main(); return
            target_email = selected_client['email']

    bulk_updates = {} 
    if target_email:
        final_client = None
        for row in inbounds:
            if target_inbound_id != 0 and row['id'] != target_inbound_id: continue
            cs = json.loads(row['settings']).get('clients', [])
            found = next((c for c in cs if c['email'] == target_email), None)
            if found: final_client = found; break
        if final_client:
            bulk_updates = process_single_user_menu(final_client, real_usage)
            if not bulk_updates: main(); return
        else: console.print("[red]کلاینت گم شد![/red]"); sys.exit(1)
    else:
        console.print(Panel("تنظیمات گروهی (Bulk Actions)", border_style="cyan"))
        
        console.print("[bold yellow]🕒 سناریو زمان :[/bold yellow]")
        console.print("[0] بدون تغییر")
        console.print("[1] همه")
        console.print("[2] فقط تمدید فعال‌ها")
        console.print("[3] فقط احیای منقضی‌ها")
        time_scenario = IntPrompt.ask("انتخاب", choices=["0", "1", "2", "3"], default=0)
        days_to_add = IntPrompt.ask(" >> تعداد روز", default=30) if time_scenario != 0 else 0

        console.print("\n[bold yellow]💾 سناریو حجم :[/bold yellow]")
        console.print("[0] بدون تغییر")
        console.print("[1] همه")
        console.print("[2] فقط تمام شده‌ها")
        console.print("[3] فقط حجم‌دارها")
        traffic_scenario = IntPrompt.ask("انتخاب", choices=["0", "1", "2", "3"], default=0)
        gb_to_add = FloatPrompt.ask(" >> مقدار GB", default=0.0) if traffic_scenario != 0 else 0

    ms_to_add = days_to_add * 86400000
    bytes_to_add = int(gb_to_add * 1073741824)
    current_time = int(time.time() * 1000)

    inbound_json_updates = {}
    sql_updates = []
    reset_usage_list = []
    stats = {'processed': 0, 'enabled': 0}

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn()) as progress:
        task = progress.add_task("پردازش...", total=len(inbounds))
        for row in inbounds:
            if target_inbound_id != 0 and row['id'] != target_inbound_id:
                progress.advance(task); continue
            try:
                settings = json.loads(row['settings'])
                clients = settings.get('clients', [])
                modified = False
                for client in clients:
                    email = client.get('email')
                    if not email or (target_email and email != target_email): continue

                    if target_email and bulk_updates:
                        if 'expiryTime' in bulk_updates: client['expiryTime'] = bulk_updates['expiryTime']; modified = True
                        if 'totalGB' in bulk_updates: 
                            client['totalGB'] = bulk_updates['totalGB']
                            client['total'] = bulk_updates['totalGB']; modified = True
                        if 'RESET_USAGE' in bulk_updates: reset_usage_list.append(email)
                    elif not target_email:
                        expiry = client.get('expiryTime', 0)
                        is_expired = 0 < expiry < current_time
                        total = client.get('totalGB', client.get('total', 0))
                        used = real_usage.get(email, 0)
                        is_depleted = total > 0 and used >= total
                        
                        if time_scenario == 1 or (time_scenario == 2 and not is_expired) or (time_scenario == 3 and is_expired):
                            base = current_time if (is_expired and time_scenario != 2) else expiry
                            client['expiryTime'] = (base if base > 0 else current_time) + ms_to_add
                            modified = True
                        if traffic_scenario == 1 or (traffic_scenario == 2 and is_depleted) or (traffic_scenario == 3 and not is_depleted):
                            if total > 0:
                                client['totalGB'] = total + bytes_to_add
                                client['total'] = client['totalGB']; modified = True

                    new_exp = client.get('expiryTime', 0)
                    new_tot = client.get('totalGB', client.get('total', 0))
                    curr_used = 0 if email in reset_usage_list else real_usage.get(email, 0)
                    
                    time_ok = (new_exp <= 0) or (new_exp > current_time)
                    traffic_ok = (new_tot <= 0) or (curr_used < new_tot)
                    
                    if time_ok and traffic_ok and not client.get('enable'):
                        client['enable'] = True
                        stats['enabled'] += 1; modified = True
                    
                    if modified or email in reset_usage_list:
                        sql_updates.append((client['expiryTime'], new_tot, 1 if client.get('enable') else 0, email))
                        stats['processed'] += 1
                if modified: inbound_json_updates[row['id']] = json.dumps(settings)
            except: pass
            progress.advance(task)

    if stats['processed'] == 0 and not reset_usage_list:
        console.print("[yellow]تغییری اعمال نشد.[/yellow]"); sys.exit(0)

    console.print(Panel(
        f"تغییرات : {stats['processed']} | فعال‌سازی : {stats['enabled']} | ریست مصرف : {len(reset_usage_list)}",
        title="گزارش", border_style="green"
    ))
    
    if Confirm.ask("ذخیره در دیتابیس ؟"):
        try:
            for iid, js in inbound_json_updates.items(): cursor.execute("UPDATE inbounds SET settings = ? WHERE id = ?", (js, iid))
            cursor.executemany("UPDATE client_traffics SET expiry_time=?, total=?, enable=? WHERE email=?", sql_updates)
            if reset_usage_list:
                placeholders = ','.join('?' for _ in reset_usage_list)
                cursor.execute(f"UPDATE client_traffics SET up=0, down=0 WHERE email IN ({placeholders})", reset_usage_list)
            conn.commit()
            console.print("[bold green]✔ موفق ![/bold green]")
            restart_panel()
        except Exception as e:
            console.print(f"[bold red]❌ خطا : {e}[/bold red]"); conn.rollback()
        finally: conn.close()

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: console.print("\n[yellow]خروج.[/yellow]")
