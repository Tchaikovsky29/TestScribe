import * as vscode from 'vscode';
import * as path from 'node:path';
import * as fs from 'node:fs';
import { randomBytes } from 'node:crypto';
import { spawn, ChildProcess } from 'node:child_process';

type TestResult = {
  status: 'PASS' | 'FAIL' | 'BLOCKED';
  reason: string;
  report_path: string;
  final_url?: string;
  checks?: Array<Record<string, unknown>>;
  steps?: Array<Record<string, unknown>>;
  elapsed_seconds?: number;
  artifacts?: Record<string, string | string[]>;
};

type ChatEntry =
  | { id: number; kind: 'user'; text: string; url: string }
  | { id: number; kind: 'pending'; text: string }
  | { id: number; kind: 'error'; text: string }
  | { id: number; kind: 'result'; result: TestResult };

type RunRequest = { url: string; test: string; caseFile?: string; folder?: vscode.WorkspaceFolder };

function executable(folder: vscode.WorkspaceFolder | undefined): string {
  const configured = vscode.workspace.getConfiguration('testscribe').get<string>('cliPath', '').trim();
  if (configured) return configured;
  if (folder) {
    const candidate = path.join(folder.uri.fsPath, '.venv', process.platform === 'win32' ? 'Scripts/testscribe.exe' : 'bin/testscribe');
    if (fs.existsSync(candidate)) return candidate;
  }
  return 'testscribe';
}

function workspaceFor(uri: vscode.Uri): vscode.WorkspaceFolder | undefined {
  return vscode.workspace.getWorkspaceFolder(uri) ?? vscode.workspace.workspaceFolders?.[0];
}

async function chooseCase(uri?: vscode.Uri): Promise<vscode.Uri | undefined> {
  if (uri?.fsPath.endsWith('.json')) return uri;
  const active = vscode.window.activeTextEditor?.document.uri;
  if (active?.fsPath.endsWith('.json')) return active;
  const cases = await vscode.workspace.findFiles('**/.testscribe/*.json', '**/node_modules/**', 100);
  if (!cases.length) {
    vscode.window.showInformationMessage('No saved TestScribe case found. Enter a test in Chat or run “TestScribe: New Test Case”.');
    return undefined;
  }
  const picked = await vscode.window.showQuickPick(cases.map(caseUri => ({
    label: path.basename(caseUri.fsPath), description: vscode.workspace.asRelativePath(caseUri), uri: caseUri,
  })), { placeHolder: 'Choose a saved TestScribe case' });
  return picked?.uri;
}

function parseCase(contents: string): { url: string; test: string } {
  const spec: unknown = JSON.parse(contents);
  if (!spec || typeof spec !== 'object' || Array.isArray(spec)) throw new Error('Case must be a JSON object.');
  const fields = spec as Record<string, unknown>;
  if (typeof fields.url !== 'string' || !/^https?:\/\//.test(fields.url)) throw new Error('Case needs an HTTP(S) url.');
  if (typeof fields.test !== 'string' || !fields.test.trim()) throw new Error('Case needs a nonempty test.');
  return { url: fields.url, test: fields.test };
}

function validUrl(value: string): boolean {
  try { return ['http:', 'https:'].includes(new URL(value).protocol); }
  catch { return false; }
}

class ChatViewProvider implements vscode.WebviewViewProvider {
  private view?: vscode.WebviewView;
  private entries: ChatEntry[] = [];
  private nextId = 1;
  private currentUrl = '';
  private activeRun?: ChildProcess;
  private lastReport?: string;
  private reports = new Set<string>();
  private artifacts = new Set<string>();

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly output: vscode.OutputChannel,
  ) {}

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, 'resources')],
    };
    view.webview.html = this.html(view.webview);
    view.webview.onDidReceiveMessage(async (message: Record<string, unknown>) => {
      try {
        switch (message.type) {
          case 'ready':
            this.post({ type: 'init', entries: this.entries, url: this.currentUrl,
              model: vscode.workspace.getConfiguration('testscribe').get<string>('model', 'qwen-3.8-27b'),
              busy: Boolean(this.activeRun) });
            break;
          case 'run':
            await this.run({ url: String(message.url ?? '').trim(), test: String(message.test ?? '').trim(),
              folder: vscode.workspace.workspaceFolders?.[0] });
            break;
          case 'cancel':
            this.activeRun?.kill();
            break;
          case 'saveCase':
            await this.saveCase(String(message.url ?? '').trim(), String(message.test ?? '').trim());
            break;
          case 'openReport':
            if (typeof message.path === 'string' && this.reports.has(message.path))
              await vscode.window.showTextDocument(vscode.Uri.file(message.path));
            else if (!message.path && this.lastReport)
              await vscode.window.showTextDocument(vscode.Uri.file(this.lastReport));
            break;
          case 'openArtifact':
            if (typeof message.path === 'string' && this.artifacts.has(message.path))
              await this.openArtifact(message.path);
            break;
          case 'openSettings':
            await vscode.commands.executeCommand('workbench.action.openSettings', 'testscribe');
            break;
          case 'setApiKey':
            await vscode.commands.executeCommand('testscribe.setApiKey');
            break;
        }
      } catch (error) {
        this.output.appendLine(`Chat error: ${String(error)}`);
        vscode.window.showErrorMessage(`TestScribe: ${String(error)}`);
        this.post({ type: 'notice', text: String(error) });
      }
    });
  }

  async reveal(): Promise<void> {
    await vscode.commands.executeCommand('testscribe.chat.focus');
  }

  async runSaved(uri: vscode.Uri): Promise<void> {
    let spec: { url: string; test: string };
    try { spec = parseCase(Buffer.from(await vscode.workspace.fs.readFile(uri)).toString('utf8')); }
    catch (error) { vscode.window.showErrorMessage(`Invalid TestScribe case: ${String(error)}`); return; }
    await this.reveal();
    await this.run({ ...spec, caseFile: uri.fsPath, folder: workspaceFor(uri) });
  }

  private post(message: Record<string, unknown>): void {
    void this.view?.webview.postMessage(message);
  }

  private add(entry: ChatEntry): void {
    this.entries.push(entry);
    this.post({ type: 'entry', entry });
  }

  private replace(entry: ChatEntry): void {
    const index = this.entries.findIndex(item => item.id === entry.id);
    if (index >= 0) this.entries[index] = entry;
    this.post({ type: 'replace', entry });
  }

  private async promptKey(keyName: string): Promise<string | undefined> {
    const key = await vscode.window.showInputBox({ prompt: `Enter ${keyName} for TestScribe`, password: true, ignoreFocusOut: true });
    if (key === undefined) return undefined;
    if (!key.trim()) { vscode.window.showErrorMessage('API key cannot be empty.'); return undefined; }
    await this.context.secrets.store(`testscribe.${keyName}`, key.trim());
    vscode.window.showInformationMessage(`${keyName} saved in VS Code Secret Storage.`);
    return key.trim();
  }

  async setApiKey(): Promise<void> {
    const keyName = vscode.workspace.getConfiguration('testscribe').get<string>('apiKeyEnv', 'BHARATCODE_API_KEY');
    await this.promptKey(keyName);
  }

  async openLastReport(): Promise<void> {
    if (!this.lastReport) { vscode.window.showInformationMessage('Run a case first.'); return; }
    await vscode.window.showTextDocument(vscode.Uri.file(this.lastReport));
  }

  async openArtifact(file: string): Promise<void> {
    if (file.endsWith('.zip')) await vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(file));
    else await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(file));
  }

  private async saveCase(url: string, test: string): Promise<void> {
    if (!validUrl(url) || !test) { this.post({ type: 'notice', text: 'Enter a valid website URL and test before saving.' }); return; }
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) { vscode.window.showErrorMessage('Open a folder to save a test case.'); return; }
    const name = await vscode.window.showInputBox({ prompt: 'Case filename', value: 'my-test',
      validateInput: value => /^[a-z0-9][a-z0-9_-]*$/i.test(value) ? undefined : 'Use letters, numbers, hyphens or underscores.' });
    if (!name) return;
    const caseUri = vscode.Uri.joinPath(folder.uri, '.testscribe', `${name}.json`);
    try { await vscode.workspace.fs.stat(caseUri); vscode.window.showErrorMessage(`Case already exists: ${caseUri.fsPath}`); return; }
    catch { /* New case. */ }
    await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(folder.uri, '.testscribe'));
    await vscode.workspace.fs.writeFile(caseUri, Buffer.from(`${JSON.stringify({ url, test }, null, 2)}\n`));
    await vscode.window.showTextDocument(caseUri);
    this.post({ type: 'notice', text: `Saved .testscribe/${name}.json` });
  }

  private async run(request: RunRequest): Promise<void> {
    if (this.activeRun) { this.post({ type: 'notice', text: 'A test is already running. Cancel it or wait for the result.' }); return; }
    if (!validUrl(request.url) || !request.test) {
      this.post({ type: 'notice', text: 'Enter a full http(s) website URL and a test with an expected result.' });
      return;
    }
    const folder = request.folder ?? vscode.workspace.workspaceFolders?.[0];
    const config = vscode.workspace.getConfiguration('testscribe');
    const keyName = config.get<string>('apiKeyEnv', 'BHARATCODE_API_KEY');
    let secret = await this.context.secrets.get(`testscribe.${keyName}`);
    const hasDotEnv = fs.existsSync(path.join(folder?.uri.fsPath ?? path.dirname(request.caseFile ?? ''), '.env'));
    if (!secret && !process.env[keyName] && !hasDotEnv) {
      const choice = await vscode.window.showWarningMessage(`${keyName} is missing.`, 'Set API Key');
      if (choice !== 'Set API Key') return;
      secret = await this.promptKey(keyName);
      if (!secret) return;
    }

    this.currentUrl = request.url;
    const userId = this.nextId++;
    const answerId = this.nextId++;
    this.add({ id: userId, kind: 'user', text: request.test, url: request.url });
    this.add({ id: answerId, kind: 'pending', text: 'Running browser test' });
    this.post({ type: 'busy', busy: true, url: request.url });

    const runDir = vscode.Uri.joinPath(this.context.globalStorageUri, 'runs', `${Date.now()}-${randomBytes(3).toString('hex')}`);
    try {
      await vscode.workspace.fs.createDirectory(runDir);
      const args = ['run', '--json', '--output-dir', runDir.fsPath,
        '--model', config.get<string>('model', 'qwen-3.8-27b'),
        '--base-url', config.get<string>('baseUrl', 'https://bharatcode.ai/api/model/v1'),
        '--api-key-env', keyName];
      if (request.caseFile) args.push('--case-file', request.caseFile);
      else args.push('--url', request.url, '--test', request.test);
      if (config.get<boolean>('headed', false)) args.push('--headed');
      this.output.appendLine(`Running: ${request.test} (${request.url})`);
      const result = await new Promise<TestResult>((resolve, reject) => {
        const child = spawn(executable(folder), args, { cwd: folder?.uri.fsPath ?? path.dirname(request.caseFile ?? ''),
          env: { ...process.env, ...(secret ? { [keyName]: secret } : {}) }, shell: false });
        this.activeRun = child;
        let stdout = '';
        let stderr = '';
        child.stdout.on('data', chunk => { stdout += chunk.toString(); });
        child.stderr.on('data', chunk => { stderr += chunk.toString(); });
        child.on('error', reject);
        child.on('close', code => {
          this.activeRun = undefined;
          try {
            const parsed = JSON.parse(stdout.trim()) as TestResult;
            if (!['PASS', 'FAIL', 'BLOCKED'].includes(parsed.status) || !parsed.report_path) throw new Error('Invalid CLI result.');
            resolve(parsed);
          } catch {
            reject(new Error(`TestScribe exited ${code}: ${stderr.trim() || stdout.trim() || 'No output'}`));
          }
        });
      });
      this.lastReport = result.report_path;
      this.reports.add(result.report_path);
      this.artifacts.clear();
      for (const value of Object.values(result.artifacts ?? {}))
        for (const file of typeof value === 'string' ? [value] : value) this.artifacts.add(file);
      this.replace({ id: answerId, kind: 'result', result });
      this.output.appendLine(`${result.status}: ${result.reason}\nReport: ${result.report_path}`);
    } catch (error) {
      const message = String(error);
      this.replace({ id: answerId, kind: 'error', text: message });
      this.output.appendLine(`Error: ${message}`);
    } finally {
      this.activeRun = undefined;
      this.post({ type: 'busy', busy: false, url: this.currentUrl });
    }
  }

  private html(webview: vscode.Webview): string {
    const nonce = randomBytes(16).toString('base64');
    const css = webview.asWebviewUri(vscode.Uri.joinPath(this.context.extensionUri, 'resources', 'chat.css'));
    const js = webview.asWebviewUri(vscode.Uri.joinPath(this.context.extensionUri, 'resources', 'chat.js'));
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
  <link rel="stylesheet" href="${css}">
  <title>TestScribe Chat</title>
</head>
<body>
  <div class="app">
    <header class="topbar">
      <div class="brand"><div class="brand-icon">✳</div><div><strong>TestScribe</strong><span>Browser testing assistant</span></div></div>
      <button id="settings" class="icon-button" title="TestScribe settings" aria-label="Open settings">⚙</button>
    </header>
    <div class="target-wrap">
      <label for="target">TEST SITE</label>
      <div class="target-row"><span aria-hidden="true">◎</span><input id="target" type="url" placeholder="https://your-app.com" spellcheck="false" autocomplete="url"></div>
      <div id="model" class="model-line"></div>
    </div>
    <main id="conversation" class="conversation" aria-live="polite"></main>
    <footer class="composer-wrap">
      <div id="notice" class="notice" role="status"></div>
      <div class="composer">
        <textarea id="prompt" rows="2" placeholder="Describe what to test and what should happen…" aria-label="Test instruction"></textarea>
        <div class="composer-actions">
          <span class="hint">Enter to run · Shift+Enter for a new line</span>
          <button id="save" class="secondary" title="Save this test as a JSON case">Save</button>
          <button id="send" class="primary" title="Run browser test" aria-label="Run test">Run ↗</button>
          <button id="cancel" class="danger hidden" title="Stop the current run">Stop</button>
        </div>
      </div>
      <div class="footer-note">AI plans actions · Playwright checks the page</div>
    </footer>
  </div>
  <script nonce="${nonce}" src="${js}"></script>
</body>
</html>`;
  }
}

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel('TestScribe');
  const chat = new ChatViewProvider(context, output);
  context.subscriptions.push(output, vscode.window.registerWebviewViewProvider('testscribe.chat', chat, {
    webviewOptions: { retainContextWhenHidden: true },
  }));

  context.subscriptions.push(vscode.commands.registerCommand('testscribe.openChat', () => chat.reveal()));
  context.subscriptions.push(vscode.commands.registerCommand('testscribe.setApiKey', () => chat.setApiKey()));
  context.subscriptions.push(vscode.commands.registerCommand('testscribe.openReport', () => chat.openLastReport()));
  context.subscriptions.push(vscode.commands.registerCommand('testscribe.newCase', async () => {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) { vscode.window.showErrorMessage('Open a folder before creating a test case.'); return; }
    const name = await vscode.window.showInputBox({ prompt: 'Case filename', value: 'my-test',
      validateInput: value => /^[a-z0-9][a-z0-9_-]*$/i.test(value) ? undefined : 'Use letters, numbers, hyphens or underscores.' });
    if (!name) return;
    const caseUri = vscode.Uri.joinPath(folder.uri, '.testscribe', `${name}.json`);
    try { await vscode.workspace.fs.stat(caseUri); vscode.window.showErrorMessage(`Case already exists: ${caseUri.fsPath}`); return; }
    catch { /* New case. */ }
    await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(folder.uri, '.testscribe'));
    await vscode.workspace.fs.writeFile(caseUri, Buffer.from(`${JSON.stringify({ url: 'https://example.com', test: 'Describe the actions and expected result here.' }, null, 2)}\n`));
    await vscode.window.showTextDocument(caseUri);
  }));
  context.subscriptions.push(vscode.commands.registerCommand('testscribe.runCase', async (uri?: vscode.Uri) => {
    const caseUri = await chooseCase(uri);
    if (caseUri) await chat.runSaved(caseUri);
  }));
}

export function deactivate(): void { /* Runs exit when their VS Code host exits. */ }
