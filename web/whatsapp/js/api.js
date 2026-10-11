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
  formData.append("file", file);
  const res = await fetch("/api/ocr", {
    method: "POST",
    body: formData
  });
  if (!res.ok) throw new Error(`OCR error HTTP ${res.status}`);
  return await res.json();
}

export async function uploadVoiceAudio(file) {
  const formData = new FormData();
  formData.append("file", file, "voice_note.wav");
  const res = await fetch("/api/voice", {
    method: "POST",
    body: formData
  });
  if (!res.ok) throw new Error(`Voice error HTTP ${res.status}`);
  return await res.json();
}
