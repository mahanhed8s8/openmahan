# OpenMahan
OpenMahan is a small terminal/GU-powered shell assistant that talks to an Ollama chat model, executes safe commands, and explains the result back to you.
## Key Features
- **Ollama chat** · Uses `https://ollama.com/api/chat`, accepts both `OLLAMA_API_KEY` or `OPENMAHAN_API_KEY`, normalizes URLs, trims long outputs, and guards against dangerous commands.
- **Three interaction modes** · Terminal (`python openmahan.py`), Textual super mode (`--super`), and a polished dark/glass GUI (`--gui`). GUI assets (`openmahan.ui`) are embedded via `resource_path()` for PyInstaller bundles.
- **Safe command handling** · Detects destructive patterns (`rm -rf`, `format`, etc.), warns you before running, and explains the results.
- **Standalone Windows exe** · `dist/OpenMahan.exe` includes the UI file and icon, so it runs even if the workspace assets vanish.
## Requirements
- Python 3.14+ (3.14.3 tested)
- `rich`, `PyQt6`, `textual`, `requests`, `pyinstaller`, `pillow`
Install the dependencies with your preferred toolchain, for example:
```powershell
pip install rich PyQt6 textual requests pyinstaller pillow
```
## Configuration
- `OLLAMA_API_KEY` / `OPENMAHAN_API_KEY`: Ollama bearer token.
- `OLLAMA_BASE_URL` / `OPENMAHAN_URL`: Base URL or `/api/chat` endpoint (e.g. `https://ollama.com/api/chat`).
- `OPENMAHAN_MODEL`: Override default `gpt-oss:120b`.
These can also be provided as flags (`--api-key`, `--url`, `--model`, `--timeout`).
## Running
```powershell
python openmahan.py                  # terminal AI assistant
python openmahan.py --gui            # dark/glass PyQt GUI
python openmahan.py --super          # textual interface with F1/F2/F3 shortcuts
```
The GUI now provides a clean header, expanded chat pane, and floating input row with soft drop shadows and a matte background instead of glowing glass.
## Building the Executable
```powershell
pyinstaller openmahan.py --onefile --icon=openmahan.png --name=OpenMahan --add-data "openmahan.ui;."
```
`dist/OpenMahan.exe` contains the `.ui` file and icon so it runs even without the assets on disk. Just copy the exe somewhere safe and set your Ollama env vars before launching.
## Notes
- The GUI, terminal, and super mode share the same asking/execution pipeline.
- Dangerous commands require explicit confirmation when detected.
- If you move the exe to another machine, don’t forget to export `OLLAMA_API_KEY`.
## Troubleshooting
- Missing Pillow while building exe? `pip install pillow`
- Icon errors? Provide an `.ico` or keep the bundled PNG (PyInstaller auto-converts with Pillow).
- PyQt6 import issues? Reinstall with `pip install PyQt6`.
Need a zip or installer on top of the exe? Just ask.
