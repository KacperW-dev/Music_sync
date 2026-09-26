#!/usr/bin/env python3
"""
Music Folder Sync over SSH (SFTP)

Copies files whose relative paths do not already exist on the server by default.
Existing remote files can optionally be overwritten. Empty directories are not copied.

Install:
    python -m pip install paramiko

Run:
    python music_sync.py
"""
import errno
import json
import os
import posixpath
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

try:
    import paramiko
except ImportError:
    paramiko = None


class MusicSyncApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Music Folder Sync over SSH")
        self.root.geometry("780x650")
        self.events = queue.Queue()
        self.worker = None
        self.cancel_event = threading.Event()
        self.entry_widgets = []
        self.action_buttons = []

        self.local_var = tk.StringVar()
        self.host_var = tk.StringVar()
        self.port_var = tk.StringVar(value="22")
        self.user_var = tk.StringVar()
        self.remote_var = tk.StringVar(value="/home/username/Music")
        self.key_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.auth_var = tk.StringVar(value="key")
        self.dark_mode = tk.BooleanVar(value=False)
        self.overwrite_var = tk.BooleanVar(value=False)

        self.settings_path = Path(os.environ.get("APPDATA", Path.home())) / "MusicSync" / "settings.json"
        self._load_settings()
        self._build_ui()
        self._apply_theme()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(100, self._poll_events)

    def _load_settings(self):
        try:
            with self.settings_path.open("r", encoding="utf-8") as settings_file:
                settings = json.load(settings_file)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return

        self.local_var.set(settings.get("local", ""))
        self.host_var.set(settings.get("host", ""))
        self.port_var.set(settings.get("port", "22"))
        self.user_var.set(settings.get("username", ""))
        self.remote_var.set(settings.get("remote", "/home/username/Music"))
        self.key_var.set(settings.get("key", ""))
        self.auth_var.set(settings.get("auth", "key"))
        self.dark_mode.set(settings.get("dark_mode", False))
        self.overwrite_var.set(settings.get("overwrite", False))

    def _save_settings(self):
        settings = {
            "local": self.local_var.get(),
            "host": self.host_var.get(),
            "port": self.port_var.get(),
            "username": self.user_var.get(),
            "remote": self.remote_var.get(),
            "key": self.key_var.get(),
            "auth": self.auth_var.get(),
            "dark_mode": self.dark_mode.get(),
            "overwrite": self.overwrite_var.get(),
        }
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            with self.settings_path.open("w", encoding="utf-8") as settings_file:
                json.dump(settings, settings_file, indent=2)
        except OSError:
            pass

    def _close(self):
        self._save_settings()
        self.root.destroy()

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(7, weight=1)

        def field(row, label, variable, browse=None, show=None):
            ttk.Label(outer, text=label).grid(row=row, column=0, sticky="w", pady=5)
            ent = tk.Entry(outer, textvariable=variable, show=show, relief="flat", borderwidth=0)
            ent.grid(row=row, column=1, sticky="ew", padx=(10, 8), pady=5)
            self.entry_widgets.append(ent)
            if browse:
                ttk.Button(outer, text="Browse…", command=browse).grid(
                    row=row, column=2, pady=5
                )
            return ent

        field(0, "Local music folder", self.local_var, self._choose_folder)
        field(1, "Server IP / hostname", self.host_var)
        field(2, "SSH port", self.port_var)
        field(3, "SSH username", self.user_var)
        field(4, "Remote destination", self.remote_var)
        field(5, "SSH private key (optional)", self.key_var, self._choose_key)

        auth_frame = ttk.Frame(outer)
        auth_frame.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(4, 8))
        ttk.Label(auth_frame, text="Authentication:").pack(side="left")
        ttk.Radiobutton(auth_frame, text="SSH key / agent", variable=self.auth_var,
                        value="key", command=self._toggle_auth).pack(side="left", padx=8)
        ttk.Radiobutton(auth_frame, text="Password", variable=self.auth_var,
                        value="password", command=self._toggle_auth).pack(side="left")
        self.password_entry = tk.Entry(
            auth_frame, textvariable=self.password_var, show="•", relief="flat", borderwidth=0
        )
        self.password_entry.pack(side="left", fill="x", expand=True, padx=8)
        self.entry_widgets.append(self.password_entry)
        self.password_entry.configure(state="disabled")

        buttons = ttk.Frame(outer)
        buttons.grid(row=7, column=0, columnspan=3, sticky="new", pady=(4, 8))
        self.start_btn = tk.Button(buttons, text="Compare and sync", command=self.start_sync,
                                   relief="flat", borderwidth=0, padx=12, pady=6)
        self.start_btn.pack(side="left")
        self.cancel_btn = tk.Button(buttons, text="Cancel", command=self.cancel,
                                    state="disabled", relief="flat", borderwidth=0,
                                    padx=12, pady=6)
        self.cancel_btn.pack(side="left", padx=8)
        self.action_buttons.extend((self.start_btn, self.cancel_btn))
        ttk.Checkbutton(
            buttons, text="Dark mode", variable=self.dark_mode,
            command=self._toggle_theme
        ).pack(side="left", padx=8)

        ttk.Checkbutton(
            buttons, text="Overwrite existing files", variable=self.overwrite_var,
            command=self._toggle_overwrite
        ).pack(side="left", padx=8)

        self.overwrite_banner = tk.Label(
            outer,
            text="WARNING: Overwrite is enabled. Existing remote files will be replaced.",
            background="#b00020", foreground="#ffffff", font=("TkDefaultFont", 10, "bold"),
            padx=8, pady=6
        )
        self.overwrite_banner.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(0, 5))
        self._toggle_overwrite()

        self.status_var = tk.StringVar(value="Choose a folder and enter your SSH details.")
        ttk.Label(outer, textvariable=self.status_var).grid(
            row=9, column=0, columnspan=3, sticky="w", pady=(4, 4)
        )
        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=100)
        self.progress.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        self.detail_var = tk.StringVar(value="Waiting to start.")
        ttk.Label(outer, textvariable=self.detail_var, wraplength=730).grid(
            row=11, column=0, columnspan=3, sticky="w"
        )

        ttk.Label(outer, text="Activity log").grid(
            row=12, column=0, columnspan=3, sticky="w", pady=(10, 3)
        )
        self.log = tk.Text(outer, height=13, wrap="word", state="disabled")
        self.log.grid(row=13, column=0, columnspan=3, sticky="nsew")
        outer.rowconfigure(13, weight=1)

    def _toggle_overwrite(self):
        if self.overwrite_var.get():
            self.overwrite_banner.grid()
        else:
            self.overwrite_banner.grid_remove()
        self._save_settings()

    def _apply_theme(self):
        style = ttk.Style(self.root)
        if self.dark_mode.get() and "clam" in style.theme_names():
            style.theme_use("clam")
        if self.dark_mode.get():
            colors = {
                "background": "#17191e",
                "field": "#303844",
                "foreground": "#ffffff",
                "muted": "#aeb8c4",
                "accent": "#4ea1ff",
                "select": "#315f70",
                "progress": "#f2b84b",
                "warm": "#e46b73",
            }
        else:
            colors = {
                "background": "#f0f0f0",
                "field": "#ffffff",
                "foreground": "#000000",
                "muted": "#555555",
                "accent": "#2474d8",
                "select": "#cce8ff",
                "progress": "#167c80",
                "warm": "#c9434e",
            }

        self.root.configure(background=colors["background"])
        style.configure("TFrame", background=colors["background"])
        style.configure("TLabel", background=colors["background"], foreground=colors["foreground"])
        style.configure("TButton", background=colors["field"], foreground=colors["foreground"])
        style.configure("TCheckbutton", background=colors["background"], foreground=colors["foreground"])
        style.configure("TRadiobutton", background=colors["background"], foreground=colors["foreground"])
        style.configure("TProgressbar", background=colors["progress"], troughcolor=colors["field"])
        style.map("TButton", background=[("active", colors["accent"])])
        style.map("TCheckbutton", background=[("active", colors["background"])])
        style.map("TRadiobutton", background=[("active", colors["background"])])
        for entry in self.entry_widgets:
            entry.configure(
                background=colors["field"], foreground=colors["foreground"],
                insertbackground=colors["accent"], selectbackground=colors["select"],
                selectforeground="#ffffff", disabledbackground=colors["field"],
                disabledforeground=colors["muted"]
            )
        self.start_btn.configure(
            background=colors["accent"], foreground="#101820",
            activebackground=colors["select"], activeforeground="#ffffff"
        )
        self.cancel_btn.configure(
            background=colors["warm"], foreground="#ffffff",
            activebackground=colors["select"], activeforeground="#ffffff"
        )
        self.log.configure(
            background=colors["field"], foreground=colors["foreground"],
            insertbackground=colors["foreground"], selectbackground=colors["select"]
        )

    def _toggle_theme(self):
        self._apply_theme()
        self._save_settings()

    def _toggle_auth(self):
        self.password_entry.configure(
            state="normal" if self.auth_var.get() == "password" else "disabled"
        )

    def _choose_folder(self):
        folder = filedialog.askdirectory(title="Select local music folder")
        if folder:
            self.local_var.set(folder)

    def _choose_key(self):
        filename = filedialog.askopenfilename(title="Select SSH private key")
        if filename:
            self.key_var.set(filename)

    def log_line(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def start_sync(self):
        if paramiko is None:
            messagebox.showerror(
                "Missing dependency",
                "Paramiko is not installed.\nRun: python -m pip install paramiko"
            )
            return
        local = Path(self.local_var.get()).expanduser()
        if not local.is_dir():
            messagebox.showerror("Invalid folder", "Please select an existing local folder.")
            return
        if not self.host_var.get().strip() or not self.user_var.get().strip():
            messagebox.showerror("Missing details", "Enter the server IP/hostname and username.")
            return
        try:
            port = int(self.port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError        
        except ValueError:
            messagebox.showerror("Invalid port", "SSH port must be a number from 1 to 65535.")
            return
        remote = self.remote_var.get().strip()
        if not remote:
            messagebox.showerror("Missing destination", "Enter a remote destination folder.")
            return

        self._save_settings()
        self.cancel_event.clear()
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.configure(value=0, maximum=100)
        self.status_var.set("Connecting and comparing folders…")
        self.detail_var.set("")
        self.log_line("Starting sync…")
        config = {
            "local": str(local),
            "host": self.host_var.get().strip(),
            "port": port,
            "username": self.user_var.get().strip(),
            "remote": remote,
            "key": self.key_var.get().strip(),
            "auth": self.auth_var.get(),
            "password": self.password_var.get(),
            "overwrite": self.overwrite_var.get(),
        }
        self.worker = threading.Thread(target=self._sync_worker, args=(config,), daemon=True)
        self.worker.start()

    def cancel(self):
        self.cancel_event.set()
        self.status_var.set("Cancellation requested…")

    @staticmethod
    def remote_mkdirs(sftp, remote_dir):
        remote_dir = posixpath.normpath(remote_dir)
        if remote_dir in (".", "/"):
            return
        current = "/" if remote_dir.startswith("/") else ""
        for part in remote_dir.strip("/").split("/"):
            if not part:
                continue
            current = posixpath.join(current, part) if current else part
            try:
                sftp.stat(current)
            except OSError as exc:
                if exc.errno != errno.ENOENT:
                    raise
                sftp.mkdir(current)

    @staticmethod
    def _format_sync_error(exc, phase, cfg):
        error_type = type(exc).__name__
        detail = str(exc).strip() or "No additional details were provided."

        if paramiko is not None and isinstance(exc, paramiko.AuthenticationException):
            auth_hint = (
                "Select Password and re-enter the account password."
                if cfg["auth"] == "password"
                else "Check the SSH username and private key/agent. If the server expects a password, select Password."
            )
            return f"SSH authentication failed for {cfg['username']}@{cfg['host']}. {auth_hint} Server detail: {detail}"
        if paramiko is not None and isinstance(exc, paramiko.BadHostKeyException):
            return (
                f"The SSH host key for {cfg['host']} changed from the key saved on this PC. "
                f"Verify the server fingerprint before updating known_hosts. Server detail: {detail}"
            )
        if paramiko is not None and isinstance(exc, paramiko.ssh_exception.MissingHostKeyException):
            return (
                f"The SSH host key for {cfg['host']} is not trusted on this PC. "
                f"Verify the fingerprint, then connect to this host once with Windows OpenSSH to save it. "
                f"Server detail: {detail}"
            )
        if isinstance(exc, socket.timeout):
            return (
                f"Timed out while {phase} at {cfg['host']}:{cfg['port']}. "
                "Check that the server is online, SSH is running, and the port is reachable. "
                f"Detail: {detail}"
            )
        if error_type == "NoValidConnectionsError" or isinstance(exc, ConnectionRefusedError):
            return (
                f"Could not open an SSH connection to {cfg['host']}:{cfg['port']}. "
                "Check the address, port, server SSH service, and firewall. "
                f"Detail: {detail}"
            )
        if isinstance(exc, PermissionError) or getattr(exc, "errno", None) in (errno.EACCES, errno.EPERM):
            return (
                f"Permission denied while {phase}. Check that the SSH account can access "
                f"'{cfg['remote']}' and create folders/files there. Detail: {detail}"
            )
        if getattr(exc, "errno", None) == errno.ENOENT:
            return (
                f"A required path was not found while {phase}. Check the local folder and remote "
                f"destination '{cfg['remote']}'. Detail: {detail}"
            )
        return f"Failed while {phase} ({error_type}): {detail}"

    def _sync_worker(self, cfg):
        ssh = None
        phase = "connecting to SSH"
        try:
            self.events.put(("log", f"Connecting to {cfg['username']}@{cfg['host']}:{cfg['port']}…"))
            ssh = paramiko.SSHClient()
            # Uses known_hosts when available; unknown hosts are prompted/accepted by policy below.
            ssh.load_system_host_keys()
            ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
            connect_args = {
                "hostname": cfg["host"],
                "port": cfg["port"],
                "username": cfg["username"],
                "timeout": 20,
                "look_for_keys": cfg["auth"] == "key",
                "allow_agent": cfg["auth"] == "key",
            }
            if cfg["key"]:
                connect_args["key_filename"] = cfg["key"]
            if cfg["auth"] == "password":
                connect_args["password"] = cfg["password"]
                connect_args["look_for_keys"] = False
                connect_args["allow_agent"] = False
            ssh.connect(**connect_args)
            phase = "opening the SFTP session"
            sftp = ssh.open_sftp()
            local_root = Path(cfg["local"])
            remote_root = cfg["remote"].rstrip("/") or "/"

            # Build remote relative-path set, recursively, without downloading file contents.
            self.events.put(("status", "Scanning remote folder…"))
            phase = f"checking remote destination '{remote_root}'"
            remote_files = set()
            try:
                sftp.stat(remote_root)
            except OSError as exc:
                if exc.errno != errno.ENOENT:
                    raise
                self.remote_mkdirs(sftp, remote_root)

            def walk_remote(path, rel=""):
                if self.cancel_event.is_set():
                    return
                try:
                    entries = sftp.listdir_attr(path)
                except IOError as exc:
                    raise OSError(f"Could not list remote folder '{path}': {exc}") from exc
                for entry in entries:
                    name = entry.filename
                    full = posixpath.join(path, name)
                    child_rel = posixpath.join(rel, name) if rel else name
                    import stat
                    if stat.S_ISDIR(entry.st_mode):
                        walk_remote(full, child_rel)
                    elif stat.S_ISREG(entry.st_mode):
                        remote_files.add(child_rel)

            phase = "scanning remote files"
            walk_remote(remote_root)

            self.events.put(("status", "Scanning local folder…"))
            phase = "scanning local files"
            local_files = []
            for root, dirs, files in os.walk(local_root):
                if self.cancel_event.is_set():
                    break
                for filename in files:
                    full = Path(root) / filename
                    rel = full.relative_to(local_root).as_posix()
                    try:
                        if full.is_file():
                            local_files.append((full, rel, full.stat().st_size))
                    except OSError as exc:
                        self.events.put(("log", f"Skipping {full}: {exc}"))

            pending = [
                (path, rel, size) for path, rel, size in local_files
                if cfg["overwrite"] or rel not in remote_files
            ]
            total = len(pending)
            total_bytes = sum(size for _, _, size in pending)
            self.events.put(("log", f"Local files: {len(local_files)} | Remote files: {len(remote_files)}"))
            action = "Files to copy/replace" if cfg["overwrite"] else "Files to copy"
            self.events.put(("log", f"{action}: {total} ({total_bytes / (1024**2):.1f} MiB)"))
            if total == 0:
                self.events.put(("progress", 100, "No local files found to copy."))
                self.events.put(("done", "No files to copy."))
                sftp.close()
                return

            copied_bytes = 0
            started = time.monotonic()
            for index, (local_path, rel, size) in enumerate(pending, start=1):
                if self.cancel_event.is_set():
                    break
                remote_path = posixpath.join(remote_root, rel)
                phase = f"creating remote folder for '{rel}'"
                self.remote_mkdirs(sftp, posixpath.dirname(remote_path))
                self.events.put(("detail", f"{index}/{total}: {rel}"))
                self.events.put(("log", f"{'Replacing' if cfg['overwrite'] else 'Copying'}: {rel}"))

                file_bytes = [0]
                def callback(transferred, file_total):
                    file_bytes[0] = transferred
                    current_bytes = copied_bytes + transferred
                    pct = min(100, int((current_bytes / total_bytes) * 100)) if total_bytes else 100
                    elapsed = max(time.monotonic() - started, 0.01)
                    speed = current_bytes / elapsed / (1024 * 1024)
                    self.events.put(("progress", pct,
                                    f"{index}/{total} files • {current_bytes / (1024**2):.1f}/{total_bytes / (1024**2):.1f} MiB • {speed:.2f} MiB/s"))

                phase = f"uploading '{rel}'"
                try:
                    mode = "wb" if cfg["overwrite"] else "x"
                    with open(local_path, "rb") as src, sftp.file(remote_path, mode) as dst:
                        while True:
                            if self.cancel_event.is_set():
                                break
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            dst.write(chunk)
                            callback(file_bytes[0] + len(chunk), size)
                            file_bytes[0] += len(chunk)
                except IOError as exc:
                    if cfg["overwrite"]:
                        raise
                    try:
                        sftp.stat(remote_path)
                        self.events.put(("log", f"Skipped (already exists): {rel}"))
                    except IOError:
                        raise exc
                copied_bytes += size
                pct = min(100, int((copied_bytes / total_bytes) * 100)) if total_bytes else 100
                elapsed = max(time.monotonic() - started, 0.01)
                speed = copied_bytes / elapsed / (1024 * 1024)
                self.events.put(("progress", pct,
                                f"{index}/{total} files • {copied_bytes / (1024**2):.1f}/{total_bytes / (1024**2):.1f} MiB • {speed:.2f} MiB/s"))

            sftp.close()
            if self.cancel_event.is_set():
                self.events.put(("done", "Sync cancelled. Files already copied were kept."))
            else:
                self.events.put(("progress", 100, f"Finished • {total} file(s) processed"))
                result = "replaced/copied" if cfg["overwrite"] else "new"
                self.events.put(("done", f"Sync complete. Processed {total} {result} file(s)."))
        except Exception as exc:
            self.events.put(("error", self._format_sync_error(exc, phase, cfg)))
        finally:
            if ssh:
                ssh.close()

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self.log_line(event[1])
                elif kind == "status":
                    self.status_var.set(event[1])
                elif kind == "detail":
                    self.detail_var.set(event[1])
                elif kind == "progress":
                    self.progress.configure(value=event[1])
                    self.status_var.set(event[2])
                elif kind == "done":
                    self.status_var.set(event[1])
                    self.start_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                    self.log_line(event[1])
                elif kind == "error":
                    self.status_var.set("Sync failed.")
                    self.log_line("ERROR: " + event[1])
                    self.start_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                    messagebox.showerror("Sync failed", event[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)


def main():
    root = tk.Tk()
    MusicSyncApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
