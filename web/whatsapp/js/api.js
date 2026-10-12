/**
 * api.js - API client for SatyaSetu Backend
 */

export async function checkClaim(text) {
  const startTime = performance.now();
  const res = await fetch("/api/check", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ text })
  });

  const latencyMs = Math.round(performance.now() - startTime);

  if (!res.ok) {
    let errorDetail = `HTTP ${res.status}`;
    try {
      const errJson = await res.json();
      if (errJson.detail) errorDetail = errJson.detail;
      else if (errJson.error) errorDetail = errJson.error;
    } catch (_) {}
    throw new Error(errorDetail);
  }

  const data = await res.json();
  return { data, latencyMs };
}

export async function fetchDemoConfig() {
  try {
    const res = await fetch("/api/demo/config");
    if (res.ok) {
      return await res.json();
    }
  } catch (err) {
    console.warn("Failed to fetch demo config:", err);
  }
  return null;
}

export async function uploadOcrImage(file) {
  const formData = new FormData();
  formData.append("file", file, file.name || "screenshot.png");
  const res = await fetch("/api/ocr", {
    method: "POST",
    body: formData
  });
  if (!res.ok) {
    let msg = `OCR error HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (j.detail) msg = j.detail;
    } catch (_) {}
    throw new Error(msg);
  }
  return await res.json();
}

export async function uploadVoiceAudio(blob, filename = "voice_note.webm") {
  const formData = new FormData();
  formData.append("file", blob, filename);
  const res = await fetch("/api/voice", {
    method: "POST",
    body: formData
  });
  if (!res.ok) {
    let msg = `Voice error HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (j.detail) msg = j.detail;
    } catch (_) {}
    throw new Error(msg);
  }
  return await res.json();
}

export async function uploadPdf(file) {
  const formData = new FormData();
  formData.append("file", file, file.name || "document.pdf");
  const res = await fetch("/api/pdf", {
    method: "POST",
    body: formData
  });
  if (!res.ok) {
    let msg = `PDF error HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (j.detail) msg = j.detail;
    } catch (_) {}
    throw new Error(msg);
  }
  return await res.json();
}
