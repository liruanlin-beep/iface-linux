import json
import queue
import threading
import sys
import tkinter as tk
from datetime import datetime
from uuid import uuid4
from tkinter import messagebox, ttk

from app.core.agent_runtime import request_agent_plan
from app.core.ai_provider import PROVIDERS
from app.core.paths import DATABASE_DIR, OUTPUTS_DIR
from app.ui.theme import BG, PANEL


RISK_LABELS = {
    "read": "Read only",
    "view": "View action",
    "write": "Write files",
    "compute": "Start calculation",
}

KEY_STORAGE_LABEL = "Windows DPAPI" if sys.platform == "win32" else "Linux system keyring"

class AIAdvisorWindow(tk.Toplevel):
    """Human-approved workspace agent inspired by visible tool-call workflows."""

    def __init__(self, master, callbacks):
        super().__init__(master)
        self.callbacks = callbacks
        self.worker = None
        self.messages = queue.Queue()
        self.plan = None
        self.conversation = []
        self.session_id = uuid4().hex
        self.session_path = DATABASE_DIR / "agent_sessions.json"
        self._poll_id = None
        self.title("iface Agent")
        self.geometry("1100x760")
        self.minsize(840, 580)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self._load_saved_credentials()
        self._poll()

    def _build(self):
        shell = ttk.Frame(self, style="Panel.TFrame", padding=14)
        shell.pack(fill="both", expand=True, padx=12, pady=12)
        shell.columnconfigure(1, weight=1)
        shell.rowconfigure(3, weight=1)
        shell.rowconfigure(5, weight=1)

        ttk.Label(
            shell,
            text="iface Agent · Materials computation assistant",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))
        provider_bar = ttk.Frame(shell, style="Panel.TFrame")
        provider_bar.grid(
            row=0, column=1, columnspan=3, sticky="e", pady=(0, 10)
        )
        ttk.Label(provider_bar, text="AI provider").pack(side="left")
        self.provider = tk.StringVar(value="DeepSeek")
        ttk.Label(provider_bar, text="DeepSeek", style="Title.TLabel").pack(
            side="left", padx=(6, 12)
        )
        ttk.Label(provider_bar, text="Model").pack(side="left")
        self.api_key_label = ttk.Label(shell, text="DeepSeek API key")
        self.api_key_label.grid(row=1, column=0, sticky="w")
        self.api_key = tk.StringVar()
        self.api_key_entry = ttk.Entry(shell, textvariable=self.api_key, show="●")
        self.api_key_entry.grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=(8, 12)
        )
        self.model = tk.StringVar(value=PROVIDERS["DeepSeek"]["default_model"])
        self.model_combo = ttk.Combobox(
            provider_bar,
            textvariable=self.model,
            values=PROVIDERS["DeepSeek"]["models"],
            width=25,
        )
        self.model_combo.pack(side="left", padx=(6, 0))
        self.key_action_frame = ttk.Frame(shell, style="Panel.TFrame")
        self.key_action_frame.grid(row=1, column=3, sticky="e")
        self.test_key_button = ttk.Button(
            self.key_action_frame,
            text="Test API key",
            command=self.test_api_key,
        )
        self.test_key_button.pack(side="left")
        self.save_key_button = ttk.Button(
            self.key_action_frame,
            text="Save key",
            style="Success.TButton",
            command=self.save_api_key,
        )
        self.save_key_button.pack(side="left", padx=(6, 0))
        self.api_key_help = ttk.Label(
            shell,
            text=(
                f"Test the key before saving. Saved keys use {KEY_STORAGE_LABEL}; "
                "only your account can access them. File writes and calculations still require confirmation."
            ),
            style="Muted.TLabel",
        )
        self.api_key_help.grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(3, 10)
        )
        self.connected_frame = ttk.Frame(shell, style="Panel.TFrame")
        self.connected_label = ttk.Label(
            self.connected_frame,
            text="DeepSeek API connected",
            style="Muted.TLabel",
        )
        self.connected_label.pack(side="left")
        ttk.Button(
            self.connected_frame,
            text="Change key",
            command=self._show_api_key_editor,
        ).pack(side="left", padx=10)
        ttk.Button(
            self.connected_frame,
            text="Remove saved key",
            command=self.forget_saved_api_key,
        ).pack(side="left")

        chat_frame = ttk.LabelFrame(shell, text="Chat with Agent", padding=7)
        chat_frame.grid(row=3, column=0, columnspan=4, sticky="nsew", pady=(0, 8))
        chat_frame.rowconfigure(0, weight=1)
        chat_frame.columnconfigure(0, weight=1)
        self.chat = tk.Text(
            chat_frame, height=8, wrap="word", bg=PANEL, relief="flat",
            padx=8, pady=8, state="disabled",
        )
        chat_scroll = ttk.Scrollbar(chat_frame, orient="vertical", command=self.chat.yview)
        self.chat.configure(yscrollcommand=chat_scroll.set)
        self.chat.grid(row=0, column=0, sticky="nsew")
        chat_scroll.grid(row=0, column=1, sticky="ns")
        self._append_chat(
            "Agent",
            "Tell me what you want to do. You can ask follow-up questions or revise your request."
            "\nUse /resume to restore a conversation, /history to list history, or /export to export it.",
            persist=False,
        )
        session_bar = ttk.Frame(chat_frame, style="Panel.TFrame")
        session_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(
            session_bar, text="Resume last conversation", command=self.resume_last_session
        ).pack(side="left")
        ttk.Button(
            session_bar, text="New conversation", command=self.new_session
        ).pack(side="left", padx=6)
        ttk.Button(
            session_bar, text="Export conversation", command=self.export_session
        ).pack(side="left")

        prompt_frame = ttk.LabelFrame(shell, text="Message (Ctrl+Enter to send)", padding=7)
        prompt_frame.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        self.prompt = tk.Text(
            prompt_frame,
            height=3,
            wrap="word",
            bg=PANEL,
            relief="flat",
            padx=8,
            pady=8,
        )
        self.prompt.pack(fill="both", expand=True)
        self.prompt.bind("<Control-Return>", self._send_shortcut)

        self.result_frame = ttk.LabelFrame(
            shell,
            text="Agent tool calls (none yet)",
            padding=7,
        )
        result_frame = self.result_frame
        result_frame.grid(row=5, column=0, columnspan=4, sticky="nsew", pady=(0, 8))
        result_frame.rowconfigure(0, weight=1)
        result_frame.columnconfigure(0, weight=1)
        columns = ("tool", "risk", "arguments", "reason", "result")
        self.table = ttk.Treeview(
            result_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
        )
        for key, title, width in [
            ("tool", "Tool", 170),
            ("risk", "Risk", 85),
            ("arguments", "Arguments", 220),
            ("reason", "Reason", 310),
            ("result", "Result", 260),
        ]:
            self.table.heading(key, text=title)
            self.table.column(
                key,
                width=width,
                minwidth=70,
                stretch=key in {"reason", "result"},
            )
        ybar = ttk.Scrollbar(result_frame, orient="vertical", command=self.table.yview)
        xbar = ttk.Scrollbar(result_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        self.result_frame.grid_remove()

        buttons = ttk.Frame(shell, style="Panel.TFrame")
        buttons.grid(row=6, column=0, columnspan=4, sticky="ew")
        self.plan_button = ttk.Button(
            buttons,
            text="Send to Agent",
            style="Primary.TButton",
            command=self.make_plan,
        )
        self.plan_button.pack(side="left")
        self.execute_button = ttk.Button(
            buttons,
            text="Confirm selected actions",
            style="Success.TButton",
            command=self.execute_selected,
        )
        self.progress = ttk.Progressbar(
            buttons,
            mode="indeterminate",
            length=180,
        )
        self.status = tk.StringVar(value="Agent has not called any tools yet.")
        ttk.Label(buttons, textvariable=self.status, style="Muted.TLabel").pack(
            side="right"
        )

    def make_plan(self):
        if self.worker and self.worker.is_alive():
            return
        request_text = self.prompt.get("1.0", "end").strip()
        if not request_text:
            messagebox.showwarning("No request", "Tell Agent what you want to accomplish.", parent=self)
            return
        if self._handle_local_command(request_text):
            self.prompt.delete("1.0", "end")
            return
        if not self.api_key.get().strip():
            messagebox.showwarning("API key required", "Enter an API key for the selected provider.", parent=self)
            return
        # Once a key has been supplied, keep credentials out of the main
        # conversation layout. The user can reopen the editor explicitly.
        self._show_connected_credentials()
        try:
            context = self.callbacks["get_agent_context"]()
        except Exception as exc:
            messagebox.showerror("Could not read workspace", str(exc), parent=self)
            return
        self.plan = None
        self.prompt.delete("1.0", "end")
        previous_messages = tuple(self.conversation)
        self._append_chat("You", request_text)
        self.table.delete(*self.table.get_children())
        self.result_frame.grid_remove()
        self.execute_button.pack_forget()
        self.status.set("Agent is thinking (up to about 45 seconds on a slow network)…")
        self.plan_button.configure(state="disabled")
        self._start_progress()
        self.worker = threading.Thread(
            target=self._plan_worker,
            args=(
                self.api_key.get(),
                self.provider.get(),
                self.model.get(),
                request_text,
                context,
                previous_messages,
            ),
            daemon=True,
        )
        self.worker.start()

    def _plan_worker(self, *args):
        try:
            api_key, provider, model, request_text, context, history = args
            result = request_agent_plan(
                api_key,
                model,
                request_text,
                context,
                provider=provider,
                conversation_history=history,
            )
            self.messages.put(("ok", result))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def _send_shortcut(self, _event):
        self.make_plan()
        return "break"

    def _append_chat(self, speaker, content, persist=True):
        text = str(content or "").strip()
        if not text:
            return
        self.chat.configure(state="normal")
        if self.chat.get("1.0", "end-1c"):
            self.chat.insert("end", "\n\n")
        self.chat.insert("end", f"{speaker}: \n{text}")
        self.chat.configure(state="disabled")
        self.chat.see("end")
        if speaker == "You":
            self.conversation.append({"role": "user", "content": text})
        elif speaker == "Agent":
            self.conversation.append({"role": "assistant", "content": text})
        if persist:
            self._save_session()

    def _load_session_store(self):
        try:
            data = json.loads(self.session_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            data = {}
        sessions = data.get("sessions", [])
        return [item for item in sessions if isinstance(item, dict)]

    def _save_session(self):
        if not any(item.get("role") == "user" for item in self.conversation):
            return
        DATABASE_DIR.mkdir(parents=True, exist_ok=True)
        sessions = [
            item for item in self._load_session_store()
            if item.get("id") != self.session_id
        ]
        sessions.append(
            {
                "id": self.session_id,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "messages": self.conversation[-200:],
            }
        )
        sessions = sessions[-50:]
        temporary = self.session_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"sessions": sessions}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.session_path)

    def _render_conversation(self):
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        for index, item in enumerate(self.conversation):
            if index:
                self.chat.insert("end", "\n\n")
            speaker = "You" if item.get("role") == "user" else "Agent"
            self.chat.insert("end", f"{speaker}: \n{item.get('content', '')}")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def resume_last_session(self):
        sessions = self._load_session_store()
        candidates = [item for item in sessions if item.get("messages")]
        if not candidates:
            messagebox.showinfo("Restore conversation", "No saved conversations are available.", parent=self)
            return
        latest = candidates[-1]
        self.session_id = str(latest.get("id") or uuid4().hex)
        self.conversation = [
            item for item in latest.get("messages", [])
            if isinstance(item, dict) and item.get("role") in {"user", "assistant"}
        ]
        self._render_conversation()
        self.status.set(f"Conversation restored · {latest.get('updated_at', '')}")

    def new_session(self):
        self._save_session()
        self.session_id = uuid4().hex
        self.conversation = []
        self._render_conversation()
        self._append_chat(
            "Agent", "New conversation started. Use /resume to restore the previous conversation.",
            persist=False,
        )
        self.plan = None
        self.table.delete(*self.table.get_children())
        self.result_frame.grid_remove()
        self.execute_button.pack_forget()

    def history_summary(self):
        sessions = self._load_session_store()
        if not sessions:
            return "No saved conversations are available."
        lines = ["Saved conversations: "]
        for index, item in enumerate(reversed(sessions[-10:]), 1):
            first_user = next(
                (
                    str(message.get("content") or "").replace("\n", " ")[:60]
                    for message in item.get("messages", [])
                    if message.get("role") == "user"
                ),
                "(untitled)",
            )
            lines.append(
                f"{index}. {item.get('updated_at', '')} · {first_user}"
            )
        return "\n".join(lines)

    def export_session(self):
        if not self.conversation:
            messagebox.showinfo("Export conversation", "The current conversation is empty.", parent=self)
            return
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = OUTPUTS_DIR / f"agent_conversation_{timestamp}.md"
        lines = ["# iface Agent conversation", ""]
        for item in self.conversation:
            title = "User" if item.get("role") == "user" else "Agent"
            lines.extend([f"## {title}", "", str(item.get("content") or ""), ""])
        path.write_text("\n".join(lines), encoding="utf-8")
        self.status.set(f"Conversation exported: {path}")
        messagebox.showinfo("Export conversation", f"Exported to: \n{path}", parent=self)

    def _handle_local_command(self, request_text):
        command = request_text.strip().lower()
        if command == "/resume":
            self.resume_last_session()
            return True
        if command == "/history":
            self._append_chat("Agent", self.history_summary(), persist=False)
            return True
        if command == "/export":
            self.export_session()
            return True
        if command in {"/new", "/clear"}:
            self.new_session()
            return True
        return False

    def _start_progress(self):
        if not self.progress.winfo_ismapped():
            self.progress.pack(side="right", padx=(8, 12))
        self.progress.start(12)

    def _stop_progress(self):
        self.progress.stop()
        if self.progress.winfo_ismapped():
            self.progress.pack_forget()

    def _show_connected_credentials(self):
        self.api_key_label.grid_remove()
        self.api_key_entry.grid_remove()
        self.key_action_frame.grid_remove()
        self.api_key_help.grid_remove()
        self.connected_frame.grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(0, 10)
        )

    def _show_api_key_editor(self):
        self.connected_frame.grid_remove()
        self.api_key_label.grid()
        self.api_key_entry.grid()
        self.key_action_frame.grid()
        self.api_key_help.grid()
        self.api_key_entry.focus_set()

    def _load_saved_credentials(self, provider=None):
        loader = self.callbacks.get("load_ai_credentials")
        if loader is None:
            self._show_api_key_editor()
            return
        try:
            credentials = loader("DeepSeek")
        except Exception as exc:
            self.api_key.set("")
            self.status.set(f"Could not read saved API key: {exc}")
            self._show_api_key_editor()
            return
        chosen = "DeepSeek"
        definition = PROVIDERS[chosen]
        self.provider.set(chosen)
        self.model_combo.configure(values=definition["models"])
        self.model.set(
            credentials.get("model")
            or definition["default_model"]
        )
        self.api_key.set(credentials.get("api_key") or "")
        if self.api_key.get():
            self.connected_label.configure(
                text=f"{chosen} API key saved and ready"
            )
            self.status.set("API key loaded from local secure storage.")
            self._show_connected_credentials()
        else:
            self.connected_label.configure(text=f"{chosen} API connected")
            self._show_api_key_editor()

    def save_api_key(self):
        key = self.api_key.get().strip()
        if not key:
            messagebox.showwarning(
                "API key required",
                f"Enter {self.provider.get()} API key.",
                parent=self,
            )
            return
        saver = self.callbacks.get("save_ai_credentials")
        if saver is None:
            messagebox.showerror(
                "Cannot save key",
                "Local secure storage is unavailable in this installation.",
                parent=self,
            )
            return
        try:
            saver(self.provider.get(), self.model.get().strip(), key)
        except Exception as exc:
            messagebox.showerror("Could not save key", str(exc), parent=self)
            return
        self.connected_label.configure(
            text=f"{self.provider.get()} API key saved and ready"
        )
        self.status.set(f"API key saved with {KEY_STORAGE_LABEL}.")
        self._show_connected_credentials()

    def forget_saved_api_key(self):
        remover = self.callbacks.get("remove_ai_credentials")
        if remover is None:
            self._show_api_key_editor()
            return
        if not messagebox.askyesno(
            "Remove saved API key",
            f"Delete the locally saved {self.provider.get()} API key?",
            parent=self,
        ):
            return
        try:
            remover(self.provider.get())
        except Exception as exc:
            messagebox.showerror("Could not remove key", str(exc), parent=self)
            return
        self.api_key.set("")
        self.status.set("Saved API key removed.")
        self._show_api_key_editor()

    def test_api_key(self):
        if self.worker and self.worker.is_alive():
            return
        if not self.api_key.get().strip():
            messagebox.showwarning(
                "API key required",
                f"Enter {self.provider.get()} API key.",
                parent=self,
            )
            return
        provider = self.provider.get()
        model = self.model.get().strip()
        self.status.set(f"Validating with {provider} API…")
        self._start_progress()
        self.worker = threading.Thread(
            target=self._test_worker,
            args=(self.api_key.get().strip(), provider, model),
            daemon=True,
        )
        self.worker.start()

    def _test_worker(self, key, provider, model):
        try:
            from app.core.ai_provider import request_json

            response = request_json(
                provider,
                key,
                model,
                "Output strict JSON only.",
                'Return {"status":"ok"}.',
                timeout_seconds=30,
            )
            self.messages.put(("test_ok", response.get("model", provider)))
        except Exception as exc:
            self.messages.put(("test_error", str(exc)))

    def execute_selected(self):
        if not self.plan:
            messagebox.showinfo("No plan", "Ask Agent to prepare a plan first.", parent=self)
            return
        selected = list(self.table.selection())
        if not selected:
            messagebox.showinfo("Nothing selected", "Select the tool actions to execute.", parent=self)
            return
        actions = [self.plan.actions[int(item)] for item in selected]
        preview = "\n".join(
            f"{index + 1}. {action.tool}({RISK_LABELS.get(action.risk, action.risk)})"
            for index, action in enumerate(actions)
        )
        if not messagebox.askyesno(
            "Confirm Agent tool calls",
            "Agent will execute these actions in order: \n\n" + preview + "\n\nContinue?",
            parent=self,
        ):
            return
        completed = 0
        execution_report = []
        for iid, action in zip(selected, actions):
            try:
                result = self.callbacks["execute_agent_action"](action)
                text = self._result_text(result)
                values = list(self.table.item(iid, "values"))
                values[4] = text
                self.table.item(iid, values=values)
                completed += 1
                execution_report.append(
                    f"{action.tool}: {self._result_text(result, limit=4000)}"
                )
            except Exception as exc:
                values = list(self.table.item(iid, "values"))
                values[4] = "Failed: " + str(exc)
                self.table.item(iid, values=values)
                execution_report.append(f"{action.tool} Failed: {exc}")
                break
        self.status.set(f"Executed {completed}/{len(actions)} Agent actions.")
        if execution_report:
            self._append_chat(
                "Agent",
                "Result: \n" + "\n".join(execution_report),
            )

    @staticmethod
    def _result_text(result, limit=500):
        if isinstance(result, (dict, list, tuple)):
            return json.dumps(result, ensure_ascii=False)[:limit]
        return str(result or "Completed")[:limit]

    def _poll(self):
        while not self.messages.empty():
            kind, payload = self.messages.get_nowait()
            self.plan_button.configure(state="normal")
            self._stop_progress()
            if kind == "test_ok":
                self._show_connected_credentials()
                self.status.set(f"API key valid · {payload}")
                messagebox.showinfo("DeepSeek API", "Connected. The API key is valid.", parent=self)
                continue
            if kind == "test_error":
                self.status.set("API key test failed.")
                messagebox.showerror(
                    "DeepSeek API",
                    payload + "\n\nCheck the API key and system network/proxy settings.",
                    parent=self,
                )
                continue
            if kind == "error":
                self.status.set("Agent planning failed.")
                self._append_chat("Agent", f"Request failed: {payload}")
                messagebox.showerror("iface Agent", payload, parent=self)
                continue
            self.plan = payload
            self._show_connected_credentials()
            reply = payload.message
            if payload.warnings:
                reply += "\n\n" + "\n".join(
                    "Warning: " + value for value in payload.warnings
                )
            self._append_chat("Agent", reply)
            action_count = len(payload.actions)
            if action_count:
                self.result_frame.configure(
                    text=f"Agent tool calls ({action_count} actions; confirmation required)"
                )
                self.result_frame.grid()
                self.execute_button.pack(side="left", padx=8)
            else:
                self.result_frame.grid_remove()
                self.execute_button.pack_forget()
            for index, action in enumerate(payload.actions):
                self.table.insert(
                    "",
                    "end",
                    iid=str(index),
                    values=(
                        action.tool,
                        RISK_LABELS.get(action.risk, action.risk),
                        json.dumps(action.arguments, ensure_ascii=False),
                        action.reason,
                        "Waiting to execute",
                    ),
                )
            # All validated actions are selected so the user only needs to
            # review the visible risk/parameters and confirm once.
            if payload.actions:
                self.table.selection_set(
                    *(str(index) for index in range(len(payload.actions)))
                )
            tokens = payload.usage.get("total_tokens")
            self.status.set(
                f"{payload.model} planned {len(payload.actions)} actions"
                + (f" · {tokens} tokens" if tokens is not None else "")
            )
        self._poll_id = self.after(250, self._poll)

    def _close(self):
        self._save_session()
        self.api_key.set("")
        self._stop_progress()
        if self._poll_id:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        self.destroy()
