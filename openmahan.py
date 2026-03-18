import sys
import requests
import subprocess
import re
import argparse
import os
from dataclasses import dataclass
from rich.console import Console

console = Console()

DEFAULT_OLLAMA_URL = "https://ollama.com/api/chat"
DEFAULT_MODEL = "gpt-oss:120b"
DEFAULT_TIMEOUT = 45
MAX_OUTPUT_CHARS = 6000

BANNER = """
╔██████╗ ██████╗ ███████╗███╗   ██╗███╗   ███╗ █████╗ ██╗  ██╗ █████╗ ███╗   ██╗
██╔═══██╗██╔══██╗██╔════╝████╗  ██║████╗ ████║██╔══██╗██║  ██║██╔══██╗████╗  ██║
██║   ██║██████╔╝█████╗  ██╔██╗ ██║██╔████╔██║███████║███████║███████║██╔██╗ ██║
██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██║╚██╔╝██║██╔══██║██╔══██║██╔══██║██║╚██╗██║
╚██████╔╝██║     ███████╗██║ ╚████║██║ ╚═╝ ██║██║  ██║██║  ██║██║  ██║██║ ╚████║
 ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝
"""

SYSTEM_PROMPT = """
You are OpenMahan, a terminal AI assistant.

You help users by executing terminal commands.

If you want to execute a command reply with along with your message:

<RUN_COMMAND>
command
</RUN_COMMAND>

If you want the user to execute 

Rules:
- Only one command per responce
- Greet the user if needed
"""


@dataclass
class RuntimeConfig:
    ollama_url: str
    timeout_seconds: int
    api_key: str | None


RUNTIME = RuntimeConfig(
    ollama_url=os.getenv("OPENMAHAN_URL", os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_URL)),
    timeout_seconds=DEFAULT_TIMEOUT,
    api_key=os.getenv("OPENMAHAN_API_KEY", os.getenv("OLLAMA_API_KEY")),
)
MODEL = os.getenv("OPENMAHAN_MODEL", DEFAULT_MODEL)


def resource_path(relative_path: str) -> str:
    if getattr(sys, "frozen", False):
        base_path = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(base_path, relative_path)


def normalize_ollama_url(url):
    cleaned = (url or "").strip().rstrip("/")
    if cleaned.endswith("/api/chat"):
        return cleaned
    return f"{cleaned}/api/chat"


def ask_model(prompt, model=None):

    model_name = model or MODEL
    url = normalize_ollama_url(RUNTIME.ollama_url)
    headers = {}
    if RUNTIME.api_key:
        headers["Authorization"] = f"Bearer {RUNTIME.api_key}"

    if "ollama.com" in url and not RUNTIME.api_key:
        return "[Model error] Missing API key. Set OLLAMA_API_KEY or pass --api-key for ollama.com."

    try:
        r = requests.post(
            url,
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT.strip()},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
            },
            headers=headers,
            timeout=RUNTIME.timeout_seconds,
        )
        r.raise_for_status()
    except requests.RequestException as exc:
        return f"[Model error] {exc}"

    try:
        data = r.json()
    except ValueError:
        return "[Model error] Invalid JSON response from server."

    if "message" in data and isinstance(data["message"], dict):
        return data["message"].get("content", str(data))

    if "choices" in data and data["choices"]:
        first = data["choices"][0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                return message.get("content", str(data))

    return data.get("response", str(data))


def clean_assistant_text(text):
    return re.sub(r"<RUN_COMMAND>.*?</RUN_COMMAND>", "", text, flags=re.DOTALL).strip()


def trim_output(output):
    if len(output) <= MAX_OUTPUT_CHARS:
        return output
    return output[:MAX_OUTPUT_CHARS] + "\n\n[output truncated]"


def extract_command(text):

    matches = re.findall(
        r"<RUN_COMMAND>(.*?)</RUN_COMMAND>",
        text,
        re.DOTALL
    )

    if matches:
        return matches[0].strip()

    return None


def is_dangerous_command(cmd):
    dangerous_patterns = [
        r"\brm\s+-rf\b",
        r"\bdel\b",
        r"\bformat\b",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bmkfs\b",
    ]
    lowered = cmd.lower()
    return any(re.search(pattern, lowered) for pattern in dangerous_patterns)


def run_command(cmd, allow_dangerous=False):

    if is_dangerous_command(cmd) and not allow_dangerous:
        return "[Command blocked] Potentially destructive command requires explicit approval."

    console.print(f"[yellow]⚡ Running:[/yellow] {cmd}")

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "[Command error] Command timed out after 60 seconds."
    except Exception as exc:
        return f"[Command error] {exc}"

    output = result.stdout + result.stderr
    return output or "[No output]"


def explain_command_result(user_text, cmd, output, model=None):
    explanation_prompt = f"""
User asked:
{user_text}

The command executed was:
{cmd}

Output:
{trim_output(output)}

Explain the result to the user briefly.
"""
    return ask_model(explanation_prompt, model=model)


def terminal_mode():

    console.print(BANNER, style="bold cyan")
    console.print("[green]OpenMahan Terminal Mode[/green]\n")

    history = ""

    while True:

        user_input = input("> ")

        if user_input.lower() in ["exit", "quit"]:
            break

        prompt = history + f"\nUser: {user_input}\nAssistant:"

        response = ask_model(prompt)

        cmd = extract_command(response)

        if cmd:

            allow_dangerous = False

            if is_dangerous_command(cmd):
                console.print(f"[red]Potentially dangerous command detected:[/red] {cmd}")
                confirm = input("Run anyway? (y/N): ").strip().lower()
                allow_dangerous = confirm == "y"

            output = run_command(cmd, allow_dangerous=allow_dangerous)

            response = explain_command_result(user_input, cmd, output)

        clean_response = clean_assistant_text(response)

        console.print(f"\n[cyan]{clean_response}[/cyan]\n")

        history += f"\nUser: {user_input}\nAssistant: {clean_response}"


def super_mode():

    from textual.app import App, ComposeResult
    from textual.widgets import Header, Footer, Input, RichLog, Static
    from textual.containers import Horizontal, Vertical
    from rich.text import Text
    import threading

    class OpenMahanTUI(App):

        BINDINGS = [
            ("f1", "switch_qwen", "Qwen"),
            ("f2", "switch_minimax", "Minimax"),
            ("f3", "clear_chat", "Clear Chat"),
        ]

        CSS = """
        Screen {
            layout: vertical;
        }

        #main {
            height: 1fr;
        }

        #sidebar {
            width: 30;
            border: solid blue;
        }

        #chat {
            border: solid green;
        }

        #commands {
            height: 8;
            border: solid yellow;
        }

        Input {
            dock: bottom;
        }
        """

        def __init__(self):
            super().__init__()
            self.history = ""

        def compose(self) -> ComposeResult:
            yield Header()

            with Horizontal(id="main"):

                with Vertical(id="sidebar"):
                    self.status = Static("Model: qwen3-coder-next")
                    yield self.status
                    yield Static("F1 → Qwen")
                    yield Static("F2 → Minimax")
                    yield Static("F3 → Clear")

                with Vertical():
                    self.chat = RichLog(id="chat")
                    yield self.chat

                    self.commands = RichLog(id="commands")
                    yield self.commands

            self.input = Input(placeholder="Ask OpenMahan...")
            yield self.input

            yield Footer()

        def on_input_submitted(self, message: Input.Submitted):

            user_text = message.value.strip()

            if not user_text:
                return

            self.chat.write(Text(f"You: {user_text}", style="cyan"))
            self.input.value = ""

            threading.Thread(
                target=self.run_ai,
                args=(user_text,),
                daemon=True
            ).start()

        def strip_run_command(self, text):
            return re.sub(
                r"<RUN_COMMAND>.*?</RUN_COMMAND>",
                "",
                text,
                flags=re.DOTALL
            ).strip()

        def run_ai(self, user_text):

            import time

            prompt = self.history + f"\nUser: {user_text}\nAssistant:"

            # start thinking animation
            self._thinking = True

            def animate():
                dots = 1
                while self._thinking:
                    msg = "AI is thinking" + "." * dots
                    self.call_from_thread(self.status.update, msg)
                    dots = (dots % 3) + 1
                    time.sleep(0.5)

            threading.Thread(target=animate, daemon=True).start()

            # run the model
            response = ask_model(prompt)

            # stop animation
            self._thinking = False

            # restore status
            self.call_from_thread(self.status.update, f"Model: {MODEL}")

            clean_response = clean_assistant_text(response)

            # print final response
            self.call_from_thread(
                self.chat.write,
                Text(f"AI: {clean_response}", style="green")
            )

            cmd = extract_command(response)

            if cmd:

                self.call_from_thread(
                    self.commands.write,
                    Text(f"$ {cmd}", style="yellow")
                )

                output = run_command(cmd)

                self.call_from_thread(
                    self.commands.write,
                    Text(output, style="white")
                )

            self.history += f"\nUser: {user_text}\nAssistant: {clean_response}"

        def action_switch_qwen(self):
            global MODEL
            MODEL = "qwen3-coder-next:cloud"
            self.status.update("Model: qwen3-coder-next")

        def action_switch_minimax(self):
            global MODEL
            MODEL = "minimax-m2.5:cloud"
            self.status.update("Model: minimax-m2.5")

        def action_clear_chat(self):
            self.chat.clear()
            self.commands.clear()
            self.history = ""

    OpenMahanTUI().run()

def gui_mode():

    import sys
    import threading
    from PyQt6 import uic
    from PyQt6.QtCore import pyqtSignal, Qt
    from PyQt6.QtGui import QColor, QFont
    from PyQt6.QtWidgets import (
        QApplication,
        QMainWindow,
        QGraphicsDropShadowEffect,
    )

    class OpenMahanGUI(QMainWindow):

        ai_response_ready = pyqtSignal(str)

        def __init__(self):
            super().__init__()

            uic.loadUi(resource_path("openmahan.ui"), self)

            self.setWindowTitle("OpenMahan · LLM Co-Pilot")
            self.history = ""

            self.pushButton.clicked.connect(self.send_message)
            self.lineEdit.returnPressed.connect(self.send_message)
            self.ai_response_ready.connect(self.append_ai_message)

            self.comboBox.setFont(QFont("Segoe UI", 10))
            self.lineEdit.setPlaceholderText("Ask a question or request a command...")
            self.statusbar.showMessage("Model ready — choose a model or ask a question")

            self.apply_theme()
            self.install_shadows()

        def append_ai_message(self, message):
            self.textBrowser.append(message)

        def install_shadows(self):
            for widget in (self.textBrowser, self.lineEdit, self.pushButton):
                effect = QGraphicsDropShadowEffect(self)
                effect.setColor(QColor(0, 0, 0, 140))
                effect.setBlurRadius(14)
                effect.setOffset(0, 2)
                widget.setGraphicsEffect(effect)

        def apply_theme(self):
            theme = """
            QMainWindow {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1,
                    stop:0 #05060a, stop:0.4 #0c0f1c, stop:1 #111720);
            }
            QWidget#centralwidget {
                background: rgba(4, 6, 12, 0.55);
                border-radius: 24px;
                padding: 16px;
            }
            QLabel#label {
                color: #f5f7ff;
                font-size: 22pt;
                font-weight: 600;
                font-family: "Space Grotesk", "Segoe UI", sans-serif;
            }
            QTextBrowser {
                background: rgba(28, 35, 56, 0.78);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 24px;
                padding: 16px;
                color: #f3f6ff;
                font-size: 13pt;
                font-family: "JetBrains Mono", "Segoe UI", monospace;
            }
            QTextBrowser#textBrowser {
                min-height: 360px;
            }
            QLineEdit {
                background: rgba(32, 38, 66, 0.7);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 20px;
                padding: 12px 16px;
                color: #e8ecff;
                font-size: 11pt;
            }
            QPushButton#pushButton {
                border-radius: 20px;
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7d8cff, stop:1 #5b6bff);
                color: white;
                font-weight: 600;
                font-size: 11pt;
                padding: 12px 24px;
            }
            QPushButton#pushButton:hover {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0,
                    stop:0 #9fabff, stop:1 #7b87ff);
            }
            QComboBox {
                background: rgba(19, 26, 48, 0.8);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 18px;
                color: #f5f7ff;
                padding: 4px 8px;
            }
            QStatusBar {
                background: transparent;
                color: rgba(248, 250, 255, 0.7);
            }
            """
            self.setStyleSheet(theme)

        def send_message(self):

            user_text = self.lineEdit.text().strip()

            if not user_text:
                return

            self.textBrowser.append(f"You: {user_text}")
            self.lineEdit.clear()

            threading.Thread(
                target=self.run_ai,
                args=(user_text,),
                daemon=True
            ).start()

        def run_ai(self, user_text):

            # get model from combo box
            model = self.comboBox.currentText()

            prompt = self.history + f"\nUser: {user_text}\nAssistant:"

            response = ask_model(prompt, model=model)

            cmd = extract_command(response)

            if cmd:

                output = run_command(cmd)

                response = explain_command_result(user_text, cmd, output, model=model)

            clean_response = clean_assistant_text(response)

            self.history += f"\nUser: {user_text}\nAssistant: {clean_response}"

            self.ai_response_ready.emit(f"AI: {clean_response}\n")


    app = QApplication(sys.argv)

    window = OpenMahanGUI()
    window.show()

    sys.exit(app.exec())


def main():

    global MODEL

    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()

    group.add_argument(
        "--gui",
        action="store_true",
    )
    group.add_argument(
        "--super",
        action="store_true",
    )
    parser.add_argument(
        "--url",
        default=RUNTIME.ollama_url,
        help="Ollama base URL or /api/chat URL",
    )
    parser.add_argument(
        "--model",
        default=MODEL,
        help="Default model name",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=RUNTIME.timeout_seconds,
        help="Model request timeout in seconds",
    )
    parser.add_argument(
        "--api-key",
        default=RUNTIME.api_key,
        help="Optional bearer token for remote Ollama",
    )

    args = parser.parse_args()

    MODEL = args.model
    RUNTIME.ollama_url = normalize_ollama_url(args.url)
    RUNTIME.timeout_seconds = max(5, args.timeout)
    RUNTIME.api_key = args.api_key

    if args.gui:
        gui_mode()
    elif args.super:
        super_mode()
    else:
        terminal_mode()


if __name__ == "__main__":
    main()
