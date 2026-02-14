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
  let composing = false;
  let initialLoad = true;
  let pollIntervals = [];

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
      // Cursor in middle — normalize first, then re-query cursor position
      parentSpan.normalize();
      // Re-query selection since normalize() may have merged text nodes
      const freshSel = window.getSelection();
      const tailRange = document.createRange();
      let splitNode, splitOffset;
      if (freshSel.rangeCount && parentSpan.contains(freshSel.getRangeAt(0).startContainer)) {
        const fr = freshSel.getRangeAt(0);
        splitNode = fr.startContainer;
        splitOffset = fr.startOffset;
      } else {
        // Selection was lost — fall back to placing at end
        parentSpan.after(newSpan);
        placeCursorIn(newSpan);
        return;
      }
      if (splitNode === parentSpan) {
        if (splitOffset < parentSpan.childNodes.length) {
          splitNode = parentSpan.childNodes[splitOffset];
          splitOffset = 0;
        } else {
          parentSpan.after(newSpan);
          placeCursorIn(newSpan);
          return;
        }
      }
      tailRange.setStart(splitNode, splitOffset);
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

    // 1b. Unwrap browser-injected DIV/P elements
    for (const child of Array.from(msgInput.childNodes)) {
      if (child.nodeType === Node.ELEMENT_NODE &&
          (child.tagName === 'DIV' || child.tagName === 'P')) {
        const br = document.createElement('br');
        child.before(br);
        while (child.firstChild) child.before(child.firstChild);
        child.remove();
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
    // Use nextSibling (not nextElementSibling) so BRs and text nodes
    // between spans correctly prevent merging across boundaries.
    let child = msgInput.firstChild;
    while (child) {
      const next = child.nextSibling;
      if (next && child.nodeType === Node.ELEMENT_NODE && child.tagName === 'SPAN' &&
          next.nodeType === Node.ELEMENT_NODE && next.tagName === 'SPAN' &&
          segmentState(child) === segmentState(next)) {
        while (next.firstChild) child.appendChild(next.firstChild);
        next.remove();
        // Don't advance — check the same `child` against its new next sibling
      } else {
        child = next;
      }
    }

    // 4. Ensure cursor is still inside msgInput
    const selCheck = window.getSelection();
    if (selCheck.rangeCount && !msgInput.contains(selCheck.getRangeAt(0).startContainer)) {
      const lastSpan = msgInput.querySelector('span:last-of-type');
      if (lastSpan) placeCursorIn(lastSpan);
    }
  }

  function insertNewlineBeforeTagSwitch() {
    const sel = window.getSelection();
    if (!sel.rangeCount) return;
    const span = findParentSpan(sel.getRangeAt(0).startContainer);
    if (!span) return;
    if (isSpanEmpty(span)) return;
    const prev = span.previousSibling;
    if (!prev) return;
    if (prev.nodeName === 'BR') return;
    if (prev.nodeType === Node.ELEMENT_NODE && prev.tagName === 'SPAN') {
      if (isSpanEmpty(prev)) return;
      // Only insert BR for format/identity switches, not knowledge-only
      const prevFmt = prev.dataset.format || null;
      const prevId = prev.dataset.identity || null;
      const curFmt = span.dataset.format || null;
      const curId = span.dataset.identity || null;
      if (prevFmt === curFmt && prevId === curId) return;
    }
    span.before(document.createElement('br'));
  }

  function inputHasContent() {
    return msgInput.textContent.replace(/\u200B/g, '').trim() !== '';
  }

  // --- Identity chips ---
  document.querySelectorAll('.identity-chip').forEach(chip => {
    chip.addEventListener('mousedown', ev => ev.preventDefault());
    chip.addEventListener('click', () => {
      if (composing) return;
      const val = chip.dataset.identity;
      if (currentIdentity === val) {
        currentIdentity = null;
        chip.classList.remove('active');
        chip.setAttribute('aria-pressed', 'false');
      } else {
        document.querySelectorAll('.identity-chip').forEach(c => {
          c.classList.remove('active');
          c.setAttribute('aria-pressed', 'false');
        });
        currentIdentity = val;
        chip.classList.add('active');
        chip.setAttribute('aria-pressed', 'true');
      }
      msgInput.focus();
      if (inputHasContent()) {
        ensureActiveSpan();
        normalizeInput();
        insertNewlineBeforeTagSwitch();
      }
    });
  });

  // --- Format & knowledge buttons ---
  document.querySelectorAll('.tag-toggle').forEach(btn => {
    const tag = btn.dataset.tag;

    btn.addEventListener('mousedown', ev => ev.preventDefault());
    btn.addEventListener('click', () => {
      if (composing) return;
      if (FORMATS.includes(tag)) {
        if (currentFormat === tag) {
          currentFormat = null;
          btn.classList.remove('active-' + tag);
          btn.setAttribute('aria-pressed', 'false');
        } else {
          FORMATS.forEach(f => {
            const other = document.querySelector('.tag-toggle[data-tag="' + f + '"]');
            if (other) {
              other.classList.remove('active-' + f);
              other.setAttribute('aria-pressed', 'false');
            }
          });
          currentFormat = tag;
          btn.classList.add('active-' + tag);
          btn.setAttribute('aria-pressed', 'true');
        }
      } else if (KNOWLEDGE.includes(tag)) {
        currentKnowledge[tag] = !currentKnowledge[tag];
        btn.classList.toggle('active-' + tag, currentKnowledge[tag]);
        btn.setAttribute('aria-pressed', String(currentKnowledge[tag]));
      }
      msgInput.focus();
      if (inputHasContent()) {
        ensureActiveSpan();
        normalizeInput();
        insertNewlineBeforeTagSwitch();
      }
    });
  });

  // --- Input event handlers ---

  // Wrap bare text nodes created by the browser (e.g. after select-all + delete)
  msgInput.addEventListener('input', () => {
    for (const child of Array.from(msgInput.childNodes)) {
      if (child.nodeType === Node.TEXT_NODE) {
        const span = createSpan();
        child.before(span);
        span.appendChild(child);
      }
    }
    syncStateFromDOM();
  });

  // Prevent HTML drag-drop into contenteditable
  msgInput.addEventListener('drop', ev => { ev.preventDefault(); });

  // IME composition guards
  msgInput.addEventListener('compositionstart', () => { composing = true; });
  msgInput.addEventListener('compositionend', () => { composing = false; });

  // Sync JS state from DOM (handles browser undo reverting span changes)
  function syncStateFromDOM() {
    const sel = window.getSelection();
    if (!sel.rangeCount) return;
    const span = findParentSpan(sel.getRangeAt(0).startContainer);
    if (!span) return;

    const spanId = span.dataset.identity || null;
    const spanFmt = span.dataset.format || null;
    const spanPlan = span.dataset.plan === '1';
    const spanPin = span.dataset.pin === '1';

    if (spanId !== currentIdentity) {
      currentIdentity = spanId;
      document.querySelectorAll('.identity-chip').forEach(c => {
        const active = c.dataset.identity === currentIdentity;
        c.classList.toggle('active', active);
        c.setAttribute('aria-pressed', String(active));
      });
    }
    if (spanFmt !== currentFormat) {
      currentFormat = spanFmt;
      FORMATS.forEach(f => {
        const b = document.querySelector('.tag-toggle[data-tag="' + f + '"]');
        if (b) {
          const active = f === currentFormat;
          b.classList.toggle('active-' + f, active);
          b.setAttribute('aria-pressed', String(active));
        }
      });
    }
    if (spanPlan !== currentKnowledge.plan) {
      currentKnowledge.plan = spanPlan;
      const b = document.querySelector('.tag-toggle[data-tag="plan"]');
      if (b) {
        b.classList.toggle('active-plan', spanPlan);
        b.setAttribute('aria-pressed', String(spanPlan));
      }
    }
    if (spanPin !== currentKnowledge.pin) {
      currentKnowledge.pin = spanPin;
      const b = document.querySelector('.tag-toggle[data-tag="pin"]');
      if (b) {
        b.classList.toggle('active-pin', spanPin);
        b.setAttribute('aria-pressed', String(spanPin));
      }
    }
  }

  // Strip paste to plain text
  msgInput.addEventListener('paste', ev => {
    ev.preventDefault();
    const text = (ev.clipboardData || window.clipboardData).getData('text/plain');
    if (!text) return;
    const sel = window.getSelection();
    if (!sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    range.deleteContents();
    const parentSpan = findParentSpan(range.startContainer);
    if (parentSpan && stateMatches(parentSpan)) {
      const textNode = document.createTextNode(text);
      range.insertNode(textNode);
      range.setStartAfter(textNode);
      range.collapse(true);
      sel.removeAllRanges();
      sel.addRange(range);
    } else {
      const span = createSpan();
      span.textContent = text;
      if (parentSpan) {
        // Split parent span at cursor to avoid nesting
        const pasteRange = document.createRange();
        pasteRange.setStart(range.startContainer, range.startOffset);
        pasteRange.setEnd(parentSpan, parentSpan.childNodes.length);
        const tail = pasteRange.extractContents();
        const hasTail = tail.textContent.replace(/\u200B/g, '').length > 0;
        parentSpan.after(span);
        if (hasTail) {
          const afterSpan = document.createElement('span');
          afterSpan.className = parentSpan.className;
          for (const key of Object.keys(parentSpan.dataset)) afterSpan.dataset[key] = parentSpan.dataset[key];
          afterSpan.appendChild(tail);
          span.after(afterSpan);
        }
      } else {
        range.insertNode(span);
      }
      const newRange = document.createRange();
      newRange.setStartAfter(span);
      newRange.collapse(true);
      sel.removeAllRanges();
      sel.addRange(newRange);
    }
    normalizeInput();
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
          // If br is at the end of its container, add a sentinel <br>
          // so the browser renders the new blank line visually
          if (!br.nextSibling ||
              (br.nextSibling.nodeType === Node.TEXT_NODE &&
               br.nextSibling.textContent.replace(/\u200B/g, '') === '' &&
               !br.nextSibling.nextSibling)) {
            br.parentNode.appendChild(document.createElement('br'));
          }
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
            plan: node.dataset.plan !== undefined ? node.dataset.plan === '1' : inherited.plan,
            pin: node.dataset.pin !== undefined ? node.dataset.pin === '1' : inherited.pin,
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

    // Strip trailing newlines (from sentinel <br>)
    while (merged.length > 0) {
      const last = merged[merged.length - 1];
      const trimmed = last.text.replace(/\n+$/, '');
      if (trimmed === last.text) break;
      if (trimmed === '') { merged.pop(); } else { last.text = trimmed; break; }
    }

    return merged;
  }

  function serializeSegments(segments) {
    let result = '';
    for (const seg of segments) {
      let t = seg.text;
      // Don't wrap bare newlines in display tags
      if (t.replace(/\n/g, '') === '') { result += t; continue; }
      const fmt = seg.format || 'say';
      t = '<' + fmt + '>' + t + '</' + fmt + '>';
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
    msgInput.focus();
  }

  // --- Auth guard ---
  function checkAuth(resp) {
    if (resp.status === 401) { window.location.href = '.'; return true; }
    return false;
  }

  // --- Form submission ---
  form.addEventListener('submit', async ev => {
    ev.preventDefault();
    if (submitting) return;

    normalizeInput();
    const segments = getSegments();
    const message = serializeSegments(segments);
    const hasImage = imageInput.files.length > 0;

    if ((!message || !message.trim()) && !hasImage) return;
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
      if (checkAuth(resp)) return;
      const data = await resp.json();

      if (!data || !data.ok) { showError(data?.error || 'submit failed'); return; }

      appendMonoMessage(segments, actor, usedTags, hasImage ? imageInput.files[0] : null);

      // Clear input and reset state
      msgInput.innerHTML = '';
      clearImage();
      currentFormat = null;
      FORMATS.forEach(f => {
        const b = document.querySelector('.tag-toggle[data-tag="' + f + '"]');
        if (b) { b.classList.remove('active-' + f); b.setAttribute('aria-pressed', 'false'); }
      });
      KNOWLEDGE.forEach(k => {
        currentKnowledge[k] = false;
        const b = document.querySelector('.tag-toggle[data-tag="' + k + '"]');
        if (b) { b.classList.remove('active-' + k); b.setAttribute('aria-pressed', 'false'); }
      });
      currentIdentity = null;
      document.querySelectorAll('.identity-chip').forEach(c => {
        c.classList.remove('active');
        c.setAttribute('aria-pressed', 'false');
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
    const isoTs = now.toISOString();

    div.innerHTML =
      '<div class="msg mono" data-identity="' + esc(actorName) + '">' +
        '<span class="actor" data-actor="' + esc(actorName) + '">' + esc(actorName) + '</span>' +
        imageHtml +
        '<div class="body">' + bodyHtml + '</div>' +
        '<div class="msg-meta">' + tagPills + '<time class="msg-time" data-ts="' + isoTs + '" datetime="' + isoTs + '"></time></div>' +
      '</div>';

    chatLog.appendChild(div);
    formatMsgTimes(div);
    scrollToBottom();
  }

  function appendPending(jobId) {
    const div = document.createElement('div');
    div.className = 'turn pending';
    div.innerHTML = '<div class="breathing"></div>';
    chatLog.appendChild(div);
    scrollToBottom();

    let pollErrors = 0;
    const poll = setInterval(async () => {
      try {
        const resp = await fetch('api/status.php?id=' + jobId + '&format=json', { credentials: 'same-origin' });
        if (checkAuth(resp)) { clearInterval(poll); return; }
        const data = await resp.json();
        if (!data || !data.ok) return;

        if (data.status === 'done') {
          clearInterval(poll);
          div.remove();
          // Guard against duplicate rendering (e.g. two tabs polling same job)
          if (chatLog.querySelector('[data-rendered-job="' + jobId + '"]')) return;
          if (Array.isArray(data.display) && data.display.length > 0) {
            appendClaudeMessage(data.display, data.actor || 'claude', jobId);
          }
        } else if (data.status === 'error') {
          clearInterval(poll);
          div.remove();
          showError(data.error || 'something went wrong');
        }
      } catch {
        pollErrors++;
        if (pollErrors >= 5) {
          clearInterval(poll);
          div.remove();
          showError('lost connection');
        }
      }
    }, 1200);
    pollIntervals.push(poll);
  }

  function appendClaudeMessage(display, actor, jobId) {
    const div = document.createElement('div');
    div.className = 'turn';
    if (jobId) div.dataset.renderedJob = jobId;

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
    const isoTs = now.toISOString();

    div.innerHTML =
      '<div class="msg claude">' +
        '<span class="actor" data-actor="' + esc(actor) + '">' + esc(actor) + '</span>' +
        '<div class="body">' + bodyHtml + '</div>' +
        '<div class="msg-meta"><time class="msg-time" data-ts="' + isoTs + '" datetime="' + isoTs + '"></time></div>' +
      '</div>';

    chatLog.appendChild(div);
    formatMsgTimes(div);
    scrollToBottom();
  }

  function showError(msg) {
    const div = document.createElement('div');
    div.className = 'turn error-turn';
    div.innerHTML = '<p class="error-msg">' + esc(msg) + '</p>';
    chatLog.appendChild(div);
    scrollToBottom();
  }

  function formatMsgTimes(root) {
    const els = (root || document).querySelectorAll('.msg-time:empty, .msg-time[data-ts]');
    els.forEach(el => {
      const ts = el.getAttribute('data-ts');
      if (!ts) return;
      const d = new Date(ts);
      if (isNaN(d.getTime())) return;
      const str = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase();
      if (el.textContent !== str) el.textContent = str;
    });
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
      .replace(/\*\*(.+?)\*\*/gs, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/gs, '<em>$1</em>');
  }

  // --- Bridge status polling ---
  async function checkBridge() {
    try {
      const resp = await fetch('api/bridge_state.php', { credentials: 'same-origin' });
      if (checkAuth(resp)) return;
      const data = await resp.json();
      bridgeOnline = !!(data && data.ok && data.online);
    } catch { bridgeOnline = false; }
    bridgeDot.classList.toggle('online', bridgeOnline);
    bridgeLabel.textContent = bridgeOnline ? 'connected' : 'offline';
  }

  const bridgePollMs = ('ontouchstart' in window || navigator.maxTouchPoints > 0) ? 8000 : 3000;
  setInterval(checkBridge, bridgePollMs);
  checkBridge();

  // --- HTMX events ---
  document.body.addEventListener('htmx:afterSettle', () => {
    formatMsgTimes(chatLog);
    if (initialLoad) {
      scrollToBottom();
      initialLoad = false;
    } else if (chatArea.scrollHeight - chatArea.scrollTop - chatArea.clientHeight < 100) {
      scrollToBottom();
    }
  });

  window.addEventListener('beforeunload', () => {
    pollIntervals.forEach(id => clearInterval(id));
  });

  // --- Loom image upload ---

  const loomBtn   = document.getElementById('loom-upload-btn');
  const loomInput = document.getElementById('loom-input');
  const loomBadge = document.getElementById('loom-badge');

  if (loomBtn && loomInput && loomBadge) {
    let loomUploading = false;

    function updateLoomBadge(count) {
      if (count > 0) {
        loomBadge.textContent = String(count);
        loomBadge.classList.add('visible');
      } else {
        loomBadge.classList.remove('visible');
        loomBadge.textContent = '';
      }
    }

    async function fetchLoomCount() {
      try {
        const resp = await fetch('api/loom_images.php', { credentials: 'same-origin' });
        if (checkAuth(resp)) return;
        const data = await resp.json();
        if (data && data.ok) updateLoomBadge(data.count);
      } catch { /* silent */ }
    }

    loomBtn.addEventListener('click', () => {
      if (loomUploading) return;
      loomInput.click();
    });

    loomInput.addEventListener('change', async () => {
      const files = loomInput.files;
      if (!files || files.length === 0) return;

      loomUploading = true;
      loomBtn.classList.add('uploading');

      const fd = new FormData();
      for (let i = 0; i < files.length; i++) {
        fd.append('images[]', files[i]);
      }

      try {
        const resp = await fetch('api/upload_loom.php', { method: 'POST', body: fd, credentials: 'same-origin' });
        if (checkAuth(resp)) return;
        const data = await resp.json();

        if (data && data.ok) {
          loomBtn.classList.add('success');
          setTimeout(() => loomBtn.classList.remove('success'), 1500);
          fetchLoomCount();
        }
      } catch { /* silent */ }
      finally {
        loomUploading = false;
        loomBtn.classList.remove('uploading');
        loomInput.value = '';
      }
    });

    // Fetch initial count
    fetchLoomCount();
  }

  // --- Init ---
  msgInput.focus();
  if (sendBtn) sendBtn.title = 'Send (Ctrl+Enter)';

})();
