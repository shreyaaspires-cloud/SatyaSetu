/**
 * send.js - Message Sending and Bot Verification Lifecycle
 */

import { store } from '../state.js';
import { checkClaim, uploadOcrImage } from '../api.js';
import { showTypingIndicator, hideTypingIndicator } from './typing.js';

export async function sendMessage(textToSend, extraData = {}) {
  const input = document.getElementById("messageInput");
  const text = (textToSend !== undefined ? textToSend : (input ? input.value : "")).trim();

  if (!text && !extraData.image) return;

  if (textToSend === undefined && input) {
    input.value = "";
    const actionBtn = document.getElementById("composerActionBtn");
    if (actionBtn) {
      actionBtn.classList.remove("has-text");
    }
  }

  const now = new Date();
  const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }).toLowerCase();

  const userMsg = {
    id: "usr-" + Date.now(),
    sender: "You",
    isMe: true,
    text: text,
    image: extraData.image || null,
    time: timeStr,
    status: "✓✓"
  };

  const activeChatId = store.activeChatId;
  store.addMessage(activeChatId, userMsg);

  // If in SatyaSetu Bot chat, execute verification lifecycle
  if (activeChatId === "bot") {
    await runBotLifecycle(text, extraData);
  }
}

export async function runBotLifecycle(claimText, extraData = {}) {
  let queryText = (claimText || "").trim();
  queryText = queryText
    .replace(/^\[Forwarded\s+from[^\]]+\]:\s*/i, "")
    .replace(/^Forwarded:\s*/i, "")
    .trim();

  // If user sent image screenshot and query is brief, attempt OCR
  if (extraData.rawFile && (!queryText || queryText.length < 5)) {
    try {
      const ocrResult = await uploadOcrImage(extraData.rawFile);
      if (ocrResult && ocrResult.text && ocrResult.text.trim()) {
        queryText = ocrResult.text.trim();
      }
    } catch (ocrErr) {
      console.warn("OCR fallback note:", ocrErr);
    }
  }

  const now = new Date();
  const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }).toLowerCase();

  // Step 1: Immediate acknowledgement bubble
  const ackMsg = {
    id: "bot-ack-" + Date.now(),
    sender: "SatyaSetu",
    isMe: false,
    text: "Received! Checking this claim… 🔍",
    time: timeStr,
    status: ""
  };
  store.addMessage("bot", ackMsg);

  // Step 2: Show typing indicator
  showTypingIndicator();

  // Step 3: Call backend /api/check
  try {
    const { data, latencyMs } = await checkClaim(queryText || "Verify this claim");

    hideTypingIndicator();

    // Update Presenter panel with real-time inspection data
    store.setPresenterData({
      query: queryText,
      verdict: data.overall_verdict || data.verdict || "UNKNOWN",
      evidence_strength: data.evidence_strength || "N/A",
      latencyMs: latencyMs,
      timestamp: new Date().toISOString(),
      rawResponse: data
    });

    // Step 4: Bot formatted reply text bubble (parity with Twilio webhook)
    const replyContent = data.formatted_reply || data.explanation || "No verdict returned by backend.";
    const respTimeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }).toLowerCase();

    const botReplyMsg = {
      id: "bot-" + Date.now(),
      sender: "SatyaSetu",
      isMe: false,
      text: replyContent,
      time: respTimeStr,
      status: ""
    };
    store.addMessage("bot", botReplyMsg);

  } catch (err) {
    console.error("Fact check request failed:", err);
    hideTypingIndicator();

    // Truthful system failure notice (F1, F2) - never invent verdicts
    const errTimeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }).toLowerCase();
    const botErrMsg = {
      id: "bot-err-" + Date.now(),
      sender: "SatyaSetu",
      isMe: false,
      text: "Couldn't check this right now. Please try again.",
      isError: true,
      retryClaim: queryText || claimText,
      time: errTimeStr,
      status: ""
    };
    store.addMessage("bot", botErrMsg);
  }
}
