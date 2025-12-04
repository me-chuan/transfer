#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Simple GUI FTP client based on TCP/IP sockets.

Features:
- Connect to FTP server with host, port, username, password
- List remote directory
- Download files
- Create / delete / rename files and directories

This uses Python's built-in ftplib which implements the FTP protocol
on top of TCP sockets.
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from ftplib import FTP, error_perm


class FTPClientGUI:
    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        self.master.title("Simple FTP Client")
        self.master.geometry("900x500")

        self.ftp: FTP | None = None
        self.current_path = "/"

        self._build_widgets()
        self._set_disconnected_state()

    # ---------------- UI -----------------
    def _build_widgets(self) -> None:
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(2, weight=1)

        # Connection frame
        frm_conn = ttk.LabelFrame(self.master, text="Connection")
        frm_conn.grid(row=0, column=0, sticky="ew", padx=8, pady=4)
        for i in range(10):
            frm_conn.columnconfigure(i, weight=1)

        ttk.Label(frm_conn, text="Host:").grid(row=0, column=0, padx=4, pady=2, sticky="e")
        self.ent_host = ttk.Entry(frm_conn)
        self.ent_host.grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        self.ent_host.insert(0, "127.0.0.1")

        ttk.Label(frm_conn, text="Port:").grid(row=0, column=2, padx=4, pady=2, sticky="e")
        self.ent_port = ttk.Entry(frm_conn, width=6)
        self.ent_port.grid(row=0, column=3, padx=4, pady=2, sticky="w")
        self.ent_port.insert(0, "21")

        ttk.Label(frm_conn, text="User:").grid(row=0, column=4, padx=4, pady=2, sticky="e")
        self.ent_user = ttk.Entry(frm_conn, width=12)
        self.ent_user.grid(row=0, column=5, padx=4, pady=2, sticky="ew")
        self.ent_user.insert(0, "anonymous")

        ttk.Label(frm_conn, text="Password:").grid(row=0, column=6, padx=4, pady=2, sticky="e")
        self.ent_pass = ttk.Entry(frm_conn, show="*")
        self.ent_pass.grid(row=0, column=7, padx=4, pady=2, sticky="ew")

        self.btn_connect = ttk.Button(frm_conn, text="Connect", command=self.connect)
        self.btn_connect.grid(row=0, column=8, padx=4, pady=2)
        self.btn_disconnect = ttk.Button(frm_conn, text="Disconnect", command=self.disconnect)
        self.btn_disconnect.grid(row=0, column=9, padx=4, pady=2)

        # Path + operations
        frm_path = ttk.Frame(self.master)
        frm_path.grid(row=1, column=0, sticky="ew", padx=8, pady=2)
        frm_path.columnconfigure(1, weight=1)

        ttk.Label(frm_path, text="Remote path:").grid(row=0, column=0, padx=4, pady=2)
        self.lbl_path = ttk.Label(frm_path, text=self.current_path, relief="sunken", anchor="w")
        self.lbl_path.grid(row=0, column=1, padx=4, pady=2, sticky="ew")

        self.btn_up = ttk.Button(frm_path, text="Up", width=5, command=self.go_up)
        self.btn_up.grid(row=0, column=2, padx=2)

        self.btn_mkdir = ttk.Button(frm_path, text="New Folder", command=self.mkdir)
        self.btn_mkdir.grid(row=0, column=3, padx=2)
        self.btn_newfile = ttk.Button(frm_path, text="New File", command=self.new_file)
        self.btn_newfile.grid(row=0, column=4, padx=2)
        self.btn_upload = ttk.Button(frm_path, text="Upload", command=self.upload)
        self.btn_upload.grid(row=0, column=5, padx=2)
        self.btn_rename = ttk.Button(frm_path, text="Rename", command=self.rename)
        self.btn_rename.grid(row=0, column=6, padx=2)
        self.btn_delete = ttk.Button(frm_path, text="Delete", command=self.delete)
        self.btn_delete.grid(row=0, column=7, padx=2)
        self.btn_download = ttk.Button(frm_path, text="Download", command=self.download)
        self.btn_download.grid(row=0, column=8, padx=2)

        # File list
        frm_list = ttk.Frame(self.master)
        frm_list.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)
        frm_list.rowconfigure(0, weight=1)
        frm_list.columnconfigure(0, weight=1)

        columns = ("name", "size", "type")
        self.tree = ttk.Treeview(frm_list, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("name", text="Name")
        self.tree.heading("size", text="Size (bytes)")
        self.tree.heading("type", text="Type")
        self.tree.column("name", width=400, anchor="w")
        self.tree.column("size", width=120, anchor="e")
        self.tree.column("type", width=80, anchor="center")

        vsb = ttk.Scrollbar(frm_list, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(frm_list, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscroll=vsb.set, xscroll=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self.tree.bind("<Double-1>", self._on_double_click)

        # Status bar
        self.status_var = tk.StringVar(value="Disconnected")
        status_bar = ttk.Label(self.master, textvariable=self.status_var, relief="sunken", anchor="w")
        status_bar.grid(row=3, column=0, sticky="ew")

    # ------------- Connection logic -------------
    def connect(self) -> None:
        host = self.ent_host.get().strip()
        port_text = self.ent_port.get().strip() or "21"
        user = self.ent_user.get().strip() or "anonymous"
        password = self.ent_pass.get()

        try:
            port = int(port_text)
        except ValueError:
            messagebox.showerror("Error", "Invalid port number")
            return

        def _do_connect():
            self._set_status(f"Connecting to {host}:{port} ...")
            try:
                ftp = FTP()
                ftp.connect(host, port, timeout=10)
                ftp.login(user=user, passwd=password)
                self.ftp = ftp
                self.current_path = ftp.pwd()
                self._set_connected_state()
                self._refresh_list()
                self._set_status("Connected")
            except Exception as e:
                self.ftp = None
                self._set_disconnected_state()
                self._set_status("Disconnected")
                messagebox.showerror("Connection failed", str(e))

        threading.Thread(target=_do_connect, daemon=True).start()

    def disconnect(self) -> None:
        if self.ftp is not None:
            try:
                self.ftp.quit()
            except Exception:
                pass
            finally:
                self.ftp = None
        self._set_disconnected_state()
        self._set_status("Disconnected")

    # ------------- Helpers -------------
    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _set_connected_state(self) -> None:
        self.btn_connect.configure(state="disabled")
        self.btn_disconnect.configure(state="normal")
        self.btn_up.configure(state="normal")
        self.btn_mkdir.configure(state="normal")
        self.btn_newfile.configure(state="normal")
        self.btn_upload.configure(state="normal")
        self.btn_rename.configure(state="normal")
        self.btn_delete.configure(state="normal")
        self.btn_download.configure(state="normal")
        self.tree.configure(selectmode="browse")

    def _set_disconnected_state(self) -> None:
        self.btn_connect.configure(state="normal")
        self.btn_disconnect.configure(state="disabled")
        self.btn_up.configure(state="disabled")
        self.btn_mkdir.configure(state="disabled")
        self.btn_newfile.configure(state="disabled")
        self.btn_upload.configure(state="disabled")
        self.btn_rename.configure(state="disabled")
        self.btn_delete.configure(state="disabled")
        self.btn_download.configure(state="disabled")
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.lbl_path.configure(text="/")

    def _ensure_connected(self) -> bool:
        if self.ftp is None:
            messagebox.showwarning("Not connected", "Please connect to a server first.")
            return False
        return True

    # ------------- Directory listing -------------
    def _refresh_list(self) -> None:
        if not self._ensure_connected():
            return

        ftp = self.ftp
        assert ftp is not None

        # Clear current tree
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Update path label
        self.current_path = ftp.pwd()
        self.lbl_path.configure(text=self.current_path)

        entries: list[tuple[str, str, int | None]] = []  # (name, type, size)

        try:
            # Prefer MLSD: structured directory listing if server supports it
            try:
                for name, facts in ftp.mlsd():
                    if name in (".", ".."):
                        continue
                    ftype = facts.get("type", "file")
                    if ftype == "dir":
                        entries.append((name, "dir", None))
                    else:
                        size_str = facts.get("size")
                        size_int: int | None = int(size_str) if size_str is not None else None
                        entries.append((name, "file", size_int))
            except Exception:
                # Fallback: NLST returns only names
                names = ftp.nlst()
                for name in names:
                    if name in (".", ".."):
                        continue

                    # Detect directory by trying cwd
                    is_dir = False
                    cur = ftp.pwd()
                    try:
                        ftp.cwd(name)
                        is_dir = True
                    except Exception:
                        is_dir = False
                    finally:
                        try:
                            ftp.cwd(cur)
                        except Exception:
                            pass

                    if is_dir:
                        entries.append((name, "dir", None))
                    else:
                        size: int | None = None
                        try:
                            size_val = ftp.size(name)
                            size = int(size_val) if size_val is not None else None
                        except Exception:
                            size = None
                        entries.append((name, "file", size))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to list directory: {e}")
            return

        # Sort: directories first, then files, by name
        entries.sort(key=lambda x: (0 if x[1] == "dir" else 1, x[0].lower()))

        for name, ftype, size in entries:
            size_text = "" if size is None else str(size)
            self.tree.insert("", "end", values=(name, size_text, ftype))

    # ------------- Navigation -------------
    def _on_double_click(self, event) -> None:
        item_id = self.tree.focus()
        if not item_id:
            return
        name, _size, ftype = self.tree.item(item_id, "values")
        if ftype == "dir":
            self.change_dir(name)

    def change_dir(self, dirname: str) -> None:
        if not self._ensure_connected():
            return
        ftp = self.ftp
        assert ftp is not None
        try:
            ftp.cwd(dirname)
            self._refresh_list()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to change directory: {e}")

    def go_up(self) -> None:
        if not self._ensure_connected():
            return
        ftp = self.ftp
        assert ftp is not None
        try:
            ftp.cwd("..")
            self._refresh_list()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to go up: {e}")

    # ------------- File operations -------------
    def _get_selected(self):
        item_id = self.tree.focus()
        if not item_id:
            return None
        values = self.tree.item(item_id, "values")
        if not values:
            return None
        name, _size, ftype = values
        return name, ftype

    def new_file(self) -> None:
        """Create a small text file on the server using STOR with in-memory data."""
        if not self._ensure_connected():
            return
        filename = simpledialog.askstring("New file", "File name:", parent=self.master)
        if not filename:
            return
        content = simpledialog.askstring("New file", "Initial content (optional):", parent=self.master)
        if content is None:
            content = ""
        data = content.encode("utf-8")
        ftp = self.ftp
        assert ftp is not None
        from io import BytesIO
        try:
            bio = BytesIO(data)
            ftp.storbinary(f"STOR {filename}", bio)
            self._refresh_list()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create file: {e}")

    def upload(self) -> None:
        """Upload a local file to the current remote directory."""
        if not self._ensure_connected():
            return
        local_path = filedialog.askopenfilename(title="Select file to upload")
        if not local_path:
            return
        filename = os.path.basename(local_path)
        ftp = self.ftp
        assert ftp is not None

        def _do_upload():
            self._set_status(f"Uploading {filename} ...")
            try:
                with open(local_path, "rb") as f:
                    ftp.storbinary(f"STOR {filename}", f)
                self._set_status(f"Uploaded {filename}")
                self._refresh_list()
            except Exception as e:
                self._set_status("Upload failed")
                messagebox.showerror("Error", f"Failed to upload file: {e}")

        threading.Thread(target=_do_upload, daemon=True).start()

    def mkdir(self) -> None:
        if not self._ensure_connected():
            return
        dirname = simpledialog.askstring("New folder", "Folder name:", parent=self.master)
        if not dirname:
            return
        ftp = self.ftp
        assert ftp is not None
        try:
            ftp.mkd(dirname)
            self._refresh_list()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create folder: {e}")

    def rename(self) -> None:
        if not self._ensure_connected():
            return
        selected = self._get_selected()
        if not selected:
            messagebox.showinfo("Rename", "Please select a file or folder.")
            return
        old_name, _ftype = selected
        new_name = simpledialog.askstring("Rename", f"New name for '{old_name}':", parent=self.master)
        if not new_name or new_name == old_name:
            return
        ftp = self.ftp
        assert ftp is not None
        try:
            ftp.rename(old_name, new_name)
            self._refresh_list()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to rename: {e}")

    def delete(self) -> None:
        if not self._ensure_connected():
            return
        selected = self._get_selected()
        if not selected:
            messagebox.showinfo("Delete", "Please select a file or folder.")
            return
        name, ftype = selected
        if not messagebox.askyesno("Confirm delete", f"Are you sure you want to delete '{name}'?"):
            return
        ftp = self.ftp
        assert ftp is not None
        try:
            if ftype == "dir":
                ftp.rmd(name)
            else:
                ftp.delete(name)
            self._refresh_list()
        except error_perm as e:
            messagebox.showerror("Error", f"Permission error: {e}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete: {e}")

    def download(self) -> None:
        if not self._ensure_connected():
            return
        selected = self._get_selected()
        if not selected:
            messagebox.showinfo("Download", "Please select a file to download.")
            return
        name, ftype = selected
        if ftype == "dir":
            messagebox.showinfo("Download", "Folder download is not implemented in this simple client.")
            return

        local_path = filedialog.asksaveasfilename(title="Save as", initialfile=name)
        if not local_path:
            return

        ftp = self.ftp
        assert ftp is not None

        def _do_download():
            self._set_status(f"Downloading {name} ...")
            try:
                with open(local_path, "wb") as f:
                    ftp.retrbinary(f"RETR {name}", f.write)
                self._set_status(f"Downloaded {name} to {local_path}")
            except Exception as e:
                self._set_status("Download failed")
                messagebox.showerror("Error", f"Failed to download file: {e}")

        threading.Thread(target=_do_download, daemon=True).start()


def main() -> None:
    root = tk.Tk()
    app = FTPClientGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
