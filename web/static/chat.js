/*
 * chat.js — interaction layer
 *
 * Tag insertion, identity selection, image upload,
 * form submission, auto-scroll, bridge status polling.
 */

(function () {
  'use strict';

  // --- Elements ---
  const chatArea    = document.getElementById('chat-area');
  const chatLog     = document.getElementById('chat-log');
  const form        = document.getElementById('chat-form');
  const msgInput    = document.getElementById('msg-input');
  const imageInput  = document.getElementById('image-input');
  const imageBtn    = document.getElementById('image-btn');
  const imagePreview = document.getElementById('image-preview');
  const previewImg  = document.getElementById('preview-img');
  const removeImage = document.getElementById('remove-image');
  const sendBtn     = document.getElementById('send-btn');
  const bridgeDot   = document.getElementById('bridge-dot');
  const bridgeLabel = document.getElementById('bridge-label');

  if (!form || !msgInput) return;

  // --- State ---
  let identity = null;   // current fronting identity, or null for "mono"
  let tagState = {};      // { plan: false, pin: false }
  let bridgeOnline = false;
  let submitting = false;

  // --- Identity chips ---
  document.querySelectorAll('.identity-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const val = chip.dataset.identity;
      if (identity === val) {
        // Deselect
        identity = null;
        chip.classList.remove('active');
      } else {
        // Select this one, deselect others
        document.querySelectorAll('.identity-chip').forEach(c => c.classList.remove('active'));
        identity = val;
        chip.classList.add('active');
      }
    });
  });

  // --- Tag toggles ---
  document.querySelectorAll('.tag-toggle').forEach(btn => {
    const tag = btn.dataset.tag;
    tagState[tag] = false;

    btn.addEventListener('click', () => {
      if (tagState[tag]) {
        // Close tag
        insertAtCursor(`</${tag}>`);
        tagState[tag] = false;
        btn.classList.remove(`active-${tag}`);
      } else {
        // Open tag
        insertAtCursor(`<${tag}>`);
        tagState[tag] = true;
        btn.classList.add(`active-${tag}`);
      }
      msgInput.focus();
    });
  });

  function insertAtCursor(text) {
    const start = msgInput.selectionStart;
    const end = msgInput.selectionEnd;
    const before = msgInput.value.substring(0, start);
    const after = msgInput.value.substring(end);
    msgInput.value = before + text + after;
    const newPos = start + text.length;
    msgInput.setSelectionRange(newPos, newPos);
    autoResize();
  }

  // --- Auto-resize textarea ---
  function autoResize() {
    msgInput.style.height = 'auto';
    msgInput.style.height = Math.min(msgInput.scrollHeight, 200) + 'px';
  }

  msgInput.addEventListener('input', autoResize);

  // --- Image upload ---
  imageBtn.addEventListener('click', () => {
    imageInput.click();
  });

  imageInput.addEventListener('change', () => {
    const file = imageInput.files[0];
    if (file) {
      imageBtn.classList.add('has-file');
      previewImg.src = URL.createObjectURL(file);
      imagePreview.classList.add('visible');
    } else {
      clearImage();
    }
  });

  removeImage.addEventListener('click', () => {
    clearImage();
  });

  function clearImage() {
    imageInput.value = '';
    imageBtn.classList.remove('has-file');
    imagePreview.classList.remove('visible');
    if (previewImg.src.startsWith('blob:')) {
      URL.revokeObjectURL(previewImg.src);
    }
    previewImg.src = '';
  }

  // --- Form submission ---
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (submitting) return;

    // Close any open tags
    for (const [tag, open] of Object.entries(tagState)) {
      if (open) {
        msgInput.value += `</${tag}>`;
        tagState[tag] = false;
        const btn = document.querySelector(`.tag-toggle[data-tag="${tag}"]`);
        if (btn) btn.classList.remove(`active-${tag}`);
      }
    }

    const message = msgInput.value.trim();
    const hasImage = imageInput.files.length > 0;

    if (!message && !hasImage) return;

    if (!bridgeOnline) {
      showError('bridge offline');
      return;
    }

    submitting = true;
    sendBtn.disabled = true;

    const fd = new FormData();
    fd.append('message', message);
    if (identity) fd.append('actor', identity);
    // Extract tags that were used in the message
    const usedTags = [];
    if (message.includes('<plan>')) usedTags.push('plan');
    if (message.includes('<pin>')) usedTags.push('pin');
    usedTags.forEach(t => fd.append('tags[]', t));
    if (hasImage) fd.append('image', imageInput.files[0]);

    try {
      const resp = await fetch('api/submit.php', {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
      });
      const data = await resp.json();

      if (!data || !data.ok) {
        showError(data?.error || 'submit failed');
        return;
      }

      // Show Mono's message immediately
      appendMonoMessage(message, identity, usedTags, hasImage ? imageInput.files[0] : null);

      // Clear input
      msgInput.value = '';
      autoResize();
      clearImage();

      // Start polling for response
      appendPending(data.job_id);

    } catch (err) {
      showError('connection failed');
    } finally {
      submitting = false;
      sendBtn.disabled = false;
    }
  });

  // Ctrl+Enter / Cmd+Enter to send
  msgInput.addEventListener('keydown', (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') {
      ev.preventDefault();
      form.dispatchEvent(new Event('submit'));
    }
  });

  // --- Rendering ---

  function appendMonoMessage(text, actor, tags, imageFile) {
    const div = document.createElement('div');
    div.className = 'turn';

    const actorName = actor || 'mono';
    const tagPills = tags.map(t => `<span class="tag-pill">${esc(t)}</span>`).join('');

    let imageHtml = '';
    if (imageFile) {
      const url = URL.createObjectURL(imageFile);
      imageHtml = `<div class="msg-image"><img src="${url}" alt="" loading="lazy"></div>`;
    }

    // Render inline tags for display
    let bodyHtml = esc(text)
      .replace(/&lt;plan&gt;(.*?)&lt;\/plan&gt;/gs, '<span class="inline-tag inline-plan">$1</span>')
      .replace(/&lt;pin&gt;(.*?)&lt;\/pin&gt;/gs, '<span class="inline-tag inline-pin">$1</span>');
    bodyHtml = bodyHtml.replace(/\n/g, '<br>');

    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase();

    div.innerHTML = `
      <div class="msg mono">
        <span class="actor" data-actor="${esc(actorName)}">${esc(actorName)}</span>
        ${imageHtml}
        <div class="body">${bodyHtml}</div>
        <div class="msg-meta">${tagPills}<time>${timeStr}</time></div>
      </div>
    `;

    chatLog.appendChild(div);
    scrollToBottom();
  }

  function appendPending(jobId) {
    const div = document.createElement('div');
    div.id = 'pending-turn';
    div.className = 'turn pending';
    div.innerHTML = '<div class="breathing"></div>';

    // HTMX attributes for polling
    div.setAttribute('hx-get', `api/status.php?id=${jobId}&format=html`);
    div.setAttribute('hx-trigger', 'every 1.2s');
    div.setAttribute('hx-swap', 'outerHTML');

    chatLog.appendChild(div);
    scrollToBottom();

    // Tell HTMX to process the new element
    if (window.htmx) {
      htmx.process(div);
    }
  }

  function showError(msg) {
    const div = document.createElement('div');
    div.className = 'turn error-turn';
    div.innerHTML = `<p class="error-msg">${esc(msg)}</p>`;
    chatLog.appendChild(div);
    scrollToBottom();
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      chatArea.scrollTop = chatArea.scrollHeight;
    });
  }

  function esc(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }

  // --- Bridge status polling ---

  async function checkBridge() {
    try {
      const resp = await fetch('api/bridge_state.php', { credentials: 'same-origin' });
      const data = await resp.json();
      bridgeOnline = !!(data && data.ok && data.online);
    } catch {
      bridgeOnline = false;
    }
    bridgeDot.classList.toggle('online', bridgeOnline);
    bridgeLabel.textContent = bridgeOnline ? 'connected' : 'offline';
  }

  setInterval(checkBridge, 3000);
  checkBridge();

  // --- HTMX events ---
  // Auto-scroll when HTMX swaps in new content (completed responses)

  document.body.addEventListener('htmx:afterSwap', (ev) => {
    scrollToBottom();
  });

  // Scroll to bottom after initial history load
  document.body.addEventListener('htmx:afterSettle', (ev) => {
    if (ev.detail.target && ev.detail.target.id === 'chat-log') {
      scrollToBottom();
    }
  });

  // --- Init ---

  // Scroll to bottom on load (after history loads)
  scrollToBottom();

})();
