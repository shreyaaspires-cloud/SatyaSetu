/**
 * main.js - Main Application Entry for SatyaSetu WhatsApp Web
 */

import { store } from './state.js';
import { escapeHtml } from './utils/escape.js';
import { formatWhatsAppText } from './utils/format.js';
import { sendMessage, runBotLifecycle } from './features/send.js';
import { openForwardModal, closeForwardModal, forwardToTarget, showToast } from './features/forward.js';
import { uploadVoiceAudio } from './api.js';

let contextTargetMessageId = null;

// ── Render Contacts Sidebar ──
function renderSidebar() {
  const listEl = document.getElementById("contactsList");
  if (!listEl) return;

  const chats = store.chats;
  const currentChatId = store.activeChatId;
  const query = store.searchQuery;
  const filter = store.activeFilter;

  listEl.innerHTML = "";

  Object.values(chats).forEach(chat => {
    // Search query filter
    if (query) {
      const matchName = chat.name.toLowerCase().includes(query);
      const matchMsg = (chat.lastMsg || "").toLowerCase().includes(query);
      if (!matchName && !matchMsg) return;
    }

    // Filter chip filter
    if (filter === "unread" && !chat.unread) return;
    if (filter === "favourites" && !(chat.isBot || chat.id === "sharma")) return;
    if (filter === "groups" && (chat.isBot || chat.id === "mummy" || chat.id === "papa")) return;

    const item = document.createElement("div");
    item.className = `contact-item ${chat.id === currentChatId ? 'active' : ''}`;
    item.id = `item-${chat.id}`;
    item.onclick = () => {
      store.setActiveChat(chat.id);
      // On mobile, switch to chat area
      const sidebar = document.querySelector(".chats-sidebar");
      const chatArea = document.querySelector(".chat-area");
      if (window.innerWidth <= 768) {
        if (sidebar) sidebar.classList.add("hidden-mobile");
        if (chatArea) chatArea.classList.remove("hidden-mobile");
      }
    };

    const avatarHtml = chat.isBot
      ? `<div class="contact-avatar bot-avatar">🛡️</div>`
      : `<div class="contact-avatar" style="background:${escapeHtml(chat.color)};">${escapeHtml(chat.avatar)}</div>`;

    const verifiedHtml = chat.isBot
      ? `<svg class="verified-badge" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>`
      : '';

    const pinHtml = chat.pinned
      ? `<svg class="pin-icon" width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/></svg>`
      : '';

    const unreadHtml = chat.unread > 0
      ? `<span class="contact-unread-badge">${chat.unread}</span>`
      : '';

    item.innerHTML = `
      ${avatarHtml}
      <div class="contact-info">
        <div class="contact-top">
          <span class="contact-name">${escapeHtml(chat.name)} ${verifiedHtml}</span>
          <span class="contact-time">${escapeHtml(chat.time || '')}</span>
        </div>
        <div class="contact-bottom">
          <span class="contact-last-msg">${escapeHtml(chat.lastMsg || '')}</span>
          ${pinHtml}
          ${unreadHtml}
        </div>
      </div>
    `;

    listEl.appendChild(item);
  });
}

// ── Render Active Chat Area ──
function renderChatArea() {
  const chat = store.getActiveChat();
  if (!chat) return;

  // Header info
  const titleEl = document.getElementById("headerTitle");
  const subEl = document.getElementById("headerSub");
  const avatarEl = document.getElementById("headerAvatar");

  if (titleEl) titleEl.textContent = chat.name;
  if (subEl) subEl.textContent = chat.sub;
  if (avatarEl) {
    avatarEl.textContent = chat.avatar;
    avatarEl.style.background = chat.color;
  }

  // Stream messages
  const stream = document.getElementById("messagesStream");
  if (!stream) return;

  stream.innerHTML = "";

  // Date Header Pill
  const datePill = document.createElement("div");
  datePill.className = "date-pill";
  datePill.textContent = chat.id === "sharma" ? "TODAY" : "YESTERDAY";
  stream.appendChild(datePill);

  if (chat.isBot) {
    const encPill = document.createElement("div");
    encPill.className = "encryption-pill";
    encPill.innerHTML = `<span>🔒</span> Official SatyaSetu AI Bot. End-to-end verified pipeline. Never shares your number.`;
    stream.appendChild(encPill);
  }

  chat.messages.forEach(msg => {
    const row = document.createElement("div");
    row.className = `msg-row ${msg.isMe ? 'outgoing' : 'incoming'}`;
    row.id = msg.id;

    let fwdHtml = "";
    if (msg.forwarded === "many") {
      fwdHtml = `<div class="msg-forward-header"><span>↪</span> Forwarded many times</div>`;
    } else if (msg.forwarded) {
      fwdHtml = `<div class="msg-forward-header"><span>↪</span> Forwarded</div>`;
    }

    let quotedHtml = "";
    if (msg.quoted) {
      quotedHtml = `
        <div class="msg-quoted">
          <div class="msg-quoted-title">${escapeHtml(msg.quoted.author)}</div>
          <div>${formatWhatsAppText(msg.quoted.text)}</div>
        </div>
      `;
    }

    let imageHtml = "";
    if (msg.image) {
      imageHtml = `
        <div style="margin-bottom:6px;border-radius:8px;overflow:hidden;max-height:240px;">
          <img src="${escapeHtml(msg.image)}" style="width:100%;height:auto;display:block;" alt="attachment">
        </div>
      `;
    }

    let retryHtml = "";
    if (msg.isError && msg.retryClaim) {
      retryHtml = `
        <div>
          <button class="msg-retry-btn" data-retry="${escapeHtml(msg.retryClaim)}">
            ↻ Retry Verification
          </button>
        </div>
      `;
    }

    const senderHeader = (!msg.isMe && !chat.isBot && (chat.id === "sharma" || chat.id === "rishtedar" || chat.id === "society" || chat.id === "friends"))
      ? `<div class="msg-sender">${escapeHtml(msg.sender)}</div>` : '';

    const contentHtml = formatWhatsAppText(msg.text);

    row.innerHTML = `
      <div class="msg-bubble" data-msgid="${escapeHtml(msg.id)}">
        <div class="msg-hover-actions">
          <span class="msg-action-icon quick-forward-btn" title="Forward message" data-msgid="${escapeHtml(msg.id)}">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="15 17 20 12 15 7"/><path d="M4 18v-2a4 4 0 0 1 4-4h12"/></svg>
          </span>
          <span class="msg-action-icon context-menu-btn" title="Options" data-msgid="${escapeHtml(msg.id)}">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M7 10l5 5 5-5z"/></svg>
          </span>
        </div>
        ${senderHeader}
        ${fwdHtml}
        ${quotedHtml}
        ${imageHtml}
        <div class="msg-content-text">${contentHtml}</div>
        ${retryHtml}
        <div class="msg-meta">
          <span>${escapeHtml(msg.time || '')}</span>
          ${msg.status ? `<span class="msg-ticks">${escapeHtml(msg.status)}</span>` : ''}
        </div>
      </div>
    `;

    stream.appendChild(row);
  });

  // Disclaimer footer
  const disclaimer = document.createElement("div");
  disclaimer.className = "simulated-disclaimer";
  disclaimer.textContent = "Simulated interface for demonstration. Not affiliated with WhatsApp or Meta.";
  stream.appendChild(disclaimer);

  stream.scrollTop = stream.scrollHeight;
}

// ── Render Presenter Panel (Ctrl+Shift+D) ──
function renderPresenter() {
  const panel = document.getElementById("presenterPanel");
  if (!panel) return;

  if (store.isPresenterOpen) {
    panel.classList.add("visible");
  } else {
    panel.classList.remove("visible");
    return;
  }

  const data = store.lastPresenterData;
  const verdictEl = document.getElementById("presenterVerdict");
  const strengthEl = document.getElementById("presenterStrength");
  const latencyEl = document.getElementById("presenterLatency");
  const jsonPre = document.getElementById("presenterJson");

  if (data) {
    if (verdictEl) verdictEl.textContent = data.verdict;
    if (strengthEl) strengthEl.textContent = data.evidence_strength;
    if (latencyEl) latencyEl.textContent = `${data.latencyMs} ms`;
    if (jsonPre) jsonPre.textContent = JSON.stringify(data.rawResponse, null, 2);
  } else {
    if (verdictEl) verdictEl.textContent = "IDLE";
    if (strengthEl) strengthEl.textContent = "N/A";
    if (latencyEl) latencyEl.textContent = "0 ms";
    if (jsonPre) jsonPre.textContent = "// No verification has been executed yet.\n// Send a claim to SatyaSetu to inspect pipeline telemetry.";
  }
}

// ── Main UI Subscriber ──
store.subscribe(() => {
  renderSidebar();
  renderChatArea();
  renderPresenter();
});

// ── Global Context & Dropdown Handlers ──
function closeAllPopups() {
  const msgMenu = document.getElementById("messageContextMenu");
  const chatMenu = document.getElementById("chatOptionsMenu");
  const attachPopup = document.getElementById("attachmentPopup");
  if (msgMenu) msgMenu.style.display = "none";
  if (chatMenu) chatMenu.style.display = "none";
  if (attachPopup) attachPopup.style.display = "none";
}

window.addEventListener("click", () => {
  closeAllPopups();
});

// ── Voice Input (Web Speech API + MediaRecorder Fallback) ──
let speechRecognizer = null;
let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];

async function toggleVoiceRecording() {
  const micBtn = document.getElementById("composerActionBtn");
  const input = document.getElementById("messageInput");

  if (isRecording) {
    if (speechRecognizer) {
      try { speechRecognizer.stop(); } catch (_) {}
    }
    if (mediaRecorder && mediaRecorder.state === "recording") {
      try { mediaRecorder.stop(); } catch (_) {}
    }
    isRecording = false;
    if (micBtn) micBtn.classList.remove("recording");
    showToast("Voice recording stopped");
    return;
  }

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (SpeechRecognition) {
    try {
      speechRecognizer = new SpeechRecognition();
      speechRecognizer.continuous = false;
      speechRecognizer.interimResults = true;
      speechRecognizer.lang = 'en-IN';

      speechRecognizer.onstart = () => {
        isRecording = true;
        if (micBtn) micBtn.classList.add("recording");
        showToast("🎙️ Listening... Speak your claim");
      };

      speechRecognizer.onresult = (e) => {
        let transcript = "";
        for (let i = e.resultIndex; i < e.results.length; ++i) {
          transcript += e.results[i][0].transcript;
        }
        if (input) {
          input.value = transcript;
          const actionBtn = document.getElementById("composerActionBtn");
          if (actionBtn && transcript.trim()) actionBtn.classList.add("has-text");
        }
      };

      speechRecognizer.onerror = (e) => {
        console.warn("Speech recognition notice:", e.error);
        isRecording = false;
        if (micBtn) micBtn.classList.remove("recording");
        if (e.error === 'network' || e.error === 'not-allowed') {
          startMediaRecorderFallback();
        } else {
          showToast(`Microphone notice: ${e.error}`);
        }
      };

      speechRecognizer.onend = () => {
        isRecording = false;
        if (micBtn) micBtn.classList.remove("recording");
        if (input && input.value.trim()) {
          showToast("Voice captured! Click send or press Enter to verify.");
        }
      };

      speechRecognizer.start();
      return;
    } catch (err) {
      console.warn("SpeechRecognition fallback triggered:", err);
    }
  }

  startMediaRecorderFallback();
}

async function startMediaRecorderFallback() {
  const micBtn = document.getElementById("composerActionBtn");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];
    mediaRecorder = new MediaRecorder(stream);

    mediaRecorder.onstart = () => {
      isRecording = true;
      if (micBtn) micBtn.classList.add("recording");
      showToast("🎙️ Recording audio... Click mic again when done");
    };

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.push(e.data);
    };

    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(track => track.stop());
      isRecording = false;
      if (micBtn) micBtn.classList.remove("recording");

      const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
      if (audioBlob.size < 100) return;

      showToast("Transcribing voice note with backend... 🎙️");
      try {
        const data = await uploadVoiceAudio(audioBlob);
        if (data && data.success && data.text) {
          store.setActiveChat("bot");
          sendMessage(`[Voice Note]: "${data.text}"`);
          showToast("Voice claim verified! ✓");
        } else {
          showToast("Could not transcribe voice note.");
        }
      } catch (err) {
        console.error("Audio error:", err);
        showToast("Audio transcription failed.");
      }
    };

    mediaRecorder.start();
  } catch (err) {
    console.error("Mic access error:", err);
    showToast("Please allow microphone permissions.");
  }
}

// ── DOM Initialization ──
document.addEventListener("DOMContentLoaded", () => {
  // Initial render
  renderSidebar();
  renderChatArea();
  renderPresenter();

  // Search input
  const searchInput = document.getElementById("chatSearch");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      store.setSearchQuery(e.target.value);
    });
  }

  // Filter chips
  document.querySelectorAll(".chip").forEach(chip => {
    chip.addEventListener("click", () => {
      document.querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      const filter = chip.getAttribute("data-filter") || "all";
      store.setFilter(filter);
    });
  });

  // Composer Input
  const messageInput = document.getElementById("messageInput");
  const actionBtn = document.getElementById("composerActionBtn");

  if (messageInput) {
    messageInput.addEventListener("input", () => {
      if (actionBtn) {
        if (messageInput.value.trim().length > 0) {
          actionBtn.classList.add("has-text");
        } else {
          actionBtn.classList.remove("has-text");
        }
      }
    });

    messageInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  // Action button (Send or Mic)
  if (actionBtn) {
    actionBtn.addEventListener("click", () => {
      if (actionBtn.classList.contains("has-text")) {
        sendMessage();
      } else {
        toggleVoiceRecording();
      }
    });
  }

  // Attachment toggle
  const attachBtn = document.getElementById("attachBtn");
  const attachPopup = document.getElementById("attachmentPopup");
  if (attachBtn && attachPopup) {
    attachBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      attachPopup.style.display = attachPopup.style.display === "flex" ? "none" : "flex";
    });
  }

  // File Inputs
  const imageUploadInput = document.getElementById("imageUploadInput");
  if (imageUploadInput) {
    imageUploadInput.addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (evt) => {
        store.setActiveChat("bot");
        sendMessage("Sent screenshot image for fact-checking:", {
          image: evt.target.result,
          rawFile: file
        });
      };
      reader.readAsDataURL(file);
      closeAllPopups();
    });
  }

  const docUploadInput = document.getElementById("docUploadInput");
  if (docUploadInput) {
    docUploadInput.addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (!file) return;
      store.setActiveChat("bot");
      sendMessage(`[Document] ${file.name} - Please verify the claims in this circular`);
      closeAllPopups();
    });
  }

  // Event delegation on messages stream
  const streamEl = document.getElementById("messagesStream");
  if (streamEl) {
    streamEl.addEventListener("click", (e) => {
      // Quick forward button
      const fwdBtn = e.target.closest(".quick-forward-btn");
      if (fwdBtn) {
        e.stopPropagation();
        const msgId = fwdBtn.getAttribute("data-msgid");
        const chat = store.getActiveChat();
        const msg = chat ? chat.messages.find(m => m.id === msgId) : null;
        if (msg) openForwardModal(msg);
        return;
      }

      // Retry button
      const retryBtn = e.target.closest(".msg-retry-btn");
      if (retryBtn) {
        const claimText = retryBtn.getAttribute("data-retry");
        if (claimText) {
          store.setActiveChat("bot");
          runBotLifecycle(claimText);
        }
        return;
      }

      // Context menu toggle
      const contextBtn = e.target.closest(".context-menu-btn");
      if (contextBtn) {
        e.stopPropagation();
        const msgId = contextBtn.getAttribute("data-msgid");
        openContextMenuAt(e, msgId);
        return;
      }
    });

    streamEl.addEventListener("contextmenu", (e) => {
      const bubble = e.target.closest(".msg-bubble");
      if (bubble) {
        e.preventDefault();
        const msgId = bubble.getAttribute("data-msgid");
        openContextMenuAt(e, msgId);
      }
    });
  }

  // Mobile Back Button
  const mobileBackBtn = document.getElementById("mobileBackBtn");
  if (mobileBackBtn) {
    mobileBackBtn.addEventListener("click", () => {
      const sidebar = document.querySelector(".chats-sidebar");
      const chatArea = document.querySelector(".chat-area");
      if (sidebar) sidebar.classList.remove("hidden-mobile");
      if (chatArea) chatArea.classList.add("hidden-mobile");
    });
  }

  // Forward Modal Targets
  document.querySelectorAll(".forward-target-item").forEach(item => {
    item.addEventListener("click", () => {
      const targetId = item.getAttribute("data-target");
      if (targetId) forwardToTarget(targetId);
    });
  });

  const forwardCloseBtn = document.getElementById("forwardCloseBtn");
  if (forwardCloseBtn) {
    forwardCloseBtn.addEventListener("click", closeForwardModal);
  }

  // Presenter Panel Controls
  const presenterCloseBtn = document.getElementById("presenterCloseBtn");
  if (presenterCloseBtn) {
    presenterCloseBtn.addEventListener("click", () => store.togglePresenter(false));
  }

  const presenterCopyBtn = document.getElementById("presenterCopyBtn");
  if (presenterCopyBtn) {
    presenterCopyBtn.addEventListener("click", () => {
      const jsonPre = document.getElementById("presenterJson");
      if (jsonPre) {
        navigator.clipboard.writeText(jsonPre.textContent).then(() => {
          showToast("Presenter JSON copied to clipboard ✓");
        });
      }
    });
  }

  // Keyboard Shortcuts: Ctrl+Shift+D for Presenter Panel, Escape to close modals
  window.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.shiftKey && (e.key === "D" || e.key === "d")) {
      e.preventDefault();
      store.togglePresenter();
    }
    if (e.key === "Escape") {
      closeAllPopups();
      closeForwardModal();
      store.togglePresenter(false);
    }
  });

  // Context Menu Actions (Copy, Reply, Star, Delete, Forward)
  document.querySelectorAll(".context-action-item").forEach(item => {
    item.addEventListener("click", () => {
      const action = item.getAttribute("data-action");
      handleContextAction(action);
    });
  });
});

function openContextMenuAt(e, msgId) {
  closeAllPopups();
  contextTargetMessageId = msgId;
  const menu = document.getElementById("messageContextMenu");
  if (menu) {
    menu.style.display = "block";
    menu.style.left = `${Math.min(e.pageX, window.innerWidth - 200)}px`;
    menu.style.top = `${Math.min(e.pageY, window.innerHeight - 300)}px`;
  }
}

function handleContextAction(action) {
  closeAllPopups();
  if (!contextTargetMessageId) return;

  const chat = store.getActiveChat();
  const msg = chat ? chat.messages.find(m => m.id === contextTargetMessageId) : null;
  if (!msg) return;

  if (action === "forward") {
    openForwardModal(msg);
  } else if (action === "copy") {
    navigator.clipboard.writeText(msg.text || "").then(() => {
      showToast("Message copied to clipboard ✓");
    });
  } else if (action === "reply") {
    const input = document.getElementById("messageInput");
    if (input) {
      input.value = `> Replying to ${msg.sender}: "${(msg.text || '').substring(0, 50)}..."\n`;
      input.focus();
    }
  } else if (action === "delete") {
    store.deleteMessage(store.activeChatId, contextTargetMessageId);
    showToast("Message deleted");
  } else if (action === "star") {
    showToast("Message starred ⭐");
  }
}
