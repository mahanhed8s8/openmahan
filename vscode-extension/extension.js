const vscode = require('vscode');
const path = require('path');

let panel;

function normalizeOllamaUrl(url) {
  if (!url) {
    return 'https://ollama.com/api/chat';
  }

  let cleaned = url.trim();
  if (cleaned.endsWith('/api/chat')) {
    return cleaned;
  }

  return `${cleaned.replace(/\/$/, '')}/api/chat`;
}

async function askModel(text) {
  const config = vscode.workspace.getConfiguration('openMahanChat');
  const url = normalizeOllamaUrl(config.get('url'));
  const model = config.get('model') || 'gpt-oss:120b';
  const timeout = Math.max(5, config.get('timeout') || 45) * 1000;
  const apiKey = config.get('apiKey') || '';

  const headers = {
    'content-type': 'application/json'
  };

  if (apiKey) {
    headers['authorization'] = `Bearer ${apiKey}`;
  }

  try {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), timeout);

    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        model,
        stream: false,
        messages: [
          { role: 'system', content: `You are OpenMahan, a helpful shell assistant.
When the user asks to create or modify files, output the action as a JSON directive:
\`\`\`json
{
  "action": "writeFile",
  "path": "notes/todo.md",
  "content": "- write README\n- build exe"
}
\`\`\`
The VS Code extension will automatically perform the file operations described in the JSON. Wrap additional explanations after the JSON block.`},
          { role: 'user', content: text }
        ]
      }),
      signal: controller.signal
    });

    clearTimeout(id);

    const data = await response.json();
    if (data?.message?.content) {
      return data.message.content;
    }

    if (Array.isArray(data?.choices) && data.choices[0]?.message?.content) {
      return data.choices[0].message.content;
    }

    return data?.response || JSON.stringify(data, null, 2);
 } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error('Request timed out.');
    }
    throw error;
  }
}

function getWorkspaceRootPath() {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    return null;
  }
  return folders[0].uri.fsPath;
}

function resolveTargetPath(relativePath) {
  if (!relativePath) {
    throw new Error('Provide a path to operate on.');
  }
  const cleaned = relativePath.trim();
  if (path.isAbsolute(cleaned)) {
    return path.normalize(cleaned);
  }
  const root = getWorkspaceRootPath();
  if (!root) {
    throw new Error('Open a folder in VS Code before running file operations.');
  }
  return path.join(root, cleaned);
}

async function handleFsAction(action, targetPath, content = '') {
  const absolutePath = resolveTargetPath(targetPath);
  const uri = vscode.Uri.file(absolutePath);
  switch (action) {
    case 'readFile': {
      const data = await vscode.workspace.fs.readFile(uri);
      return Buffer.from(data).toString('utf-8');
    }
    case 'writeFile': {
      const dir = path.dirname(absolutePath);
      await vscode.workspace.fs.createDirectory(vscode.Uri.file(dir));
      await vscode.workspace.fs.writeFile(uri, Buffer.from(content ?? '', 'utf-8'));
      return `Wrote ${content?.length || 0} bytes to ${targetPath}`;
    }
    case 'deleteFile': {
      await vscode.workspace.fs.delete(uri, { recursive: false, useTrash: false });
      return `Deleted file ${targetPath}`;
    }
    case 'createFolder': {
      await vscode.workspace.fs.createDirectory(uri);
      return `Created folder ${targetPath}`;
    }
    case 'deleteFolder': {
      await vscode.workspace.fs.delete(uri, { recursive: true, useTrash: false });
      return `Deleted folder ${targetPath}`;
    }
    case 'listFolder': {
      const entries = await vscode.workspace.fs.readDirectory(uri);
      if (!entries.length) {
        return `Folder ${targetPath} is empty.`;
      }
      return entries
        .map(([name, fileType]) => `${name} (${fileType === vscode.FileType.Directory ? 'dir' : 'file'})`)
        .join('\n');
    }
    default:
      throw new Error('Unknown file action.');
  }
}

function extractDirective(reply) {
  const jsonBlock = reply.match(/```json\s*([\s\S]+?)```/i);
  let payload = jsonBlock?.[1]?.trim();
  if (!payload) {
    const firstObject = reply.match(/({[\s\S]+})/);
    payload = firstObject?.[1];
  }
  if (!payload) {
    return null;
  }

  try {
    const parsed = JSON.parse(payload);
    if (parsed && parsed.action) {
      return parsed;
    }
  } catch (error) {
    console.error('Failed to parse AI directive', error);
  }

  return null;
}

function getWebviewContent(webview) {
  const nonce = Math.random().toString(36).slice(2);
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}'; style-src 'unsafe-inline';" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>OpenMahan Chat</title>
  <style>
    body {
      margin: 0;
      font-family: 'Segoe UI', sans-serif;
      background: radial-gradient(circle at top, #1f2335, #0a0c14 75%);
      color: #efeff4;
      display: flex;
      flex-direction: column;
      height: 100vh;
    }
    .header {
      padding: 16px 20px;
      font-size: 1.1rem;
      letter-spacing: 0.3px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .header span {
      font-weight: 600;
    }
    .chat {
      flex: 1;
      overflow-y: auto;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .bubble {
      max-width: 80%;
      padding: 14px 16px;
      border-radius: 16px;
      backdrop-filter: blur(12px);
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.08);
    }
    .bubble.user {
      background: rgba(96, 132, 255, 0.25);
      align-self: flex-end;
    }
    .bubble.ai {
      background: rgba(255,255,255,0.06);
      align-self: flex-start;
    }
    .input-row {
      display: flex;
      border-top: 1px solid rgba(255,255,255,0.08);
      padding: 12px 20px;
      gap: 10px;
    }
    .input-row textarea {
      flex: 1;
      min-height: 60px;
      border-radius: 16px;
      padding: 12px;
      border: 1px solid rgba(255,255,255,0.2);
      background: rgba(20,24,36,0.8);
      color: #f7f8ff;
      font-size: 13px;
      resize: none;
    }
    .input-row button {
      border: none;
      border-radius: 14px;
      padding: 0 28px;
      background: linear-gradient(135deg, #7d8cff, #5f71ff);
      color: #fff;
      font-weight: 600;
      cursor: pointer;
      transition: opacity 0.2s ease;
    }
    .input-row button:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
    .fs-panel {
      margin: 0 20px 12px;
      padding: 14px 16px;
      border-radius: 16px;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.08);
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .fs-row {
      display: flex;
      gap: 10px;
    }
    .fs-row select,
    .fs-row input {
      flex: 1;
      border-radius: 12px;
      border: 1px solid rgba(255,255,255,0.2);
      background: rgba(20,24,36,0.8);
      padding: 8px 12px;
      color: #fff;
    }
    .fs-panel textarea {
      border-radius: 12px;
      border: 1px solid rgba(255,255,255,0.2);
      background: rgba(10, 14, 24, 0.9);
      color: #f7f8ff;
      min-height: 80px;
      padding: 10px;
      font-size: 12px;
      font-family: 'JetBrains Mono', 'Segoe UI', monospace;
    }
    .fs-controls {
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 0.9rem;
      color: rgba(255,255,255,0.75);
    }
    .fs-controls button {
      border-radius: 12px;
      padding: 6px 18px;
      border: none;
      background: linear-gradient(135deg, #63ffb7, #2fa1ff);
      color: #05070c;
      font-weight: 600;
      cursor: pointer;
    }
    .fs-controls span {
      flex: 1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
  </style>
</head>
<body>
  <div class="header">
    <span>OpenMahan Chat</span>
    <small>Ask a command or conversation</small>
  </div>
    <div class="chat" id="chat"></div>
    </div>
    <div class="input-row">
      <textarea id="prompt" placeholder="Type a question..."></textarea>
      <button id="send">Send</button>
    </div>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const chat = document.getElementById('chat');
    const prompt = document.getElementById('prompt');
    const send = document.getElementById('send');
    const fsAction = document.getElementById('fsAction');
    const fsPath = document.getElementById('fsPath');
    const fsContent = document.getElementById('fsContent');
    const fsExecute = document.getElementById('fsExecute');
    const fsResult = document.getElementById('fsResult');

    function appendBubble(text, type='ai') {
      const el = document.createElement('div');
      el.className = 'bubble ' + type;
      el.textContent = text;
      chat.appendChild(el);
      chat.scrollTop = chat.scrollHeight;
    }

    send.addEventListener('click', () => {
      const value = prompt.value.trim();
      if (!value) {
        return;
      }
      appendBubble(value, 'user');
      vscode.postMessage({ type: 'send', payload: value });
      prompt.value = '';
      send.disabled = true;
    });

    fsExecute.addEventListener('click', () => {
      const targetPath = fsPath.value.trim();
      if (!targetPath) {
        fsResult.textContent = 'Enter a path before executing.';
        return;
      }

      vscode.postMessage({
        type: 'fsAction',
        payload: {
          action: fsAction.value,
          targetPath,
          content: fsContent.value
        }
      });
      fsResult.textContent = 'Running…';
    });

    window.addEventListener('message', (event) => {
      const message = event.data;
      if (message.type === 'reply') {
        appendBubble(message.payload, 'ai');
        send.disabled = false;
      }
      if (message.type === 'error') {
        appendBubble('Error: ' + message.payload, 'ai');
        send.disabled = false;
      }
      if (message.type === 'fsResult') {
        fsResult.textContent = message.payload;
      }
    });
  </script>
</body>
</html>`;
}

function createPanel() {
  panel = vscode.window.createWebviewPanel('openMahanChat', 'OpenMahan Chat', vscode.ViewColumn.One, {
    enableScripts: true,
    retainContextWhenHidden: true
  });

  panel.webview.html = getWebviewContent(panel.webview);

  panel.onDidDispose(() => {
    panel = undefined;
  });

  panel.webview.onDidReceiveMessage(async (message) => {
    if (message.type === 'send') {
      try {
        const text = message.payload;
        const reply = await askModel(text);
        const directive = extractDirective(reply);
        if (directive) {
          try {
            const actionResult = await handleFsAction(
              directive.action,
              directive.path || directive.targetPath || '',
              directive.content || ''
            );
            panel?.webview.postMessage({ type: 'fsResult', payload: `AI auto-action: ${actionResult}` });
          } catch (actionError) {
            panel?.webview.postMessage({ type: 'fsResult', payload: `Auto-action failed: ${actionError.message}` });
          }
        }
        panel?.webview.postMessage({ type: 'reply', payload: reply });
      } catch (error) {
        panel?.webview.postMessage({ type: 'error', payload: error.message });
      }
      return;
    }

    if (message.type === 'fsAction') {
      try {
        const result = await handleFsAction(
          message.payload.action,
          message.payload.targetPath,
          message.payload.content
        );
        panel?.webview.postMessage({ type: 'fsResult', payload: result });
      } catch (error) {
        panel?.webview.postMessage({ type: 'error', payload: error.message });
      }
    }
  });
}

function activate(context) {
  context.subscriptions.push(vscode.commands.registerCommand('openmahan.openChat', () => {
    if (panel) {
      panel.reveal(vscode.ViewColumn.One);
    } else {
      createPanel();
    }
  }));
}

function deactivate() {
  if (panel) {
    panel.dispose();
  }
}

module.exports = { activate, deactivate };
