/**
 * forward.js - Forward message to contacts and SatyaSetu Bot
 */

import { store } from '../state.js';
import { sendMessage } from './send.js';

let messageToForward = null;

export function openForwardModal(msg) {
  messageToForward = msg;
  const modal = document.getElementById("forwardModal");
  const preview = document.getElementById("forwardMsgPreview");
  if (preview) {
    preview.textContent = msg.text || "Forwarded media";
  }
  if (modal) {
    modal.classList.add("active");
  }
}

export function closeForwardModal() {
  const modal = document.getElementById("forwardModal");
  if (modal) {
    modal.classList.remove("active");
  }
  messageToForward = null;
}

export function forwardToTarget(targetId) {
  if (!messageToForward) return;
  const msg = messageToForward;
  closeForwardModal();

  // Switch to target chat
  store.setActiveChat(targetId);

  const forwardedText = msg.text || "";
  const forwardedImage = msg.image || null;

  if (targetId === "bot") {
    // When forwarding to SatyaSetu Bot, submit for verification
    const forwardIndicatorText = `[Forwarded from ${msg.sender || 'Chat'}]: ${forwardedText}`;
    sendMessage(forwardIndicatorText, {
      image: forwardedImage,
      rawFile: msg.rawFile || null
    });
    showToast("Message forwarded to SatyaSetu Bot for fact checking! 🛡️");
  } else {
    // Forwarding to ordinary user/group chat
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }).toLowerCase();
    const targetChat = store.chats[targetId];

    const fwdMsg = {
      id: "fwd-" + Date.now(),
      sender: "You",
      isMe: true,
      forwarded: "many",
      text: forwardedText,
      image: forwardedImage,
      time: timeStr,
      status: "✓✓"
    };

    store.addMessage(targetId, fwdMsg);
    showToast(`Forwarded to ${targetChat ? targetChat.name : 'chat'} ✓`);
  }
}

export function showToast(text) {
  let toast = document.getElementById("waToast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "waToast";
    document.body.appendChild(toast);
  }
  toast.textContent = text;
  toast.classList.add("visible");
  setTimeout(() => {
    toast.classList.remove("visible");
  }, 2500);
}
