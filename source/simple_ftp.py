#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal FTP client implemented on raw TCP sockets.

This module intentionally does NOT use ftplib, so that you can see how
FTP works at the protocol level. It implements only a very small subset
of the protocol: login, directory operations, and binary file transfer
using passive (PASV) mode.

It is designed to be imported and used by a GUI or other applications.
"""

from __future__ import annotations

import socket
from typing import List, Optional, Tuple, Callable, BinaryIO


class FTPProtocolError(Exception):
    """Raised when the FTP server returns an unexpected reply."""


class FTPConnection:
    """Very small FTP client based directly on TCP sockets.

    Public methods used by the GUI:
    - connect(host, port, timeout)
    - login(user, password)
    - pwd(), cwd(path)
    - mkd(dirname), rmd(dirname)
    - delete(filename), rename(old, new)
    - list_lines()
    - retr_binary(filename, callback)
    - stor_binary(filename, fileobj)
    - quit()

    This is a teaching/demo implementation and omits many details of
    the full FTP specification.
    """

    def __init__(self) -> None:
        # Control connection socket
        self.sock: Optional[socket.socket] = None
        # Buffered file-like object wrapping the control socket for convenient readline()
        self.file = None
        self.host: str = ""
        self.port: int = 21
        # Encoding used for control connection replies and commands
        self.encoding: str = "utf-8"

    # ----------- Basic socket helpers -----------
    def _readline(self) -> str:
        """Read a single line (ending with \r\n) from the control connection.

        Example server reply: "220 Welcome...\r\n".
        We read bytes until newline and then decode.
        """
        if self.file is None:
            raise FTPProtocolError("Control connection not open")
        line = self.file.readline()
        if not line:
            raise FTPProtocolError("Connection closed by server")
        # FTP uses ASCII-compatible encodings for replies.
        return line.decode(self.encoding, errors="ignore").rstrip("\r\n")

    def _read_response(self) -> Tuple[int, str]:
        """Read a server response and return (code, last_line_text).

        FTP replies can be single-line or multi-line:
        - Single-line:  "220 Welcome"\r\n
        - Multi-line:   "227-First line"\r\n
                          ...more lines...
                         "227 Last line"\r\n
        We always return the numeric code and the text of the last line.
        """
        line = self._readline()
        if len(line) < 3 or not line[:3].isdigit():
            raise FTPProtocolError(f"Invalid reply: {line}")

        code = int(line[:3])
        text = line[4:] if len(line) > 3 else ""

        # Multi-line reply: first line like "227-..."
        if len(line) >= 4 and line[3] == "-":
            prefix = f"{code} "
            # Read until we find a line starting with "<code> "
            while True:
                next_line = self._readline()
                if next_line.startswith(prefix):
                    text = next_line[4:] if len(next_line) > 3 else ""
                    break
        return code, text

    def _send_cmd(self, cmd: str) -> Tuple[int, str]:
        """Send a command like 'USER name' and return the server response.

        Returns (code, text) where code is an integer (e.g. 220, 230).
        """
        if self.sock is None:
            raise FTPProtocolError("Not connected")
        data = (cmd + "\r\n").encode(self.encoding)
        self.sock.sendall(data)
        return self._read_response()

    # ----------- Public high-level API -----------
    def connect(self, host: str, port: int = 21, timeout: int = 10) -> None:
        """Open TCP connection to FTP server and read the welcome banner."""
        self.host = host
        self.port = port
        self.sock = socket.create_connection((host, port), timeout=timeout)
        # Wrap the socket in a buffered file-like object for readline()
        self.file = self.sock.makefile('rb')

        code, text = self._read_response()
        if code != 220:
            raise FTPProtocolError(f"Unexpected welcome reply: {code} {text}")

    def login(self, user: str = "anonymous", password: str = "") -> None:
        """Send USER/PASS to log in to the FTP server."""
        code, _ = self._send_cmd(f"USER {user}")
        if code == 230:
            # Logged in without needing PASS
            return
        if code == 331:
            code2, text2 = self._send_cmd(f"PASS {password}")
            if code2 not in (230, 202):
                raise FTPProtocolError(f"Login failed: {code2} {text2}")
        else:
            raise FTPProtocolError(f"USER command failed: {code}")

    def pwd(self) -> str:
        """Return the current working directory using PWD."""
        code, text = self._send_cmd("PWD")
        if code != 257:
            raise FTPProtocolError(f"PWD failed: {code} {text}")
        # Typical response: 257 "/" is current directory
        if '"' in text:
            try:
                start = text.index('"') + 1
                end = text.index('"', start)
                return text[start:end]
            except ValueError:
                return text
        return text

    def cwd(self, path: str) -> None:
        """Change working directory."""
        code, text = self._send_cmd(f"CWD {path}")
        if code != 250:
            raise FTPProtocolError(f"CWD failed: {code} {text}")

    def mkd(self, dirname: str) -> None:
        """Create a directory on the server."""
        code, text = self._send_cmd(f"MKD {dirname}")
        if code not in (257, 250):
            raise FTPProtocolError(f"MKD failed: {code} {text}")

    def rmd(self, dirname: str) -> None:
        """Remove a directory on the server."""
        code, text = self._send_cmd(f"RMD {dirname}")
        if code != 250:
            raise FTPProtocolError(f"RMD failed: {code} {text}")

    def delete(self, filename: str) -> None:
        """Delete a file on the server."""
        code, text = self._send_cmd(f"DELE {filename}")
        if code != 250:
            raise FTPProtocolError(f"DELE failed: {code} {text}")

    def rename(self, old: str, new: str) -> None:
        """Rename a file or directory on the server."""
        code, text = self._send_cmd(f"RNFR {old}")
        if code != 350:
            raise FTPProtocolError(f"RNFR failed: {code} {text}")
        code2, text2 = self._send_cmd(f"RNTO {new}")
        if code2 != 250:
            raise FTPProtocolError(f"RNTO failed: {code2} {text2}")

    def quit(self) -> None:
        """Politely close the FTP session and underlying socket."""
        if self.sock is None:
            return
        try:
            self._send_cmd("QUIT")
        except Exception:
            pass
        try:
            if self.file is not None:
                self.file.close()
        finally:
            self.file = None
        try:
            self.sock.close()
        finally:
            self.sock = None

    # ----------- Passive mode data connection helpers -----------
    def _enter_passive_mode(self) -> socket.socket:
        """Send PASV and open a data connection to the returned address.

        PASV reply example (RFC 959):
            227 Entering Passive Mode (h1,h2,h3,h4,p1,p2).

        Data port = p1*256 + p2 on host h1.h2.h3.h4.
        """
        code, text = self._send_cmd("PASV")
        if code != 227:
            raise FTPProtocolError(f"PASV failed: {code} {text}")

        # Extract the numbers inside parentheses
        start = text.find('(')
        end = text.find(')', start + 1)
        if start == -1 or end == -1:
            raise FTPProtocolError(f"Invalid PASV reply: {text}")
        nums = text[start + 1 : end].split(',')
        if len(nums) != 6:
            raise FTPProtocolError(f"Invalid PASV address: {text}")
        h1, h2, h3, h4, p1, p2 = nums
        data_host = f"{h1}.{h2}.{h3}.{h4}"
        data_port = int(p1) * 256 + int(p2)

        return socket.create_connection((data_host, data_port))

    # ----------- LIST / RETR / STOR using data connection -----------
    def list_lines(self) -> List[str]:
        """Return directory listing as a list of lines of text.

        Implementation steps:
        - Set binary mode with TYPE I (safer for arbitrary bytes)
        - Enter PASV to open a data connection
        - Send LIST on the control connection
        - Read all data from the data connection
        - Read the final 226/250 reply on the control connection
        """
        self._send_cmd("TYPE I")

        data_sock = self._enter_passive_mode()
        code, text = self._send_cmd("LIST")
        if code not in (125, 150):
            data_sock.close()
            raise FTPProtocolError(f"LIST failed: {code} {text}")

        lines: List[str] = []
        with data_sock:
            buffer = b""
            while True:
                chunk = data_sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk
            text_data = buffer.decode("utf-8", errors="ignore")
            for line in text_data.splitlines():
                if line.strip():
                    lines.append(line.rstrip("\r\n"))

        code2, text2 = self._read_response()
        if code2 not in (226, 250):
            raise FTPProtocolError(f"LIST did not complete correctly: {code2} {text2}")
        return lines

    def retr_binary(self, filename: str, callback: Callable[[bytes], None]) -> None:
        """Download a file and pass each data chunk to callback(chunk: bytes)."""
        self._send_cmd("TYPE I")
        data_sock = self._enter_passive_mode()
        code, text = self._send_cmd(f"RETR {filename}")
        if code not in (125, 150):
            data_sock.close()
            raise FTPProtocolError(f"RETR failed: {code} {text}")

        with data_sock:
            while True:
                buf = data_sock.recv(4096)
                if not buf:
                    break
                callback(buf)

        code2, text2 = self._read_response()
        if code2 not in (226, 250):
            raise FTPProtocolError(f"RETR did not complete correctly: {code2} {text2}")

    def stor_binary(self, filename: str, fileobj: BinaryIO) -> None:
        """Upload a file to the server from a binary file-like object."""
        self._send_cmd("TYPE I")
        data_sock = self._enter_passive_mode()
        code, text = self._send_cmd(f"STOR {filename}")
        if code not in (125, 150):
            data_sock.close()
            raise FTPProtocolError(f"STOR failed: {code} {text}")

        with data_sock:
            while True:
                buf = fileobj.read(4096)
                if not buf:
                    break
                data_sock.sendall(buf)

        code2, text2 = self._read_response()
        if code2 not in (226, 250):
            raise FTPProtocolError(f"STOR did not complete correctly: {code2} {text2}")
