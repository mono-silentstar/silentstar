/*
 * chat.js — interaction layer
 *
 * Rich contenteditable input with identity-colored text,
 * format/knowledge buttons, image upload, bridge polling.
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

  // --- Constants ---
  const IDENTITIES = ['hasuki', 'renki', 'luna', 'chloe', 'strah'];
  const FORMATS = ['do', 'narrate'];
  const KNOWLEDGE = ['plan', 'pin'];

  // --- State ---
  let currentIdentity = null;
  let currentFormat = null;
  let currentKnowledge = { plan: false, pin: false };
  let bridgeOnline = false;
  let submitting = false;

  // --- Contenteditable: span management ---

  function createSpan() {
    const span = document.createElement('span');
    applyState(span);
    return span;
  }

  function applyState(span) {
    span.className = '';
    delete span.dataset.identity;
    delete span.dataset.format;
    delete span.dataset.plan;
    delete span.dataset.pin;

    if (currentIdentity) {
      span.dataset.identity = currentIdentity;
      span.classList.add('input-id-' + currentIdentity);
    }
    if (currentFormat) {
      span.dataset.format = currentFormat;
      span.classList.add('input-fmt-' + currentFormat);
    }
    if (currentKnowledge.plan) {
      span.dataset.plan = '1';
      span.classList.add('input-tag-plan');
    }
    if (currentKnowledge.pin) {
      span.dataset.pin = '1';
      span.classList.add('input-tag-pin');
    }
  }

  function isSpanEmpty(span) {
    return span.textContent.replace(/\u200B/g, '').trim() === '';
  }

  function placeCursorIn(span) {
    const sel = window.getSelection();
    const range = document.createRange();
    if (span.lastChild) {
      range.setStartAfter(span.lastChild);
    } else {
      range.setStart(span, 0);
    }
    range.collapse(true);
    sel.removeAllRanges();
    sel.addRange(range);
  }

  function stateMatches(span) {
    const id = span.dataset.identity || null;
    const fmt = span.dataset.format || null;
    const plan = span.dataset.plan === '1';
    const pin = span.dataset.pin === '1';
    return id === currentIdentity && fmt === currentFormat &&
           plan === currentKnowledge.plan && pin === currentKnowledge.pin;
  }

  function findParentSpan(node) {
    // Walk up from node to find a SPAN that is a direct child of msgInput
    while (node && node !== msgInput) {
      if (node.nodeType === Node.ELEMENT_NODE && node.tagName === 'SPAN' &&
          node.parentElement === msgInput) {
        return node;
      }
      node = node.parentNode;
    }
    return null;
  }

  function ensureActiveSpan() {
    const sel = window.getSelection();

    // No selection or not inside input — append at end
    if (!sel.rangeCount || !msgInput.contains(sel.getRangeAt(0).startContainer)) {
      const span = createSpan();
      span.appendChild(document.createTextNode('\u200B'));
      msgInput.appendChild(span);
      placeCursorIn(span);
      return;
    }

    const range = sel.getRangeAt(0);
    const parentSpan = findParentSpan(range.startContainer);

    // Not inside any span (bare text node or msgInput itself) — append new span
    if (!parentSpan) {
      const span = createSpan();
      span.appendChild(document.createTextNode('\u200B'));
      msgInput.appendChild(span);
      placeCursorIn(span);
      return;
    }

    // Span already matches current state — nothing to do
    if (stateMatches(parentSpan)) return;

    // Empty span — update in place
    if (isSpanEmpty(parentSpan)) {
      applyState(parentSpan);
      return;
    }

    // Non-empty span that doesn't match — split at cursor position
    const newSpan = createSpan();
    newSpan.appendChild(document.createTextNode('\u200B'));

    // Check if cursor is at start of span content
    const beforeRange = document.createRange();
    beforeRange.setStart(parentSpan, 0);
    beforeRange.setEnd(range.startContainer, range.startOffset);
    const beforeText = beforeRange.toString().replace(/\u200B/g, '');

    // Check if cursor is at end of span content
    const afterRange = document.createRange();
    afterRange.setStart(range.startContainer, range.startOffset);
    afterRange.setEnd(parentSpan, parentSpan.childNodes.length);
    const afterText = afterRange.toString().replace(/\u200B/g, '');

    if (afterText === '') {
      // Cursor at end — insert new span after as sibling
      parentSpan.after(newSpan);
    } else if (beforeText === '') {
      // Cursor at start — insert new span before as sibling
      parentSpan.before(newSpan);
    } else {
      // Cursor in middle — extract trailing content into a clone span
      const tailRange = document.createRange();
      tailRange.setStart(range.startContainer, range.startOffset);
      tailRange.setEnd(parentSpan, parentSpan.childNodes.length);
      const tailFragment = tailRange.extractContents();

      const afterSpan = document.createElement('span');
      // Copy state from original span (not current state)
      if (parentSpan.dataset.identity) afterSpan.dataset.identity = parentSpan.dataset.identity;
      if (parentSpan.dataset.format) afterSpan.dataset.format = parentSpan.dataset.format;
      if (parentSpan.dataset.plan) afterSpan.dataset.plan = parentSpan.dataset.plan;
      if (parentSpan.dataset.pin) afterSpan.dataset.pin = parentSpan.dataset.pin;
      afterSpan.className = parentSpan.className;
      afterSpan.appendChild(tailFragment);

      // Insert newSpan then afterSpan after the original
      parentSpan.after(newSpan);
      newSpan.after(afterSpan);
    }

    placeCursorIn(newSpan);
  }

  function segmentState(span) {
    return (span.dataset.identity || '') + '|' +
           (span.dataset.format || '') + '|' +
           (span.dataset.plan || '') + '|' +
           (span.dataset.pin || '');
  }

  function normalizeInput() {
    // 1. Flatten nested spans — move inner spans to be siblings
    for (const outer of Array.from(msgInput.querySelectorAll('span span'))) {
      const parent = outer.parentElement;
      if (parent && parent.tagName === 'SPAN' && msgInput.contains(parent)) {
        parent.after(outer);
      }
    }

    // 2. Remove dead spans (ZWS-only, not the one the cursor is in)
    const sel = window.getSelection();
    let cursorSpan = null;
    if (sel.rangeCount) {
      cursorSpan = findParentSpan(sel.getRangeAt(0).startContainer);
    }
    for (const span of Array.from(msgInput.querySelectorAll('span'))) {
      if (span === cursorSpan) continue;
      if (span.parentElement !== msgInput) continue;
      if (isSpanEmpty(span)) span.remove();
    }

    // 3. Merge adjacent spans with identical state
    let child = msgInput.firstElementChild;
    while (child) {
      const next = child.nextElementSibling;
      if (next && child.tagName === 'SPAN' && next.tagName === 'SPAN' &&
          segmentState(child) === segmentState(next)) {
        while (next.firstChild) child.appendChild(next.firstChild);
        next.remove();
        // Don't advance — check the same `child` against its new next sibling
      } else {
        child = next;
      }
    }
  }

  // --- Identity chips ---
  document.querySelectorAll('.identity-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const val = chip.dataset.identity;
      if (currentIdentity === val) {
        currentIdentity = null;
        chip.classList.remove('active');
      } else {
        document.querySelectorAll('.identity-chip').forEach(c => c.classList.remove('active'));
        currentIdentity = val;
        chip.classList.add('active');
      }
      ensureActiveSpan();
      normalizeInput();
      msgInput.focus();
    });
  });

  // --- Format & knowledge buttons ---
  document.querySelectorAll('.tag-toggle').forEach(btn => {
    const tag = btn.dataset.tag;

    btn.addEventListener('click', () => {
      if (FORMATS.includes(tag)) {
        if (currentFormat === tag) {
          currentFormat = null;
          btn.classList.remove('active-' + tag);
        } else {
          FORMATS.forEach(f => {
            const other = document.querySelector('.tag-toggle[data-tag="' + f + '"]');
            if (other) other.classList.remove('active-' + f);
          });
          currentFormat = tag;
          btn.classList.add('active-' + tag);
        }
      } else if (KNOWLEDGE.includes(tag)) {
        currentKnowledge[tag] = !currentKnowledge[tag];
        btn.classList.toggle('active-' + tag, currentKnowledge[tag]);
      }
      ensureActiveSpan();
      normalizeInput();
      msgInput.focus();
    });
  });

  // --- Input event handlers ---

  // Strip paste to plain text
  msgInput.addEventListener('paste', ev => {
    ev.preventDefault();
    const text = (ev.clipboardData || window.clipboardData).getData('text/plain');
    document.execCommand('insertText', false, text);
  });

  // Enter handling: Ctrl/Cmd+Enter = submit, plain Enter = <br> (prevent Chrome <div> wrapping)
  msgInput.addEventListener('keydown', ev => {
    if (ev.key === 'Enter') {
      if (ev.ctrlKey || ev.metaKey) {
        ev.preventDefault();
        form.dispatchEvent(new Event('submit'));
      } else {
        ev.preventDefault();
        const sel = window.getSelection();
        if (sel.rangeCount) {
          const range = sel.getRangeAt(0);
          range.deleteContents();
          const br = document.createElement('br');
          range.insertNode(br);
          range.setStartAfter(br);
          range.collapse(true);
          sel.removeAllRanges();
          sel.addRange(range);
        }
      }
    }
  });

  // --- Serialization: contenteditable → tagged text + segments ---

  function getSegments() {
    const segments = [];

    function walk(node, inherited) {
      if (node.nodeType === Node.TEXT_NODE) {
        const text = node.textContent.replace(/\u200B/g, '');
        if (text) {
          segments.push({
            text: text,
            identity: inherited.identity,
            format: inherited.format,
            plan: inherited.plan,
            pin: inherited.pin,
          });
        }
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        if (node.tagName === 'BR') {
          segments.push({ text: '\n', identity: inherited.identity, format: inherited.format, plan: inherited.plan, pin: inherited.pin });
        } else if (node.tagName === 'SPAN') {
          // Span's own data takes priority, fall back to inherited
          const spanProps = {
            identity: node.dataset.identity || inherited.identity,
            format: node.dataset.format || inherited.format,
            plan: node.dataset.plan === '1' || inherited.plan,
            pin: node.dataset.pin === '1' || inherited.pin,
          };
          for (const child of node.childNodes) {
            walk(child, spanProps);
          }
        } else {
          // DIV/P from browser line wrapping — treat as block with trailing newline
          const isBlock = node.tagName === 'DIV' || node.tagName === 'P';
          for (const child of node.childNodes) walk(child, inherited);
          if (isBlock) {
            segments.push({ text: '\n', identity: null, format: null, plan: false, pin: false });
          }
        }
      }
    }

    const noProps = { identity: null, format: null, plan: false, pin: false };
    for (const child of msgInput.childNodes) walk(child, noProps);

    // Merge adjacent segments with same properties
    const merged = [];
    for (const seg of segments) {
      const prev = merged[merged.length - 1];
      if (prev && prev.identity === seg.identity && prev.format === seg.format &&
          prev.plan === seg.plan && prev.pin === seg.pin) {
        prev.text += seg.text;
      } else {
        merged.push({ ...seg });
      }
    }
    return merged;
  }

  function serializeSegments(segments) {
    let result = '';
    for (const seg of segments) {
      let t = seg.text;
      if (seg.format) t = '<' + seg.format + '>' + t + '</' + seg.format + '>';
      if (seg.plan) t = '<plan>' + t + '</plan>';
      if (seg.pin) t = '<pin>' + t + '</pin>';
      if (seg.identity) t = '<' + seg.identity + '>' + t + '</' + seg.identity + '>';
      result += t;
    }
    return result.trim();
  }

  function getPrimaryIdentity(segments) {
    for (const seg of segments) {
      if (seg.identity) return seg.identity;
    }
    return currentIdentity;
  }

  // --- Image upload ---
  imageBtn.addEventListener('click', () => imageInput.click());

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

  removeImage.addEventListener('click', () => clearImage());

  function clearImage() {
    imageInput.value = '';
    imageBtn.classList.remove('has-file');
    imagePreview.classList.remove('visible');
    if (previewImg.src.startsWith('blob:')) URL.revokeObjectURL(previewImg.src);
    previewImg.src = '';
  }

  // --- Form submission ---
  form.addEventListener('submit', async ev => {
    ev.preventDefault();
    if (submitting) return;

    normalizeInput();
    const segments = getSegments();
    const message = serializeSegments(segments);
    const hasImage = imageInput.files.length > 0;

    if (!message && !hasImage) return;
    if (!bridgeOnline) { showError('bridge offline'); return; }

    submitting = true;
    sendBtn.disabled = true;

    const actor = getPrimaryIdentity(segments);
    const usedTags = [];
    if (message.includes('<plan>')) usedTags.push('plan');
    if (message.includes('<pin>')) usedTags.push('pin');

    const fd = new FormData();
    fd.append('message', message);
    if (actor) fd.append('actor', actor);
    usedTags.forEach(t => fd.append('tags[]', t));
    if (hasImage) fd.append('image', imageInput.files[0]);

    try {
      const resp = await fetch('api/submit.php', { method: 'POST', body: fd, credentials: 'same-origin' });
      const data = await resp.json();

      if (!data || !data.ok) { showError(data?.error || 'submit failed'); return; }

      appendMonoMessage(segments, actor, usedTags, hasImage ? imageInput.files[0] : null);

      // Clear input and reset state
      msgInput.innerHTML = '';
      clearImage();
      currentFormat = null;
      FORMATS.forEach(f => {
        const b = document.querySelector('.tag-toggle[data-tag="' + f + '"]');
        if (b) b.classList.remove('active-' + f);
      });
      KNOWLEDGE.forEach(k => {
        currentKnowledge[k] = false;
        const b = document.querySelector('.tag-toggle[data-tag="' + k + '"]');
        if (b) b.classList.remove('active-' + k);
      });

      appendPending(data.job_id);

    } catch { showError('connection failed'); }
    finally { submitting = false; sendBtn.disabled = false; }
  });

  // --- Rendering ---

  function renderSegmentsHtml(segments) {
    let html = '';
    for (const seg of segments) {
      let text = md(esc(seg.text));
      const classes = [];
      if (seg.identity) classes.push('chat-id-' + seg.identity);
      if (seg.format === 'do') classes.push('inline-do');
      if (seg.format === 'narrate') classes.push('inline-narrate');
      if (seg.plan) classes.push('inline-tag inline-plan');
      if (seg.pin) classes.push('inline-tag inline-pin');

      if (classes.length > 0) {
        html += '<span class="' + classes.join(' ') + '">' + text + '</span>';
      } else {
        html += text;
      }
    }
    return html.replace(/\n/g, '<br>');
  }

  function appendMonoMessage(segments, actor, tags, imageFile) {
    const div = document.createElement('div');
    div.className = 'turn';

    const actorName = actor || 'mono';
    const tagPills = tags.map(t => '<span class="tag-pill">' + esc(t) + '</span>').join('');

    let imageHtml = '';
    if (imageFile) {
      const url = URL.createObjectURL(imageFile);
      imageHtml = '<div class="msg-image"><img src="' + url + '" alt="" loading="lazy"></div>';
    }

    const bodyHtml = renderSegmentsHtml(segments);
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase();

    div.innerHTML =
      '<div class="msg mono">' +
        '<span class="actor" data-actor="' + esc(actorName) + '">' + esc(actorName) + '</span>' +
        imageHtml +
        '<div class="body">' + bodyHtml + '</div>' +
        '<div class="msg-meta">' + tagPills + '<time>' + timeStr + '</time></div>' +
      '</div>';

    chatLog.appendChild(div);
    scrollToBottom();
  }

  function appendPending(jobId) {
    const div = document.createElement('div');
    div.className = 'turn pending';
    div.innerHTML = '<div class="breathing"></div>';
    chatLog.appendChild(div);
    scrollToBottom();

    const poll = setInterval(async () => {
      try {
        const resp = await fetch('api/status.php?id=' + jobId + '&format=json', { credentials: 'same-origin' });
        const data = await resp.json();
        if (!data || !data.ok) return;

        if (data.status === 'done') {
          clearInterval(poll);
          div.remove();
          if (Array.isArray(data.display) && data.display.length > 0) {
            appendClaudeMessage(data.display, data.actor || 'claude');
          }
        } else if (data.status === 'error') {
          clearInterval(poll);
          div.remove();
          showError(data.error || 'something went wrong');
        }
      } catch {}
    }, 1200);
  }

  function appendClaudeMessage(display, actor) {
    const div = document.createElement('div');
    div.className = 'turn';

    let bodyHtml = '';
    for (const span of display) {
      if (!span.content) continue;
      const cls = span.tag === 'do' ? 'display-do'
                : span.tag === 'narrate' ? 'display-narrate'
                : 'display-say';
      bodyHtml += '<p class="' + cls + '">' + md(esc(span.content)) + '</p>\n';
    }

    if (!bodyHtml.trim()) return;

    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase();

    div.innerHTML =
      '<div class="msg claude">' +
        '<span class="actor" data-actor="' + esc(actor) + '">' + esc(actor) + '</span>' +
        '<div class="body">' + bodyHtml + '</div>' +
        '<div class="msg-meta"><time>' + timeStr + '</time></div>' +
      '</div>';

    chatLog.appendChild(div);
    scrollToBottom();
  }

  function showError(msg) {
    const div = document.createElement('div');
    div.className = 'turn error-turn';
    div.innerHTML = '<p class="error-msg">' + esc(msg) + '</p>';
    chatLog.appendChild(div);
    scrollToBottom();
  }

  function scrollToBottom() {
    requestAnimationFrame(() => { chatArea.scrollTop = chatArea.scrollHeight; });
  }

  function esc(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }

  function md(html) {
    return html
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>');
  }

  // --- Bridge status polling ---
  async function checkBridge() {
    try {
      const resp = await fetch('api/bridge_state.php', { credentials: 'same-origin' });
      const data = await resp.json();
      bridgeOnline = !!(data && data.ok && data.online);
    } catch { bridgeOnline = false; }
    bridgeDot.classList.toggle('online', bridgeOnline);
    bridgeLabel.textContent = bridgeOnline ? 'connected' : 'offline';
  }

  setInterval(checkBridge, 3000);
  checkBridge();

  // --- HTMX events ---
  document.body.addEventListener('htmx:afterSettle', () => scrollToBottom());

  // --- Init ---
  scrollToBottom();
  msgInput.focus();

})();
