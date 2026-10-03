const $ = (id) => document.getElementById(id);
const captions = $("captions"), statusEl = $("status"), toggle = $("toggle");
let ws, ctx, stream, node, listening = false;
const spoken = new Set();          // segment ids already sent to TTS
const audioQueue = [];
let playing = false;

function setStatus(t) { statusEl.textContent = t; }

function render(lines, live) {
  captions.replaceChildren();
  const add = (l, cls) => {
    const div = document.createElement("div");
    div.className = "line " + cls;
    const tr = document.createElement("div");
    tr.className = "tr";
    tr.textContent = l.translation || (cls === "live" ? "…" : "translating…");
    if (!l.translation && cls !== "live") div.classList.add("pending");
    const src = document.createElement("div");
    src.className = "src";
    src.textContent = l.source;
    div.append(tr, src);
    if (cls === "final" && l.segment_id) tr.onclick = () => correct(l, tr);
    captions.append(div);
  };
  lines.forEach((l) => add(l, "final"));
  if (live && live.source) add(live, "live");
  captions.scrollTop = captions.scrollHeight;
  if ($("speak").checked) lines.forEach(speak);
}

async function correct(line, el) {
  const fixed = prompt("Correct translation:", line.translation);
  if (!fixed || fixed === line.translation) return;
  const r = await fetch("/api/corrections", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ segment_id: line.segment_id, translation: fixed }),
  });
  if (r.ok) { line.translation = fixed; el.textContent = fixed; setStatus("Correction saved ✓"); }
}

function speak(line) {
  if (!line.segment_id || !line.translation || spoken.has(line.segment_id)) return;
  spoken.add(line.segment_id);
  audioQueue.push(line.translation);
  playNext();
}
async function playNext() {
  if (playing || !audioQueue.length) return;
  playing = true;
  try {
    const r = await fetch("/api/tts", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ text: audioQueue.shift() }),
    });
    if (r.ok) {
      const a = new Audio(URL.createObjectURL(await r.blob()));
      await new Promise((res) => { a.onended = res; a.onerror = res; a.play().catch(res); });
    }
  } finally { playing = false; playNext(); }
}

async function start() {
  stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  ctx = new AudioContext();
  await ctx.audioWorklet.addModule("pcm-worklet.js");
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws?src=${$("src").value}&tgt=${$("tgt").value}`);
  ws.binaryType = "arraybuffer";
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.type === "ready") setStatus(m.gemini ? "Listening…" : "Listening (set GEMINI_API_KEY to enable translation)");
    else if (m.type === "update") render(m.lines, m.live);
    else if (m.type === "error") { setStatus(m.error); stop(false); }
    else if (m.type === "done") { setStatus("Finished"); ws.close(); }
  };
  ws.onclose = () => { if (listening) stop(false); };
  ws.onopen = () => {
    node = new AudioWorkletNode(ctx, "pcm-worklet");
    node.port.onmessage = (e) => { if (ws.readyState === 1) ws.send(e.data); };
    ctx.createMediaStreamSource(stream).connect(node);
  };
  listening = true; toggle.textContent = "Stop"; toggle.classList.add("on");
  setStatus("Connecting…");
}

function stop(graceful = true) {
  listening = false;
  toggle.textContent = "Start listening"; toggle.classList.remove("on");
  stream?.getTracks().forEach((t) => t.stop());
  node?.disconnect(); ctx?.close();
  if (graceful && ws?.readyState === 1) { ws.send("stop"); setStatus("Finishing…"); }
}

toggle.onclick = () => (listening ? stop() : start().catch((e) => setStatus("Mic error: " + e.message)));
