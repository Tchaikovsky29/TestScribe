(() => {
  const vscode = acquireVsCodeApi();
  const conversation = document.getElementById('conversation');
  const target = document.getElementById('target');
  const prompt = document.getElementById('prompt');
  const model = document.getElementById('model');
  const send = document.getElementById('send');
  const save = document.getElementById('save');
  const cancel = document.getElementById('cancel');
  const notice = document.getElementById('notice');
  let busy = false;
  let lastTest = '';
  let noticeTimer;

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  }

  function scrollToEnd() { conversation.scrollTop = conversation.scrollHeight; }

  function showNotice(text) {
    notice.textContent = text;
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => { notice.textContent = ''; }, 6500);
  }

  function welcome() {
    const wrapper = node('div', 'welcome');
    wrapper.id = 'welcome';
    wrapper.append(node('div', 'welcome-mark', '✳'));
    wrapper.append(node('h1', '', 'What should we test?'));
    wrapper.append(node('p', '', 'Describe a browser flow in plain English. TestScribe will run it and check the result on the page.'));
    wrapper.append(node('div', 'example-label', 'Try an example'));
    const examples = [
      {
        label: 'Submit a form and check the response',
        url: 'https://www.selenium.dev/selenium/web/web-form.html',
        test: 'Enter TestScribe into the Text input field, submit the form, and verify that Received! appears.',
      },
      {
        label: 'Check a website navigation flow',
        url: 'https://phptravels.com/demo',
        test: 'Open the storefront from the demo page and verify a flight search option is shown.',
      },
    ];
    for (const example of examples) {
      const button = node('button', 'example');
      button.type = 'button';
      button.append(node('span', '', '↗'), node('span', '', example.label));
      button.addEventListener('click', () => {
        target.value = example.url;
        prompt.value = example.test;
        prompt.focus();
      });
      wrapper.append(button);
    }
    return wrapper;
  }

  function header(role, assistant) {
    const line = node('div', 'message-header');
    line.append(node('span', 'avatar ' + (assistant ? 'assistant' : 'user'), assistant ? '✳' : '●'));
    line.append(node('span', '', role));
    return line;
  }

  function description(check) {
    const detail = check && typeof check.check === 'object' && check.check ? check.check : {};
    if (detail.text) return String(detail.text);
    if (detail.url) return String(detail.url);
    if (detail.kind) return String(detail.kind).replaceAll('_', ' ');
    return 'Expected result';
  }

  function resultCard(result) {
    const status = ['PASS', 'FAIL', 'BLOCKED'].includes(result.status) ? result.status : 'BLOCKED';
    const card = node('div', 'result-card ' + status.toLowerCase());
    const head = node('div', 'result-head');
    head.append(node('div', 'status-mark', status === 'PASS' ? '✓' : status === 'FAIL' ? '×' : '!'));
    head.append(node('div', 'result-title', status));
    card.append(head);
    card.append(node('div', 'result-reason', result.reason || 'The browser run has finished.'));

    const steps = Array.isArray(result.steps) ? result.steps : [];
    const checks = Array.isArray(result.checks) ? result.checks : [];
    const stats = node('div', 'result-stats');
    const stepStat = node('span');
    stepStat.append(node('strong', '', steps.length), document.createTextNode(' actions'));
    const checkStat = node('span');
    checkStat.append(node('strong', '', checks.length), document.createTextNode(' checks'));
    stats.append(stepStat, checkStat);
    if (typeof result.elapsed_seconds === 'number') {
      const elapsed = node('span');
      elapsed.append(node('strong', '', result.elapsed_seconds.toFixed(1) + 's'), document.createTextNode(' elapsed'));
      stats.append(elapsed);
    }
    card.append(stats);

    if (checks.length) {
      const section = node('div', 'section');
      section.append(node('div', 'section-title', 'Assertions'));
      for (const check of checks) {
        const row = node('div', 'check');
        row.append(node('span', 'check-icon' + (check.passed === false ? ' failed' : ''), check.passed === false ? '×' : '✓'));
        const content = node('div');
        content.append(node('div', 'check-text', description(check)));
        if (check.reason) content.append(node('div', 'check-detail', check.reason));
        row.append(content);
        section.append(row);
      }
      card.append(section);
    }

    if (steps.length) {
      const details = node('details', 'section');
      details.append(node('summary', '', 'Browser actions (' + steps.length + ')'));
      for (const [index, step] of steps.entries()) {
        const row = node('div', 'step');
        row.append(node('span', 'step-num', index + 1));
        row.append(node('div', 'step-text', step.instruction || [step.action, step.target].filter(Boolean).join(' · ') || 'Action'));
        details.append(row);
      }
      card.append(details);
    }

    const actions = node('div', 'section report-actions');
    const reportButton = node('button', 'link-button', 'Open full report ↗');
    reportButton.type = 'button';
    reportButton.addEventListener('click', () => vscode.postMessage({ type: 'openReport', path: result.report_path }));
    actions.append(reportButton);
    if (result.artifacts && typeof result.artifacts === 'object') {
      for (const [name, value] of Object.entries(result.artifacts)) {
        const files = typeof value === 'string' ? [value] : Array.isArray(value) ? value : [];
        for (const file of files) {
          if (typeof file !== 'string') continue;
          const button = node('button', 'link-button', 'Open ' + name + ' ↗');
          button.type = 'button';
          button.addEventListener('click', () => vscode.postMessage({ type: 'openArtifact', path: file }));
          actions.append(button);
        }
      }
    }
    card.append(actions);
    return card;
  }

  function render(entry) {
    const message = node('article', 'message');
    message.dataset.id = String(entry.id);
    if (entry.kind === 'user') {
      message.append(header('You', false));
      message.append(node('div', 'user-bubble', entry.text));
      message.append(node('div', 'user-url', entry.url));
    } else {
      message.append(header('TestScribe', true));
      const body = node('div', 'assistant-body');
      if (entry.kind === 'pending') {
        const row = node('div', 'pending-row');
        row.append(node('span', 'spinner'));
        const label = node('span', '', 'Planning and running in Chromium…');
        row.append(label);
        const started = Date.now();
        const timer = setInterval(() => {
          if (!message.isConnected) { clearInterval(timer); return; }
          label.textContent = 'Planning and running in Chromium… ' + Math.floor((Date.now() - started) / 1000) + 's';
        }, 1000);
        body.append(row);
      } else if (entry.kind === 'result') {
        body.append(resultCard(entry.result));
      } else {
        body.append(node('div', 'error-card', entry.text));
      }
      message.append(body);
    }
    return message;
  }

  function setBusy(value) {
    busy = Boolean(value);
    send.classList.toggle('hidden', busy);
    cancel.classList.toggle('hidden', !busy);
    save.disabled = busy;
  }

  function submit() {
    if (busy) return;
    const url = target.value.trim();
    const test = prompt.value.trim();
    if (!/^https?:\/\//i.test(url)) { showNotice('Enter a full URL starting with http:// or https://.'); target.focus(); return; }
    if (!test) { showNotice('Describe the browser actions and expected result.'); prompt.focus(); return; }
    notice.textContent = '';
    lastTest = test;
    vscode.postMessage({ type: 'run', url, test });
    prompt.value = '';
  }

  window.addEventListener('message', event => {
    const message = event.data;
    if (!message || typeof message !== 'object') return;
    if (message.type === 'init') {
      conversation.replaceChildren();
      if (Array.isArray(message.entries) && message.entries.length) {
        for (const entry of message.entries) conversation.append(render(entry));
      } else conversation.append(welcome());
      if (message.url) target.value = message.url;
      const lastUser = Array.isArray(message.entries) ? [...message.entries].reverse().find(entry => entry.kind === 'user') : undefined;
      if (lastUser) lastTest = lastUser.text;
      model.textContent = message.model ? 'Model · ' + message.model : '';
      setBusy(message.busy);
      scrollToEnd();
    } else if (message.type === 'entry') {
      document.getElementById('welcome')?.remove();
      if (message.entry.kind === 'user') lastTest = message.entry.text;
      conversation.append(render(message.entry));
      scrollToEnd();
    } else if (message.type === 'replace') {
      const existing = Array.from(conversation.children).find(element => element.dataset.id === String(message.entry.id));
      if (existing) existing.replaceWith(render(message.entry));
      scrollToEnd();
    } else if (message.type === 'busy') {
      setBusy(message.busy);
      if (message.url) target.value = message.url;
    } else if (message.type === 'notice') showNotice(message.text || 'Something went wrong.');
  });

  send.addEventListener('click', submit);
  cancel.addEventListener('click', () => vscode.postMessage({ type: 'cancel' }));
  save.addEventListener('click', () => vscode.postMessage({ type: 'saveCase', url: target.value, test: prompt.value.trim() || lastTest }));
  document.getElementById('settings').addEventListener('click', () => vscode.postMessage({ type: 'openSettings' }));
  prompt.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit(); }
  });
  vscode.postMessage({ type: 'ready' });
})();
