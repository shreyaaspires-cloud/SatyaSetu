/**
 * send.js - Message Sending and Bot Verification Lifecycle
 */

import { store } from '../state.js';
import { checkClaim, uploadOcrImage, uploadPdf } from '../api.js';
import { showTypingIndicator, hideTypingIndicator } from './typing.js';

export async function sendMessage(textToSend, extraData = {}) {
  const input = document.getElementById("messageInput");
  const text = (textToSend !== undefined ? textToSend : (input ? input.value : "")).trim();

  if (!text && !extraData.image && !extraData.file) return;

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
    file: extraData.file || null,
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

  const now = new Date();
  const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }).toLowerCase();

  // ── Image Attachment Handling ──
  if (extraData.rawFile) {
    showTypingIndicator();
    try {
      const ocrResult = await uploadOcrImage(extraData.rawFile);
      hideTypingIndicator();
      if (!ocrResult || !ocrResult.success || !ocrResult.text || !ocrResult.text.trim()) {
        const botFailMsg = {
          id: "bot-ocr-fail-" + Date.now(),
          sender: "SatyaSetu",
          isMe: false,
          text: "I couldn't read any text in this image. Try a clearer screenshot.",
          time: timeStr,
          status: ""
        };
        store.addMessage("bot", botFailMsg);
        return;
      }
      queryText = ocrResult.text.trim();
    } catch (ocrErr) {
      hideTypingIndicator();
      const botErrMsg = {
        id: "bot-ocr-err-" + Date.now(),
        sender: "SatyaSetu",
        isMe: false,
        text: ocrErr.message || "Failed to process image.",
        isError: true,
        time: timeStr,
        status: ""
      };
      store.addMessage("bot", botErrMsg);
      return;
    }
  }

  // ── PDF Attachment Handling ──
  let pdfNote = "";
  if (extraData.pdfFile) {
    showTypingIndicator();
    try {
      const pdfResult = await uploadPdf(extraData.pdfFile);
      hideTypingIndicator();
      if (!pdfResult || !pdfResult.success || !pdfResult.text || !pdfResult.text.trim()) {
        const botFailMsg = {
          id: "bot-pdf-fail-" + Date.now(),
          sender: "SatyaSetu",
          isMe: false,
          text: "I couldn't read any text in this PDF. Please check the document.",
          time: timeStr,
          status: ""
        };
        store.addMessage("bot", botFailMsg);
        return;
      }
      queryText = pdfResult.text.trim();
      pdfNote = `📄 Document checked (${pdfResult.page_count} pages, ${pdfResult.extraction_method})`;
    } catch (pdfErr) {
      hideTypingIndicator();
      const botErrMsg = {
        id: "bot-pdf-err-" + Date.now(),
        sender: "SatyaSetu",
        isMe: false,
        text: pdfErr.message || "Failed to process PDF file.",
        isError: true,
        time: timeStr,
        status: ""
      };
      store.addMessage("bot", botErrMsg);
      return;
    }
  }

  // Step 1: Immediate acknowledgement bubble
  const ackMsg = {
    id: "bot-ack-" + Date.now(),
    sender: "SatyaSetu",
    isMe: false,
    text: pdfNote ? `${pdfNote}\nChecking claims… 🔍` : "Received! Checking this claim… 🔍",
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
      verdict: data.verdict || data.overall_verdict || "UNKNOWN",
      evidence_strength: data.evidence_strength || "N/A",
      latencyMs: latencyMs,
      timestamp: new Date().toISOString(),
      rawResponse: data
    });

    // Step 4: Bot card reply
    const replyContent = data.formatted_reply || data.explanation || "No verdict returned by backend.";
    const respTimeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }).toLowerCase();

    const botReplyMsg = {
      id: "bot-" + Date.now(),
      sender: "SatyaSetu",
      isMe: false,
      text: replyContent,
      cardData: data,
      time: respTimeStr,
      status: ""
    };
    store.addMessage("bot", botReplyMsg);

  } catch (err) {
    console.error("Fact check request failed:", err);
    hideTypingIndicator();

    // Truthful system failure notice
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
