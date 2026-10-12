/**
 * main.js - Main Application Entry for SatyaSetu WhatsApp Web
 *
 * Phase 3 changes:
 *  - renderChatArea: same-sender class grouping (2px vs 12px gap),
 *    doc-card for file attachments, fact-check-card for cardData,
 *    disclaimer shown only once in empty-state.
 *  - imageUploadInput: 2 MB guard, accept jpeg/png/webp only, no placeholder text.
 *  - docUploadInput: 2 MB guard, PDF only, calls uploadPdf via send.js extraData.
 *  - startMediaRecorderFallback: correct mimeType, no [Voice Note] wrapper.
 *  - copy-card-btn: delegated click handler.
 */

import { store } from './state.js';
import { escapeHtml } from './utils/escape.js';
import { formatWhatsAppText } from './utils/format.js';
import { sendMessage, runBotLifecycle } from './features/send.js';
import { openForwardModal, closeForwardModal, forwardToTarget, showToast } from './features/forward.js';
import { uploadVoiceAudio } from './api.js';

let contextTargetMessageId = null;

// ── Verdict display config ────────────────────────────────────────────────────
const VERDICT_CONFIG = {
  SUPPORTED:           { icon: 'check_circle', label: 'True',         bg: 'var(--chip-true-bg)',    color: 'var(--chip-true-fg)' },
  REFUTED:             { icon: 'cancel',        label: 'Fake',         bg: 'var(--chip-fake-bg)',    color: 'var(--chip-fake-fg)' },
  PARTIALLY_SUPPORTED: { icon: 'warning',       label: 'Half True',   bg: 'var(--chip-half-bg)',    color: 'var(--chip-half-fg)' },
  OUTDATED:            { icon: 'history',       label: 'Old News',    bg: 'var(--chip-old-bg)',     color: 'var(--chip-old-fg)' },
  UNVERIFIABLE:        { icon: 'help',          label: "Can't Confirm",bg: 'var(--chip-none-bg)',   color: 'var(--chip-none-fg)' },
};

const VERDICT_EMOJI = {
  SUPPORTED: '\u2705', REFUTED: '\u274C', PARTIALLY_SUPPORTED: '\u26A0\uFE0F', OUTDATED: '\uD83D\uDD57', UNVERIFIABLE: '\u2139\uFE0F',
};

// ── Build fact-check card ─────────────────────────────────────────────────────
function buildFactCheckCard(data) {
  const key = (data.verdict || data.overall_verdict || 'UNVERIFIABLE').toUpperCase();
  const cfg = VERDICT_CONFIG[key] || VERDICT_CONFIG.UNVERIFIABLE;
  const emoji = VERDICT_EMOJI[key] || '\u2139\uFE0F';

  // Verdict chip
  const chipHtml = `
    <div class="fc-verdict-chip" style="background:${cfg.bg};color:${cfg.color};">
      <span class="fc-verdict-icon">${emoji}</span>
      <span class="fc-verdict-label">${escapeHtml(data.plain_verdict || cfg.label)}</span>
    </div>`;

  // Score bar (0-10 segments)
  let scoreHtml = '';
  if (data.truth_score != null) {
    const score = Math.max(0, Math.min(10, data.truth_score));
    const segs = Array.from({ length: 10 }, (_, i) =>
      `<span class="fc-score-seg${i < score ? ' filled' : ''}"></span>`
    ).join('');
    scoreHtml = `
      <div class="fc-score-row">
        <span class="fc-score-label">Truth score</span>
        <span class="fc-score-num">${score}/10</span>
      </div>
      <div class="fc-score-bar">${segs}</div>`;
  } else if (key === 'UNVERIFIABLE') {
    scoreHtml = `<div class="fc-no-score">Not enough proof yet.</div>`;
  }

  // Claim quote
  const claimText = data.claim || data.query || '';
  const claimDisplay = claimText.length > 160
    ? escapeHtml(claimText.slice(0, 157)) + '...'
    : escapeHtml(claimText);
  const claimHtml = claimDisplay ? `<div class="fc-claim-block">${claimDisplay}</div>` : '';

  // Reason
  const reason = data.short_reason || data.explanation || '';
  const reasonHtml = reason
    ? `<div class="fc-why"><strong>Why:</strong> ${escapeHtml(reason.slice(0, 280))}</div>` : '';

  // Source pills
  let sourcesHtml = '';
  if (data.sources && data.sources.length > 0) {
    const pills = data.sources.slice(0, 3).map(src => {
      const domain = src.domain || src.url || '';
      const url = src.url || '#';
      return `<a class="fc-source-pill" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(domain)}</a>`;
    }).join('');
    sourcesHtml = `<div class="fc-sources-row"><span class="fc-sources-label">Check:</span>${pills}</div>`;
  }

  // Actions
  const copyText = escapeHtml((data.plain_verdict || cfg.label) + ': ' + (data.short_reason || ''));
  const actionsHtml = `
    <div class="fc-actions">
      <button class="fc-action-btn copy-card-btn" data-text="${copyText}">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
        Copy
      </button>
      <span class="fc-forward-hint">Send this to whoever forwarded it.</span>
    </div>`;

  return `<div class="fact-check-card">${chipHtml}${scoreHtml}${claimHtml}${reasonHtml}${sourcesHtml}${actionsHtml}</div>`;
}

// ── Build document card ───────────────────────────────────────────────────────
function buildDocCard(fileInfo) {
  const name   = escapeHtml(fileInfo.name || 'Document');
  const sizeKb = fileInfo.size ? Math.round(fileInfo.size / 1024) : 0;
  return `
    <div class="doc-card">
      <span class="doc-card-icon">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
      </span>
      <div class="doc-card-info">
        <div class="doc-card-name">${name}</div>
        ${sizeKb ? `<div class="doc-card-size">${sizeKb} KB</div>` : ''}
      </div>
    </div>`;
}

// ── Render Sidebar ────────────────────────────────────────────────────────────
function renderSidebar() {
  const listEl = document.getElementById('contactsList');
  if (!listEl) return;

  const { chats, activeChatId: currentChatId, searchQuery: query, activeFilter: filter } = store;
  listEl.innerHTML = '';

  Object.values(chats).forEach(chat => {
    if (query) {
      const matchName = chat.name.toLowerCase().includes(query);
      const matchMsg  = (chat.lastMsg || '').toLowerCase().includes(query);
      if (!matchName && !matchMsg) return;
    }
    if (filter === 'unread'     && !chat.unread) return;
    if (filter === 'favourites' && !(chat.isBot || chat.id === 'sharma')) return;
    if (filter === 'groups'     && (chat.isBot || chat.id === 'mummy' || chat.id === 'papa')) return;

    const item = document.createElement('div');
    item.className = `contact-item ${chat.id === currentChatId ? 'active' : ''}`;
    item.id = `item-${chat.id}`;
    item.onclick = () => {
      store.setActiveChat(chat.id);
      if (window.innerWidth <= 768) {
        document.querySelector('.chats-sidebar')?.classList.add('hidden-mobile');
        document.querySelector('.chat-area')?.classList.remove('hidden-mobile');
      }
    };

    const avatarHtml   = chat.isBot
      ? `<div class="contact-avatar bot-avatar">🛡️</div>`
      : `<div class="contact-avatar" style="background:${escapeHtml(chat.color)};">${escapeHtml(chat.avatar)}</div>`;
    const verifiedHtml = chat.isBot
      ? `<svg class="verified-badge" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>`
      : '';
    const pinHtml      = chat.pinned
      ? `<svg class="pin-icon" width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/></svg>`
      : '';
    const unreadHtml   = chat.unread > 0
      ? `<span class="contact-unread-badge">${chat.unread}</span>` : '';

    item.innerHTML = `
      ${avatarHtml}
      <div class="contact-info">
        <div class="contact-top">
          <span class="contact-name">${escapeHtml(chat.name)} ${verifiedHtml}</span>
          <span class="contact-time">${escapeHtml(chat.time || '')}</span>
        </div>
        <div class="contact-bottom">
          <span class="contact-last-msg">${escapeHtml(chat.lastMsg || '')}</span>
          ${pinHtml}${unreadHtml}
        </div>
      </div>`;
    listEl.appendChild(item);
  });
}

// ── Render Chat Area ──────────────────────────────────────────────────────────
function renderChatArea() {
  const chat = store.getActiveChat();
  if (!chat) return;

  const titleEl  = document.getElementById('headerTitle');
  const subEl    = document.getElementById('headerSub');
  const avatarEl = document.getElementById('headerAvatar');
  if (titleEl)  titleEl.textContent        = chat.name;
  if (subEl)    subEl.textContent          = chat.sub;
  if (avatarEl) { avatarEl.textContent     = chat.avatar; avatarEl.style.background = chat.color; }

  const stream = document.getElementById('messagesStream');
  if (!stream) return;
  stream.innerHTML = '';

  // Date pill
  const datePill = document.createElement('div');
  datePill.className   = 'date-pill';
  datePill.textContent = chat.id === 'sharma' ? 'TODAY' : 'YESTERDAY';
  stream.appendChild(datePill);

  if (chat.isBot) {
    const enc = document.createElement('div');
    enc.className = 'encryption-pill';
    enc.innerHTML = '<span>🔒</span> Official SatyaSetu AI Bot. End-to-end verified pipeline. Never shares your number.';
    stream.appendChild(enc);
  }

  // Disclaimer shown ONCE only in the empty state
  if (chat.messages.length === 0) {
    const d = document.createElement('div');
    d.className   = 'simulated-disclaimer';
    d.textContent = 'Simulated interface for demonstration. Not affiliated with WhatsApp or Meta.';
    stream.appendChild(d);
  }

  let lastSender = null;

  chat.messages.forEach(msg => {
    const row = document.createElement('div');
    const sameSender = lastSender === (msg.isMe ? 'me' : msg.sender);
    row.className = `msg-row ${msg.isMe ? 'outgoing' : 'incoming'}${sameSender ? ' same-sender' : ''}`;
    row.id = msg.id;
    lastSender = msg.isMe ? 'me' : msg.sender;

    const fwdHtml = msg.forwarded === 'many'
      ? `<div class="msg-forward-header"><span>â†ª</span> Forwarded many times</div>`
      : msg.forwarded ? `<div class="msg-forward-header"><span>â†ª</span> Forwarded</div>` : '';

    const quotedHtml = msg.quoted ? `
      <div class="msg-quoted">
        <div class="msg-quoted-title">${escapeHtml(msg.quoted.author)}</div>
        <div>${formatWhatsAppText(msg.quoted.text)}</div>
      </div>` : '';

    const imageHtml = msg.image ? `
      <div style="margin-bottom:6px;border-radius:8px;overflow:hidden;max-height:240px;">
        <img src="${escapeHtml(msg.image)}" style="width:100%;height:auto;display:block;" alt="attachment">
      </div>` : '';

    const docHtml   = msg.file ? buildDocCard(msg.file) : '';

    const retryHtml = (msg.isError && msg.retryClaim) ? `
      <div><button class="msg-retry-btn" data-retry="${escapeHtml(msg.retryClaim)}">â†» Retry Verification</button></div>` : '';

    const senderHeader = (!msg.isMe && !chat.isBot &&
      ['sharma','rishtedar','society','friends'].includes(chat.id))
      ? `<div class="msg-sender">${escapeHtml(msg.sender)}</div>` : '';

    const contentHtml = (!msg.isMe && msg.cardData)
      ? buildFactCheckCard(msg.cardData)
      : `<div class="msg-content-text">${formatWhatsAppText(msg.text)}</div>`;

    row.innerHTML = `
      <div class="msg-bubble" data-msgid="${escapeHtml(msg.id)}">
        <div class="msg-hover-actions">
          <span class="msg-action-icon quick-forward-btn" title="Forward" data-msgid="${escapeHtml(msg.id)}">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="15 17 20 12 15 7"/><path d="M4 18v-2a4 4 0 0 1 4-4h12"/></svg>
          </span>
          <span class="msg-action-icon context-menu-btn" title="Options" data-msgid="${escapeHtml(msg.id)}">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M7 10l5 5 5-5z"/></svg>
          </span>
        </div>
        ${senderHeader}${fwdHtml}${quotedHtml}${imageHtml}${docHtml}${contentHtml}${retryHtml}
        <div class="msg-meta">
          <span>${escapeHtml(msg.time || '')}</span>
          ${msg.status ? `<span class="msg-ticks">${escapeHtml(msg.status)}</span>` : ''}
        </div>
      </div>`;
    stream.appendChild(row);
  });

  stream.scrollTop = stream.scrollHeight;
}

// ── Presenter Panel ───────────────────────────────────────────────────────────
function renderPresenter() {
  const panel = document.getElementById('presenterPanel');
  if (!panel) return;
  if (store.isPresenterOpen) { panel.classList.add('visible'); } else { panel.classList.remove('visible'); return; }

  const data = store.lastPresenterData;
  const verdictEl  = document.getElementById('presenterVerdict');
  const strengthEl = document.getElementById('presenterStrength');
  const latencyEl  = document.getElementById('presenterLatency');
  const jsonPre    = document.getElementById('presenterJson');

  if (data) {
    if (verdictEl)  verdictEl.textContent  = data.verdict;
    if (strengthEl) strengthEl.textContent = data.evidence_strength;
    if (latencyEl)  latencyEl.textContent  = `${data.latencyMs} ms`;
    if (jsonPre)    jsonPre.textContent     = JSON.stringify(data.rawResponse, null, 2);
  } else {
    if (verdictEl)  verdictEl.textContent  = 'IDLE';
    if (strengthEl) strengthEl.textContent = 'N/A';
    if (latencyEl)  latencyEl.textContent  = '0 ms';
    if (jsonPre)    jsonPre.textContent     = '// No verification executed yet.\n// Send a claim to SatyaSetu.';
  }
}

store.subscribe(() => { renderSidebar(); renderChatArea(); renderPresenter(); });

// ── Popup helpers ─────────────────────────────────────────────────────────────
function closeAllPopups() {
  document.getElementById('messageContextMenu')?.style && (document.getElementById('messageContextMenu').style.display = 'none');
  document.getElementById('chatOptionsMenu')?.style && (document.getElementById('chatOptionsMenu').style.display = 'none');
  document.getElementById('attachmentPopup')?.style && (document.getElementById('attachmentPopup').style.display = 'none');
}
window.addEventListener('click', closeAllPopups);

// ── Voice recording ───────────────────────────────────────────────────────────
let speechRecognizer = null, isRecording = false, mediaRecorder = null, audioChunks = [];

async function toggleVoiceRecording() {
  const micBtn = document.getElementById('composerActionBtn');
  const input  = document.getElementById('messageInput');

  if (isRecording) {
    try { speechRecognizer?.stop(); } catch (_) {}
    if (mediaRecorder?.state === 'recording') try { mediaRecorder.stop(); } catch (_) {}
    isRecording = false;
    micBtn?.classList.remove('recording');
    showToast('Voice recording stopped');
    return;
  }

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SR) {
    try {
      speechRecognizer = new SR();
      speechRecognizer.continuous = false;
      speechRecognizer.interimResults = true;
      speechRecognizer.lang = navigator.language || 'en-IN';
      speechRecognizer.onstart  = () => { isRecording = true; micBtn?.classList.add('recording'); showToast('\uD83C\uDF99\uFE0F Listening... Speak your claim'); };
      speechRecognizer.onresult = (e) => {
        let t = '';
        for (let i = e.resultIndex; i < e.results.length; ++i) t += e.results[i][0].transcript;
        if (input) { input.value = t; if (t.trim()) document.getElementById('composerActionBtn')?.classList.add('has-text'); }
      };
      speechRecognizer.onerror = (e) => {
        isRecording = false; micBtn?.classList.remove('recording');
        (e.error === 'network' || e.error === 'not-allowed') ? startMediaRecorderFallback() : showToast(`Microphone notice: ${e.error}`);
      };
      speechRecognizer.onend = () => {
        isRecording = false; micBtn?.classList.remove('recording');
        if (input?.value.trim()) showToast('Voice captured! Click send or press Enter to verify.');
      };
      speechRecognizer.start();
      return;
    } catch (err) { console.warn('SR fallback:', err); }
  }
  startMediaRecorderFallback();
}

async function startMediaRecorderFallback() {
  const micBtn = document.getElementById('composerActionBtn');
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks  = [];
    const preferred = ['audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus','audio/ogg'];
    const mimeType  = preferred.find(t => MediaRecorder.isTypeSupported(t)) || '';
    mediaRecorder   = new MediaRecorder(stream, mimeType ? { mimeType } : {});

    mediaRecorder.onstart = () => { isRecording = true; micBtn?.classList.add('recording'); showToast('\uD83C\uDF99\uFE0F Recording... Click mic again when done'); };
    mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.push(e.data); };
    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      isRecording = false; micBtn?.classList.remove('recording');
      const actualMime = mediaRecorder.mimeType || mimeType || 'audio/webm';
      const ext = actualMime.includes('ogg') ? 'ogg' : actualMime.includes('wav') ? 'wav' : 'webm';
      const blob = new Blob(audioChunks, { type: actualMime });
      if (blob.size < 100) return;
      if (blob.size > 2_000_000) { showToast('Voice note too large (max 2 MB). Please record a shorter clip.'); return; }
      showToast('Transcribing voice note... \uD83C\uDF99\uFE0F');
      try {
        const data = await uploadVoiceAudio(blob, `voice_note.${ext}`);
        if (data?.success && data.text) { store.setActiveChat('bot'); sendMessage(data.text.trim()); showToast('Voice claim captured! \u2713'); }
        else showToast('Could not transcribe voice note.');
      } catch (err) { console.error('Audio error:', err); showToast(err.message || 'Audio transcription failed.'); }
    };
    mediaRecorder.start();
  } catch (err) { console.error('Mic access error:', err); showToast('Please allow microphone permissions.'); }
}

// ── DOM Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  renderSidebar(); renderChatArea(); renderPresenter();

  // Search
  document.getElementById('chatSearch')?.addEventListener('input', e => store.setSearchQuery(e.target.value));

  // Filter chips
  document.querySelectorAll('.chip').forEach(chip =>
    chip.addEventListener('click', () => {
      document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      store.setFilter(chip.getAttribute('data-filter') || 'all');
    })
  );

  // Composer
  const messageInput = document.getElementById('messageInput');
  const actionBtn    = document.getElementById('composerActionBtn');
  messageInput?.addEventListener('input', () =>
    actionBtn?.classList.toggle('has-text', messageInput.value.trim().length > 0)
  );
  messageInput?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  actionBtn?.addEventListener('click', () =>
    actionBtn.classList.contains('has-text') ? sendMessage() : toggleVoiceRecording()
  );

  // Attachment toggle
  const attachBtn   = document.getElementById('attachBtn');
  const attachPopup = document.getElementById('attachmentPopup');
  attachBtn?.addEventListener('click', e => {
    e.stopPropagation();
    if (attachPopup) attachPopup.style.display = attachPopup.style.display === 'flex' ? 'none' : 'flex';
  });

  // Image upload
  const imageUploadInput = document.getElementById('imageUploadInput');
  imageUploadInput?.addEventListener('change', e => {
    const file = e.target.files[0]; if (!file) return;
    e.target.value = '';
    const allowed = ['image/jpeg','image/png','image/webp'];
    if (!allowed.includes(file.type)) { showToast('Only JPEG, PNG and WebP images are supported.'); return; }
    if (file.size > 2_000_000) { showToast('Image too large. Please choose one under 2 MB.'); return; }
    const reader = new FileReader();
    reader.onload = evt => { store.setActiveChat('bot'); sendMessage('', { image: evt.target.result, rawFile: file }); };
    reader.readAsDataURL(file);
    closeAllPopups();
  });

  // PDF upload
  const docUploadInput = document.getElementById('docUploadInput');
  docUploadInput?.addEventListener('change', e => {
    const file = e.target.files[0]; if (!file) return;
    e.target.value = '';
    if (!file.name.toLowerCase().endsWith('.pdf') && file.type !== 'application/pdf') {
      showToast('Only PDF documents are supported.'); return;
    }
    if (file.size > 2_000_000) { showToast('PDF too large. Please choose one under 2 MB.'); return; }
    store.setActiveChat('bot');
    sendMessage('', { file: { name: file.name, size: file.size }, pdfFile: file });
    closeAllPopups();
  });

  // Stream delegation
  const streamEl = document.getElementById('messagesStream');
  streamEl?.addEventListener('click', e => {
    const fwdBtn = e.target.closest('.quick-forward-btn');
    if (fwdBtn) {
      e.stopPropagation();
      const msg = store.getActiveChat()?.messages.find(m => m.id === fwdBtn.getAttribute('data-msgid'));
      if (msg) openForwardModal(msg); return;
    }
    const retryBtn = e.target.closest('.msg-retry-btn');
    if (retryBtn) {
      const t = retryBtn.getAttribute('data-retry');
      if (t) { store.setActiveChat('bot'); runBotLifecycle(t); } return;
    }
    const copyBtn = e.target.closest('.copy-card-btn');
    if (copyBtn) {
      e.stopPropagation();
      navigator.clipboard.writeText(copyBtn.getAttribute('data-text') || '').then(() => showToast('Copied to clipboard \u2713')); return;
    }
    const ctxBtn = e.target.closest('.context-menu-btn');
    if (ctxBtn) { e.stopPropagation(); openContextMenuAt(e, ctxBtn.getAttribute('data-msgid')); }
  });

  streamEl?.addEventListener('contextmenu', e => {
    const bubble = e.target.closest('.msg-bubble');
    if (bubble) { e.preventDefault(); openContextMenuAt(e, bubble.getAttribute('data-msgid')); }
  });

  // Mobile back
  document.getElementById('mobileBackBtn')?.addEventListener('click', () => {
    document.querySelector('.chats-sidebar')?.classList.remove('hidden-mobile');
    document.querySelector('.chat-area')?.classList.add('hidden-mobile');
  });

  // Forward modal
  document.querySelectorAll('.forward-target-item').forEach(item =>
    item.addEventListener('click', () => forwardToTarget(item.getAttribute('data-target')))
  );
  document.getElementById('forwardCloseBtn')?.addEventListener('click', closeForwardModal);

  // Presenter panel
  document.getElementById('presenterCloseBtn')?.addEventListener('click', () => store.togglePresenter(false));
  document.getElementById('presenterCopyBtn')?.addEventListener('click', () => {
    const t = document.getElementById('presenterJson')?.textContent;
    if (t) navigator.clipboard.writeText(t).then(() => showToast('Presenter JSON copied \u2713'));
  });

  // Keyboard shortcuts
  window.addEventListener('keydown', e => {
    if (e.ctrlKey && e.shiftKey && (e.key === 'D' || e.key === 'd')) { e.preventDefault(); store.togglePresenter(); }
    if (e.key === 'Escape') { closeAllPopups(); closeForwardModal(); store.togglePresenter(false); }
  });

  // Context menu actions
  document.querySelectorAll('.context-action-item').forEach(item =>
    item.addEventListener('click', () => handleContextAction(item.getAttribute('data-action')))
  );
});

// ── Context menu ──────────────────────────────────────────────────────────────
function openContextMenuAt(e, msgId) {
  closeAllPopups();
  contextTargetMessageId = msgId;
  const menu = document.getElementById('messageContextMenu');
  if (menu) {
    menu.style.display = 'block';
    menu.style.left    = `${Math.min(e.pageX, window.innerWidth  - 200)}px`;
    menu.style.top     = `${Math.min(e.pageY, window.innerHeight - 300)}px`;
  }
}

function handleContextAction(action) {
  closeAllPopups();
  if (!contextTargetMessageId) return;
  const msg = store.getActiveChat()?.messages.find(m => m.id === contextTargetMessageId);
  if (!msg) return;

  if (action === 'forward') {
    openForwardModal(msg);
  } else if (action === 'copy') {
    const text = msg.text || (msg.cardData ? `${msg.cardData.plain_verdict}: ${msg.cardData.short_reason}` : '');
    navigator.clipboard.writeText(text).then(() => showToast('Message copied \u2713'));
  } else if (action === 'reply') {
    const input = document.getElementById('messageInput');
    if (input) { input.value = `> Replying to ${msg.sender}: "${(msg.text||'').substring(0,50)}..."\n`; input.focus(); }
  } else if (action === 'delete') {
    store.deleteMessage(store.activeChatId, contextTargetMessageId);
    showToast('Message deleted');
  } else if (action === 'star') {
    showToast('Message starred \u2B50');
  }
}