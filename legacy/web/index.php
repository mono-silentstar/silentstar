<?php
declare(strict_types=1);

require_once __DIR__ . '/lib/auth.php';

mono_session_start();
$loggedIn = mono_is_logged_in();
$loginError = isset($_GET['login_error']) && $_GET['login_error'] === '1';
$hashConfigured = mono_auth_hash_configured();
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>silentstar</title>
  <style>
    :root {
      --bg: #f3f2ef;
      --ink: #111;
      --panel: #fff;
      --line: #ddd;
      --accent: #0b6;
      --warn: #c0392b;
      --muted: #666;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, -apple-system, Segoe UI, Helvetica, Arial, sans-serif;
      color: var(--ink);
      background: radial-gradient(circle at 0 0, #fff, #f4f1ea 50%, #ece8df 100%);
      min-height: 100vh;
    }
    .wrap {
      max-width: 780px;
      margin: 24px auto;
      padding: 0 16px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 16px;
      box-shadow: 0 6px 26px rgba(0,0,0,0.05);
    }
    .chat-shell {
      display: flex;
      flex-direction: column;
      gap: 12px;
      min-height: calc(100vh - 160px);
    }
    h1 { margin: 0 0 12px; font-size: 1.2rem; }
    .small { color: var(--muted); font-size: 0.9rem; }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .tag-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 10px;
      margin-top: 10px;
    }
    .tag-card {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      background: #faf9f7;
    }
    .tag-card legend {
      padding: 0 4px;
      font-size: 0.85rem;
      font-weight: 600;
      color: #333;
    }
    .tag-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-top: 4px;
    }
    .tag-list label {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 0.92rem;
      color: #222;
    }
    .tag-list input[type="radio"],
    .tag-list input[type="checkbox"] {
      margin: 0;
    }
    .tag-actions {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      margin-top: 8px;
    }
    .ghost-link {
      border: 0;
      background: transparent;
      color: #2d5eaa;
      cursor: pointer;
      padding: 0;
      font: inherit;
      text-decoration: underline;
    }
    input[type=password], textarea, input[type=file] {
      width: 100%;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      font: inherit;
      background: #fff;
    }
    textarea { min-height: 110px; resize: vertical; }
    button {
      border: 0;
      border-radius: 8px;
      padding: 10px 14px;
      font: inherit;
      cursor: pointer;
      background: #111;
      color: #fff;
    }
    button.secondary { background: #555; }
    button[disabled] { opacity: 0.5; cursor: not-allowed; }
    .status { display: inline-flex; align-items: center; gap: 8px; }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 99px;
      background: var(--warn);
      display: inline-block;
    }
    .dot.online { background: var(--accent); }
    .log {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      min-height: 180px;
      flex: 1 1 auto;
      overflow-y: auto;
      background: #fcfcfc;
      white-space: pre-wrap;
    }
    #chat-form {
      position: sticky;
      bottom: 0;
      background: var(--panel);
      padding-top: 8px;
      border-top: 1px solid var(--line);
    }
    .err { color: var(--warn); }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="panel">
      <h1>silentstar</h1>
      <?php if (!$hashConfigured): ?>
        <p class="err">Password hash is not configured. Set <code>app_password_hash</code> in <code>config.local.php</code>.</p>
      <?php endif; ?>

      <?php if (!$loggedIn): ?>
        <p class="small">Enter password to access chat.</p>
        <?php if ($loginError): ?>
          <p class="err">Invalid password.</p>
        <?php endif; ?>
        <form method="post" action="api/login.php">
          <input type="password" name="password" placeholder="Password" required />
          <div style="margin-top:10px">
            <button type="submit" <?php echo $hashConfigured ? '' : 'disabled'; ?>>Login</button>
          </div>
        </form>
      <?php else: ?>
        <div class="chat-shell">
          <div class="row" style="justify-content:space-between;">
            <div class="status"><span id="bridge-dot" class="dot"></span><span id="bridge-text">Checking bridge...</span></div>
            <form method="post" action="api/logout.php"><button class="secondary" type="submit">Logout</button></form>
          </div>

          <div id="log" class="log"></div>

          <form id="chat-form" enctype="multipart/form-data">
            <textarea id="message" name="message" placeholder="Type your message..."></textarea>
            <input id="image" type="file" name="image" accept="image/*" />

            <div class="tag-grid">
              <fieldset class="tag-card">
                <legend>Identity</legend>
                <div class="tag-list" id="identity-tags">
                  <label><input type="radio" name="identity_tag" value="mono" checked>mono</label>
                  <label><input type="radio" name="identity_tag" value="hasuki">hasuki</label>
                  <label><input type="radio" name="identity_tag" value="renki">renki</label>
                  <label><input type="radio" name="identity_tag" value="luna">luna</label>
                  <label><input type="radio" name="identity_tag" value="chloe">chloe</label>
                  <label><input type="radio" name="identity_tag" value="strah">strah</label>
                  <label><input type="radio" name="identity_tag" value="claude">claude</label>
                  <label><input type="radio" name="identity_tag" value="y'lhara">y'lhara</label>
                </div>
                <div class="tag-actions">
                  <span class="small">One at a time</span>
                  <button id="identity-clear" class="ghost-link" type="button">Clear</button>
                </div>
              </fieldset>

              <fieldset class="tag-card">
                <legend>Content</legend>
                <div class="tag-list">
                  <label><input type="checkbox" name="content_tag" value="plan">plan</label>
                  <label><input type="checkbox" name="content_tag" value="secret">secret</label>
                </div>
                <div class="tag-actions">
                  <span class="small">Behavioral tags</span>
                </div>
              </fieldset>

              <fieldset class="tag-card">
                <legend>Display</legend>
                <div class="tag-list">
                  <label><input type="checkbox" name="display_tag" value="say">say</label>
                  <label><input type="checkbox" name="display_tag" value="rp">rp</label>
                  <label><input type="checkbox" name="display_tag" value="nr">nr</label>
                </div>
                <div class="tag-actions">
                  <span class="small">Archival only</span>
                </div>
              </fieldset>
            </div>

            <div class="row" style="margin-top:10px">
              <button id="send-btn" type="submit">Send</button>
              <span class="small" id="send-state">Idle</span>
            </div>
          </form>
        </div>
      <?php endif; ?>
    </div>
  </div>

<?php if ($loggedIn): ?>
<script>
(() => {
  const form = document.getElementById('chat-form');
  const messageEl = document.getElementById('message');
  const imageEl = document.getElementById('image');
  const sendBtn = document.getElementById('send-btn');
  const sendState = document.getElementById('send-state');
  const logEl = document.getElementById('log');
  const bridgeDot = document.getElementById('bridge-dot');
  const bridgeText = document.getElementById('bridge-text');
  const identityClearBtn = document.getElementById('identity-clear');

  let bridgeOnline = false;
  let pollingJob = null;

  function appendLog(line, isErr = false) {
    const ts = new Date().toLocaleTimeString();
    const prefix = `[${ts}] `;
    const text = `${prefix}${isErr ? 'ERROR: ' : ''}${line}`;
    logEl.textContent += (logEl.textContent ? "\n\n" : "") + text;
    logEl.scrollTop = logEl.scrollHeight;
  }

  function selectedValues(selector) {
    return Array.from(document.querySelectorAll(selector))
      .filter(el => el.checked)
      .map(el => el.value);
  }

  if (identityClearBtn) {
    identityClearBtn.addEventListener('click', () => {
      document.querySelectorAll('input[name="identity_tag"]').forEach(el => {
        el.checked = false;
      });
    });
  }

  async function refreshBridgeState() {
    try {
      const r = await fetch('api/bridge_state.php', { credentials: 'same-origin' });
      const j = await r.json();
      bridgeOnline = !!(j && j.ok && j.online);
      bridgeDot.classList.toggle('online', bridgeOnline);
      bridgeText.textContent = bridgeOnline
        ? (j.busy ? 'Bridge online (busy)' : 'Bridge online (ready)')
        : 'Bridge offline';
    } catch (err) {
      bridgeOnline = false;
      bridgeDot.classList.remove('online');
      bridgeText.textContent = 'Bridge check failed';
    }
  }

  async function pollJob(jobId) {
    pollingJob = jobId;
    sendState.textContent = 'Waiting for Claude...';

    while (pollingJob === jobId) {
      await new Promise(r => setTimeout(r, 1200));
      try {
        const r = await fetch(`api/status.php?id=${encodeURIComponent(jobId)}`, { credentials: 'same-origin' });
        const j = await r.json();
        if (!j || !j.ok || !j.job) {
          sendState.textContent = 'Failed to read job status';
          appendLog('Failed to read job status.', true);
          pollingJob = null;
          return;
        }

        bridgeOnline = !!j.online;
        bridgeDot.classList.toggle('online', bridgeOnline);
        bridgeText.textContent = bridgeOnline
          ? (j.busy ? 'Bridge online (busy)' : 'Bridge online (ready)')
          : 'Bridge offline';

        const st = j.job.status;
        if (st === 'queued' || st === 'running') {
          sendState.textContent = `Job ${st}...`;
          continue;
        }
        if (st === 'done') {
          const reply = j.job.reply_hidden
            ? '[secret response hidden]'
            : (j.job.reply_text || '(empty reply)');
          appendLog(`Claude: ${reply}`);
          sendState.textContent = 'Done';
          pollingJob = null;
          return;
        }

        const err = j.job.error_message || 'Unknown error';
        appendLog(`Error: ${err}`, true);
        sendState.textContent = 'Error';
        pollingJob = null;
        return;
      } catch (err) {
        appendLog('Status polling failed.', true);
        sendState.textContent = 'Status failed';
        pollingJob = null;
        return;
      }
    }
  }

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (pollingJob) {
      appendLog('A turn is already in progress.', true);
      return;
    }

    const message = messageEl.value.trim();
    const file = imageEl.files[0] || null;

    if (!message && !file) {
      appendLog('Message or image is required.', true);
      return;
    }

    if (!bridgeOnline) {
      appendLog('Bridge offline. Turn rejected.', true);
      return;
    }

    sendBtn.disabled = true;
    sendState.textContent = 'Submitting...';

    const fd = new FormData();
    fd.append('message', message);
    if (file) fd.append('image', file);
    const identity = document.querySelector('input[name="identity_tag"]:checked');
    const contentTags = selectedValues('input[name="content_tag"]:checked');
    const displayTags = selectedValues('input[name="display_tag"]:checked');
    if (identity && identity.value) {
      fd.append('actor', identity.value);
    }
    contentTags.forEach(tag => {
      fd.append('content_tags[]', tag);
    });
    displayTags.forEach(tag => {
      fd.append('display_tags[]', tag);
    });

    try {
      const r = await fetch('api/submit.php', {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
      });
      const j = await r.json();
      if (!j || !j.ok) {
        appendLog(`Submit failed: ${j?.error || 'unknown_error'}`, true);
        sendState.textContent = 'Submit failed';
        return;
      }

      const tagParts = [];
      if (identity && identity.value) tagParts.push(identity.value);
      tagParts.push(...contentTags);
      tagParts.push(...displayTags);
      const tagPrefix = tagParts.length ? `[${tagParts.join(', ')}] ` : '';
      const userLine = file
        ? `You: ${tagPrefix}${message || '[image only]'} (image: ${file.name})`
        : `You: ${tagPrefix}${message}`;
      appendLog(userLine);
      messageEl.value = '';
      imageEl.value = '';
      await pollJob(j.job_id);
    } catch (err) {
      appendLog('Submit request failed.', true);
      sendState.textContent = 'Submit request failed';
    } finally {
      sendBtn.disabled = false;
    }
  });

  setInterval(refreshBridgeState, 2000);
  refreshBridgeState();
})();
</script>
<?php endif; ?>
</body>
</html>
