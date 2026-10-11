/**
 * typing.js - Typing indicator bubble controller
 */

export function showTypingIndicator() {
  const container = document.getElementById("typingIndicatorContainer");
  if (container) {
    container.style.display = "block";
    const stream = document.getElementById("messagesStream");
    if (stream) stream.scrollTop = stream.scrollHeight;
  }
}

export function hideTypingIndicator() {
  const container = document.getElementById("typingIndicatorContainer");
  if (container) {
    container.style.display = "none";
  }
}
