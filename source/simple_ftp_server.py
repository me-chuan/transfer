#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A minimal FTP server implemented with raw TCP sockets.

This server is intentionally very small and only implements the subset of
FTP commands that the existing GUI client (using simple_ftp.FTPConnection)
needs:

- TCP control connection on a configurable port (default 2121)
- USER / PASS       : login
- PWD               : print working directory
- CWD               : change working directory
- MKD / RMD         : create / remove directory
- DELE              : delete file
- RNFR / RNTO       : rename
- TYPE I            : set binary mode (accepted but only one mode)
- PASV              : enter passive mode (server opens data port)
- LIST              : list directory over data connection
- RETR              : download file
- STOR              : upload file
- QUIT              : close session

It supports a very simple user database with per-user permissions
(read-only or read-write) and a per-server root directory.

This is for teaching and testing with your custom FTP client only.
DO NOT expose it to the Internet in production.
"""

from __future__ import annotations

import os
import socket
import threading
import traceback
from dataclasses import dataclass
from typing import Dict, Tuple, Optional


@dataclass
class UserInfo:
    password: str
    perm: str  # "r" or "rw"


@dataclass
class FTPConfig:
    host: str = "0.0.0.0"      # Listen on all interfaces
    port: int = 2121           # Control port (avoid 21 which may need root)
    root: str = os.path.abspath("./ftp_root")  # FTP root directory
    users: Dict[str, UserInfo] = None

    def __post_init__(self) -> None:
        if self.users is None:
            # Default: one read-write user and one read-only user
            self.users = {
                "user": UserInfo(password="123456", perm="rw"),
                "guest": UserInfo(password="guest", perm="r"),
            }
        # Ensure root exists
        os.makedirs(self.root, exist_ok=True)


class FTPSession:
    """Represents one FTP control connection (one client)."""

    def __init__(self, conn: socket.socket, addr: Tuple[str, int], config: FTPConfig) -> None:
        self.conn = conn
        self.addr = addr
        self.config = config

        self.control_file = conn.makefile("rwb")  # for readline/write
        self.logged_in = False
        self.username: Optional[str] = None
        self.cwd = "/"  # current working directory, relative to FTP root, always like '/subdir'
        self.type = "I"  # only support binary mode

        # Passive mode data listener (per command)
        self.pasv_listener: Optional[socket.socket] = None

    # ---------- Utility helpers ----------
    def _send_line(self, line: str) -> None:
        # All replies must end with CRLF
        data = (line + "\r\n").encode("utf-8")
        self.control_file.write(data)
        self.control_file.flush()

    def reply(self, code: int, text: str) -> None:
        self._send_line(f"{code} {text}")

    def read_command(self) -> Optional[str]:
        line = self.control_file.readline()
        if not line:
            return None
        return line.decode("utf-8", errors="ignore").rstrip("\r\n")

    def user_perm(self) -> str:
        if not self.logged_in or self.username is None:
            return ""
        info = self.config.users.get(self.username)
        return info.perm if info else ""

    def ensure_write_perm(self) -> bool:
        perm = self.user_perm()
        if "w" not in perm:
            self.reply(550, "Permission denied.")
            return False
        return True

    # Map FTP virtual path (starting with /) to real filesystem path
    def to_real_path(self, path: str) -> str:
        # Normalize: if path is relative, join with cwd
        if not path.startswith("/"):
            path = os.path.join(self.cwd, path)
        # Collapse .. and .
        norm = os.path.normpath(path)
        if not norm.startswith("/"):
            norm = "/" + norm
        real = os.path.abspath(os.path.join(self.config.root, norm.lstrip("/")))
        # Ensure we stay under root
        if not real.startswith(self.config.root):
            return self.config.root
        return real

    # ---------- Command handlers ----------
    def handle_USER(self, arg: str) -> None:
        if arg in self.config.users:
            self.username = arg
            self.reply(331, "User name okay, need password.")
        else:
            self.reply(530, "User not found.")

    def handle_PASS(self, arg: str) -> None:
        if self.username is None:
            self.reply(503, "Login with USER first.")
            return
        info = self.config.users.get(self.username)
        if info and info.password == arg:
            self.logged_in = True
            self.reply(230, "User logged in, proceed.")
        else:
            self.logged_in = False
            self.reply(530, "Login incorrect.")

    def handle_PWD(self) -> None:
        if not self.logged_in:
            self.reply(530, "Please login with USER and PASS.")
            return
        # Reply format: 257 "/" is current directory
        self.reply(257, f'"{self.cwd}" is current directory')

    def handle_CWD(self, arg: str) -> None:
        if not self.logged_in:
            self.reply(530, "Please login with USER and PASS.")
            return
        if not arg:
            arg = "/"
        new_real = self.to_real_path(arg)
        if os.path.isdir(new_real):
            # Convert back to virtual path rooted at '/'
            rel = os.path.relpath(new_real, self.config.root)
            self.cwd = "/" if rel == "." else "/" + rel.replace(os.sep, "/")
            self.reply(250, "Directory successfully changed.")
        else:
            self.reply(550, "Failed to change directory.")

    def handle_TYPE(self, arg: str) -> None:
        # We only support binary (I); accept A but ignore
        self.type = arg.upper() or "I"
        self.reply(200, f"Type set to {self.type}.")

    # ---- Passive mode ----
    def handle_PASV(self) -> None:
        # Close any previous listener
        if self.pasv_listener is not None:
            try:
                self.pasv_listener.close()
            except Exception:
                pass
            self.pasv_listener = None

        # Bind to an ephemeral port on the same host as control connection
        host = self.config.host if self.config.host != "0.0.0.0" else self.conn.getsockname()[0]
        self.pasv_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.pasv_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.pasv_listener.bind((host, 0))
        except Exception as e:
            print(f"[PASV] bind error on {host}: {e}")
            traceback.print_exc()
            self.reply(421, "Cannot open passive listener")
            return
        self.pasv_listener.listen(1)

        # Debug output
        port = self.pasv_listener.getsockname()[1]
        print(f"[PASV] listening on {host}:{port}")

        try:
            h1, h2, h3, h4 = host.split(".")
        except Exception:
            # fallback to control socket address
            host = self.conn.getsockname()[0]
            h1, h2, h3, h4 = host.split(".")
        p1 = port // 256
        p2 = port % 256
        self.reply(227, f"Entering Passive Mode ({h1},{h2},{h3},{h4},{p1},{p2}).")

    def accept_data_connection(self) -> Optional[socket.socket]:
        if self.pasv_listener is None:
            self.reply(425, "Use PASV first.")
            return None
        try:
            print("[PASV] waiting for data connection...")
            data_conn, peer = self.pasv_listener.accept()
            print(f"[PASV] data connection accepted from {peer}")
            return data_conn
        except Exception as e:
            print(f"[PASV] accept failed: {e}")
            traceback.print_exc()
            self.reply(425, "Can't open data connection.")
            return None
        finally:
            try:
                self.pasv_listener.close()
            except Exception:
                pass
            self.pasv_listener = None

    # ---- LIST ----
    def handle_LIST(self, arg: str) -> None:
        if not self.logged_in:
            self.reply(530, "Please login with USER and PASS.")
            return
        data_conn = self.accept_data_connection()
        if data_conn is None:
            return

        self.reply(150, "Here comes the directory listing.")
        real_dir = self.to_real_path(arg or self.cwd)
        try:
            entries = os.listdir(real_dir)
        except Exception as e:
            print(f"[LIST] os.listdir error for {real_dir}: {e}")
            traceback.print_exc()
            entries = []

        with data_conn:
            for name in entries:
                full = os.path.join(real_dir, name)
                try:
                    st = os.stat(full)
                    size = st.st_size
                    if os.path.isdir(full):
                        line = f"drwxr-xr-x 1 owner group 0 Jan 01 00:00 {name}\r\n"
                    else:
                        line = f"-rw-r--r-- 1 owner group {size} Jan 01 00:00 {name}\r\n"
                except Exception as e:
                    print(f"[LIST] stat error for {full}: {e}")
                    traceback.print_exc()
                    line = f"-rw-r--r-- 1 owner group 0 Jan 01 00:00 {name}\r\n"
                try:
                    data_conn.sendall(line.encode("utf-8"))
                except Exception as e:
                    print(f"[LIST] sendall error: {e}")
                    traceback.print_exc()
                    break

        self.reply(226, "Directory send OK.")

    # ---- RETR ----
    def handle_RETR(self, arg: str) -> None:
        if not self.logged_in:
            self.reply(530, "Please login with USER and PASS.")
            return
        real_path = self.to_real_path(arg)
        if not os.path.isfile(real_path):
            self.reply(550, "File not found.")
            return

        data_conn = self.accept_data_connection()
        if data_conn is None:
            return

        self.reply(150, "Opening binary mode data connection.")
        try:
            print(f"[RETR] sending file {real_path}")
            with data_conn, open(real_path, "rb") as f:
                while True:
                    buf = f.read(4096)
                    if not buf:
                        break
                    data_conn.sendall(buf)
            self.reply(226, "Transfer complete.")
        except Exception as e:
            print(f"[RETR] error transferring {real_path}: {e}")
            traceback.print_exc()
            self.reply(550, "Failed to read file.")

    # ---- STOR ----
    def handle_STOR(self, arg: str) -> None:
        if not self.logged_in:
            self.reply(530, "Please login with USER and PASS.")
            return
        if not self.ensure_write_perm():
            return
        real_path = self.to_real_path(arg)
        os.makedirs(os.path.dirname(real_path), exist_ok=True)

        data_conn = self.accept_data_connection()
        if data_conn is None:
            return

        self.reply(150, "Opening binary mode data connection for file upload.")
        try:
            print(f"[STOR] receiving file -> {real_path}")
            print(f"[STOR] write access to dir? {os.access(os.path.dirname(real_path), os.W_OK)}")
            with data_conn, open(real_path, "wb") as f:
                while True:
                    buf = data_conn.recv(4096)
                    if not buf:
                        break
                    f.write(buf)
            self.reply(226, "Transfer complete.")
        except Exception as e:
            print(f"[STOR] error storing {real_path}: {e}")
            traceback.print_exc()
            self.reply(550, "Failed to store file.")

    # ---- MKD / RMD / DELE / RNFR / RNTO ----
    def handle_MKD(self, arg: str) -> None:
        if not self.logged_in:
            self.reply(530, "Please login with USER and PASS.")
            return
        if not self.ensure_write_perm():
            return
        real_path = self.to_real_path(arg)
        try:
            os.makedirs(real_path, exist_ok=True)
            self.reply(257, f'"{arg}" directory created.')
        except Exception:
            self.reply(550, "Create directory failed.")

    def handle_RMD(self, arg: str) -> None:
        if not self.logged_in:
            self.reply(530, "Please login with USER and PASS.")
            return
        if not self.ensure_write_perm():
            return
        real_path = self.to_real_path(arg)
        try:
            os.rmdir(real_path)
            self.reply(250, "Remove directory operation successful.")
        except Exception:
            self.reply(550, "Remove directory failed.")

    def handle_DELE(self, arg: str) -> None:
        if not self.logged_in:
            self.reply(530, "Please login with USER and PASS.")
            return
        if not self.ensure_write_perm():
            return
        real_path = self.to_real_path(arg)
        try:
            os.remove(real_path)
            self.reply(250, "Delete operation successful.")
        except Exception:
            self.reply(550, "Delete failed.")

    def handle_RNFR(self, arg: str) -> None:
        if not self.logged_in:
            self.reply(530, "Please login with USER and PASS.")
            return
        if not self.ensure_write_perm():
            return
        self._rename_from = self.to_real_path(arg)
        if not os.path.exists(self._rename_from):
            self.reply(550, "File not found.")
            self._rename_from = None
            return
        self.reply(350, "File exists, ready for destination name.")

    def handle_RNTO(self, arg: str) -> None:
        if not getattr(self, "_rename_from", None):
            self.reply(503, "Bad sequence of commands.")
            return
        real_to = self.to_real_path(arg)
        try:
            os.rename(self._rename_from, real_to)
            self.reply(250, "Rename successful.")
        except Exception:
            self.reply(550, "Rename failed.")
        finally:
            self._rename_from = None

    # ---------- Main loop ----------
    def serve(self) -> None:
        # Send welcome banner
        self.reply(220, "Simple FTP Server Ready")
        try:
            while True:
                cmdline = self.read_command()
                if cmdline is None:
                    break
                if not cmdline:
                    continue
                parts = cmdline.split(" ", 1)
                command = parts[0].upper()
                arg = parts[1] if len(parts) > 1 else ""

                if command == "USER":
                    self.handle_USER(arg)
                elif command == "PASS":
                    self.handle_PASS(arg)
                elif command == "PWD":
                    self.handle_PWD()
                elif command == "CWD":
                    self.handle_CWD(arg)
                elif command == "TYPE":
                    self.handle_TYPE(arg)
                elif command == "PASV":
                    self.handle_PASV()
                elif command == "LIST":
                    self.handle_LIST(arg)
                elif command == "RETR":
                    self.handle_RETR(arg)
                elif command == "STOR":
                    self.handle_STOR(arg)
                elif command == "MKD":
                    self.handle_MKD(arg)
                elif command == "RMD":
                    self.handle_RMD(arg)
                elif command == "DELE":
                    self.handle_DELE(arg)
                elif command == "RNFR":
                    self.handle_RNFR(arg)
                elif command == "RNTO":
                    self.handle_RNTO(arg)
                elif command == "QUIT":
                    self.reply(221, "Goodbye.")
                    break
                else:
                    self.reply(502, "Command not implemented.")
        finally:
            try:
                self.control_file.close()
            except Exception:
                pass
            try:
                self.conn.close()
            except Exception:
                pass


def start_ftp_server(config: FTPConfig) -> None:
    """Start the FTP server and accept connections forever."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((config.host, config.port))
    sock.listen(5)
    print(f"FTP server listening on {config.host}:{config.port}, root={config.root}")

    try:
        while True:
            conn, addr = sock.accept()
            print(f"New connection from {addr}")
            session = FTPSession(conn, addr, config)
            threading.Thread(target=session.serve, daemon=True).start()
    finally:
        sock.close()


if __name__ == "__main__":
    # You can adjust these settings for your experiments
    cfg = FTPConfig(
        host="0.0.0.0",         # or "127.0.0.1" for local only
        port=2121,              # match this in your client
        root=os.path.abspath("./ftp_root"),
    )
    start_ftp_server(cfg)
