import * as vscode from 'vscode';
import * as path from 'node:path';
import * as fs from 'node:fs';
import { spawn } from 'node:child_process';

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

class ResultItem extends vscode.TreeItem {
  constructor(label: string, description?: string, icon?: string, command?: vscode.Command) {
    super(label, vscode.TreeItemCollapsibleState.None);
    this.description = description;
    this.tooltip = description ? `${label}: ${description}` : label;
    this.iconPath = icon ? new vscode.ThemeIcon(icon) : undefined;
    this.command = command;
  }
}

class Results implements vscode.TreeDataProvider<ResultItem> {
  private readonly changed = new vscode.EventEmitter<ResultItem | undefined>();
  readonly onDidChangeTreeData = this.changed.event;
  private current?: TestResult;
  private caseName?: string;

  set(result: TestResult, caseName: string): void {
    this.current = result;
    this.caseName = caseName;
    this.changed.fire(undefined);
  }

  getTreeItem(item: ResultItem): vscode.TreeItem { return item; }

  getChildren(): ResultItem[] {
    const result = this.current;
    if (!result) return [new ResultItem('Run a saved case to see its result', undefined, 'beaker')];
    const items = [
      new ResultItem(`${result.status}: ${this.caseName}`, result.reason,
        result.status === 'PASS' ? 'pass' : result.status === 'FAIL' ? 'error' : 'warning'),
    ];
    for (const check of result.checks ?? []) {
      const expectation = check.check && typeof check.check === 'object' ? check.check as Record<string, unknown> : {};
      const label = `${String(expectation.kind ?? 'check')}: ${String(expectation.text ?? expectation.url ?? '')}`;
      const actual = String(check.reason ?? (check.passed ? 'passed' : 'failed'));
      items.push(new ResultItem(label, actual, check.passed === false ? 'error' : 'check'));
    }
    if (result.final_url) items.push(new ResultItem('Final URL', result.final_url, 'link-external'));
    if (result.elapsed_seconds !== undefined) items.push(new ResultItem('Duration', `${result.elapsed_seconds}s`, 'clock'));
    for (const [name, value] of Object.entries(result.artifacts ?? {})) {
      const files = typeof value === 'string' ? [value] : value;
      for (const file of files) items.push(new ResultItem(`Open ${name}`, file, 'file-media',
        { command: 'testscribe.openArtifact', title: 'Open artifact', arguments: [file] }));
    }
    items.push(new ResultItem('Open full report', result.report_path, 'file-code',
      { command: 'testscribe.openReport', title: 'Open report' }));
    return items;
  }
}

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
    vscode.window.showInformationMessage('No saved TestScribe case found. Run “TestScribe: New Test Case” first.');
    return undefined;
  }
  const picked = await vscode.window.showQuickPick(cases.map(caseUri => ({
    label: path.basename(caseUri.fsPath), description: vscode.workspace.asRelativePath(caseUri), uri: caseUri,
  })), { placeHolder: 'Choose a saved TestScribe case' });
  return picked?.uri;
}

function validateCase(contents: string): void {
  const spec: unknown = JSON.parse(contents);
  if (!spec || typeof spec !== 'object' || Array.isArray(spec)) throw new Error('Case must be a JSON object.');
  const fields = spec as Record<string, unknown>;
  if (typeof fields.url !== 'string' || !/^https?:\/\//.test(fields.url)) throw new Error('Case needs an HTTP(S) url.');
  if (typeof fields.test !== 'string' || !fields.test.trim()) throw new Error('Case needs a nonempty test.');
}

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel('TestScribe');
  const results = new Results();
  context.subscriptions.push(output, vscode.window.registerTreeDataProvider('testscribe.results', results));
  let lastReport: string | undefined;

  async function promptKey(keyName: string): Promise<string | undefined> {
    const key = await vscode.window.showInputBox({ prompt: `Enter ${keyName} for TestScribe`, password: true, ignoreFocusOut: true });
    if (key === undefined) return undefined;
    if (!key.trim()) { vscode.window.showErrorMessage('API key cannot be empty.'); return undefined; }
    await context.secrets.store(`testscribe.${keyName}`, key.trim());
    vscode.window.showInformationMessage(`${keyName} saved in VS Code Secret Storage.`);
    return key.trim();
  }

  context.subscriptions.push(vscode.commands.registerCommand('testscribe.newCase', async () => {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) { vscode.window.showErrorMessage('Open a folder before creating a test case.'); return; }
    const name = await vscode.window.showInputBox({ prompt: 'Case filename', value: 'my-test',
      validateInput: value => /^[a-z0-9][a-z0-9_-]*$/i.test(value) ? undefined : 'Use letters, numbers, hyphens or underscores.' });
    if (!name) return;
    const caseUri = vscode.Uri.joinPath(folder.uri, '.testscribe', `${name}.json`);
    try {
      await vscode.workspace.fs.stat(caseUri);
      vscode.window.showErrorMessage(`Case already exists: ${caseUri.fsPath}`);
      return;
    } catch { /* This is a new case. */ }
    await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(folder.uri, '.testscribe'));
    const template = { url: 'https://example.com', test: 'Describe the actions and expected result here.' };
    await vscode.workspace.fs.writeFile(caseUri, Buffer.from(`${JSON.stringify(template, null, 2)}\n`));
    await vscode.window.showTextDocument(caseUri);
  }));

  context.subscriptions.push(vscode.commands.registerCommand('testscribe.setApiKey', async () => {
    const keyName = vscode.workspace.getConfiguration('testscribe').get<string>('apiKeyEnv', 'BHARATCODE_API_KEY');
    await promptKey(keyName);
  }));

  context.subscriptions.push(vscode.commands.registerCommand('testscribe.openReport', async () => {
    if (!lastReport) { vscode.window.showInformationMessage('Run a case first.'); return; }
    await vscode.window.showTextDocument(vscode.Uri.file(lastReport));
  }));

  context.subscriptions.push(vscode.commands.registerCommand('testscribe.openArtifact', async (file: string) => {
    if (file.endsWith('.zip')) await vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(file));
    else await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(file));
  }));

  context.subscriptions.push(vscode.commands.registerCommand('testscribe.runCase', async (uri?: vscode.Uri) => {
    const caseUri = await chooseCase(uri);
    if (!caseUri) return;
    try { validateCase(Buffer.from(await vscode.workspace.fs.readFile(caseUri)).toString('utf8')); }
    catch (error) { vscode.window.showErrorMessage(`Invalid TestScribe case: ${String(error)}`); return; }
    const folder = workspaceFor(caseUri);
    const config = vscode.workspace.getConfiguration('testscribe', caseUri);
    const keyName = config.get<string>('apiKeyEnv', 'BHARATCODE_API_KEY');
    let secret = await context.secrets.get(`testscribe.${keyName}`);
    const hasDotEnv = fs.existsSync(path.join(folder?.uri.fsPath ?? path.dirname(caseUri.fsPath), '.env'));
    if (!secret && !process.env[keyName] && !hasDotEnv) {
      const choice = await vscode.window.showWarningMessage(`${keyName} is missing.`, 'Set API Key');
      if (choice !== 'Set API Key') return;
      secret = await promptKey(keyName);
      if (!secret) return;
    }
    const runDir = vscode.Uri.joinPath(context.globalStorageUri, 'runs', `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`);
    await vscode.workspace.fs.createDirectory(runDir);
    const args = ['run', '--case-file', caseUri.fsPath, '--json', '--output-dir', runDir.fsPath,
      '--model', config.get<string>('model', 'qwen-3.8-27b'),
      '--base-url', config.get<string>('baseUrl', 'https://bharatcode.ai/api/model/v1'),
      '--api-key-env', keyName];
    if (config.get<boolean>('headed', false)) args.push('--headed');
    output.appendLine(`Running ${caseUri.fsPath}`);
    try {
    const result = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification,
      title: `TestScribe: ${path.basename(caseUri.fsPath)}`, cancellable: true }, (progress, token) =>
      new Promise<TestResult>((resolve, reject) => {
        const child = spawn(executable(folder), args, { cwd: folder?.uri.fsPath ?? path.dirname(caseUri.fsPath),
          env: { ...process.env, ...(secret ? { [keyName]: secret } : {}) }, shell: false });
        let stdout = '';
        let stderr = '';
        token.onCancellationRequested(() => child.kill());
        child.stdout.on('data', chunk => { stdout += chunk.toString(); });
        child.stderr.on('data', chunk => { stderr += chunk.toString(); });
        child.on('error', reject);
        child.on('close', code => {
          if (token.isCancellationRequested) { reject(new Error('Test cancelled.')); return; }
          try {
            const report = JSON.parse(stdout.trim()) as TestResult;
            if (!['PASS', 'FAIL', 'BLOCKED'].includes(report.status) || !report.report_path) throw new Error('Invalid result from CLI.');
            resolve(report);
          } catch {
            reject(new Error(`TestScribe exited ${code}: ${stderr.trim() || stdout.trim() || 'No output'}`));
          }
        });
      }));
    lastReport = result.report_path;
    results.set(result, path.basename(caseUri.fsPath));
    output.appendLine(`${result.status}: ${result.reason}`);
    output.appendLine(`Report: ${lastReport}`);
    const message = `${result.status}: ${result.reason}`;
    if (result.status === 'PASS') vscode.window.showInformationMessage(message, 'Open Report').then(choice => {
      if (choice) vscode.commands.executeCommand('testscribe.openReport');
    });
    else vscode.window.showWarningMessage(message, 'Open Report').then(choice => {
      if (choice) vscode.commands.executeCommand('testscribe.openReport');
    });
    } catch (error) {
      output.appendLine(`Error: ${String(error)}`);
      output.show(true);
      vscode.window.showErrorMessage(`TestScribe could not run: ${String(error)}`);
    }
  }));
}

export function deactivate(): void { /* Child processes are tied to individual commands. */ }
