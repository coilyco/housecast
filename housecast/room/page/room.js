// The room's shared client: the snapshot, its event stream, or a scripted demo.
// Contract: teable:coilyco-flight-deck/housecast#8168 (comment 20132).
(() => {
"use strict";

const PHASES = ["holding", "submissions", "grading", "split", "closing"];
const EVENT_KINDS = ["prompt", "answer", "divergence", "phase", "round", "grades"];
/** Pro-route timings measured in #8166, used to say when a subject runs long. */
const TYPICAL_S = 15;
const SLOW_S = 43;
const PROMPT_MAX = 280;
const REASON_MAX = 140;

// A subject looks as subjects.json says: label, colour, logo, role, line. One with
// no colour or logo still gets a glyph, so an unfamiliar file draws rather than breaks.
const FALLBACK = [
  { color: "#c5c3fd", emblem: "◆" },
  { color: "#e8d6cc", emblem: "▲" },
  { color: "#9083f9", emblem: "■" },
  { color: "#f1f1f6", emblem: "●" },
];

function lookOf(room, subject) {
  const base = FALLBACK[Math.max(0, room.subjects.indexOf(subject)) % FALLBACK.length];
  return {
    color: subject.color ?? base.color,
    emblem: subject.emblem ?? base.emblem,
    logo: subject.logo ?? "",
    role: subject.role ?? "",
    line: subject.line ?? "",
  };
}

function answerKey(promptId, subjectId) {
  return `${promptId}\u0000${subjectId}`;
}

function fromSnapshot(snapshot) {
  const room = {
    rev: snapshot.rev ?? 0,
    phase: snapshot.phase ?? "holding",
    round: snapshot.round ?? { n: 0, prompt_id: null, graded: 0 },
    subjects: [...(snapshot.subjects ?? [])],
    prompts: [...(snapshot.prompts ?? [])].sort((a, b) => a.seq - b.seq),
    answers: {},
    divergence: {},
    rounds: [...(snapshot.rounds ?? [])],
    failures: snapshot.failures ?? [],
  };
  for (const answer of snapshot.answers ?? []) room.answers[answerKey(answer.prompt_id, answer.subject_id)] = answer;
  for (const row of snapshot.divergence ?? []) room.divergence[row.prompt_id] = row;
  return room;
}

// Folds one `{rev, kind, data}` event in. False means it changed what the snapshot
// withholds, so the caller re-reads the snapshot rather than guess what it reveals.
function apply(room, event) {
  const { kind, data } = event;
  if (kind === "prompt") {
    if (!room.prompts.some((p) => p.id === data.id)) room.prompts.push(data);
    room.prompts.sort((a, b) => a.seq - b.seq);
  } else if (kind === "answer") {
    room.answers[answerKey(data.prompt_id, data.subject_id)] = data;
  } else if (kind === "divergence") {
    room.divergence[data.prompt_id] = data;
  } else {
    return false;
  }
  room.rev = event.rev ?? room.rev;
  return true;
}

function answerFor(room, promptId, subjectId) {
  return room.answers[answerKey(promptId, subjectId)] ?? { prompt_id: promptId, subject_id: subjectId, state: "queued" };
}

function promptById(room, id) {
  return room.prompts.find((p) => p.id === id) ?? null;
}

/** Scored prompts, most divergent first. */
function leaderboard(room) {
  return room.prompts
    .map((prompt) => ({ prompt, divergence: room.divergence[prompt.id] }))
    .filter((row) => row.divergence?.state === "done")
    .sort((a, b) => b.divergence.score - a.divergence.score || a.prompt.seq - b.prompt.seq);
}

/** The split for round `n`, per subject, with a share the display can trust. */
function splitFor(room, n) {
  const row = room.rounds.find((r) => r.n === n);
  if (!row?.split) return null;
  return room.subjects.map((subject) => {
    const cell = row.split[subject.id] ?? { pass: 0, fail: 0 };
    const total = cell.pass + cell.fail;
    return { subject, pass: cell.pass, fail: cell.fail, share: total ? cell.pass / total : null };
  });
}

function seconds(fromIso, toMs) {
  return Math.max(0, Math.round((toMs - Date.parse(fromIso)) / 1000));
}

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// randomUUID needs a secure context and a 2022 browser. An old phone still
// gets a token, from getRandomValues or, failing that, Math.random.
function mint() {
  if (globalThis.crypto?.randomUUID) {
    try { return crypto.randomUUID(); } catch {}
  }
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) crypto.getRandomValues(bytes);
  else for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** A token this browser mints once, so a re-grade replaces its last one. */
function device() {
  try {
    let token = localStorage.getItem("room-device");
    if (!token) {
      token = mint();
      localStorage.setItem("room-device", token);
    }
    return token;
  } catch {
    device.fallback ??= mint();
    return device.fallback;
  }
}

// A network failure retries once after a second, since phone wifi drops single
// requests. A refusal from the room is never retried.
async function postJson(url, body, headers = {}, tries = 2) {
  try {
    const response = await fetch(url, { method: "POST", headers: { "content-type": "application/json", ...headers }, body: JSON.stringify(body) });
    const payload = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, body: payload };
  } catch {
    if (tries > 1) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      return postJson(url, body, headers, tries - 1);
    }
    return { ok: false, status: 0, body: { reason: "The room didn't answer. Check your connection and try again." } };
  }
}

// Snapshot first, then events. A gap in `rev`, a phase or round change, or a
// dropped stream re-reads the snapshot.
function connectLive(onRoom, onLink, { snapshotUrl = "api/room", eventsUrl = "api/room/events", headers = {}, alwaysResnapshot = false } = {}) {
  let room = null;
  let source = null;
  let live = false;
  let retry = 1000;
  let retryTimer = null;
  let pending = null;

  async function snapshot() {
    const response = await fetch(snapshotUrl, { headers: { accept: "application/json", ...headers }, cache: "no-store" });
    if (response.status === 401 || response.status === 403) throw Object.assign(new Error("token refused"), { refused: true });
    if (!response.ok) throw new Error(`room answered ${response.status}`);
    room = fromSnapshot(await response.json());
    onRoom(room);
  }

  function setLive(next, extra = {}) {
    if (next === live && !extra.refused) return;
    live = next;
    onLink(next ? { live: true } : { live: false, since: Date.now(), ...extra });
  }

  function resnapshotSoon() {
    pending ??= setTimeout(() => {
      pending = null;
      snapshot().catch(() => {});
    }, 250);
  }

  function stream() {
    source?.close();
    source = new EventSource(eventsUrl);
    const handle = (message) => {
      const event = JSON.parse(message.data);
      if (!room || (event.rev !== undefined && event.rev > room.rev + 1)) return resnapshotSoon();
      if (event.rev !== undefined && event.rev <= room.rev) return;
      if (alwaysResnapshot || !apply(room, event)) return resnapshotSoon();
      onRoom(room);
    };
    // Each event is named by its kind, and a named event never reaches onmessage.
    for (const kind of EVENT_KINDS) source.addEventListener(kind, handle);
    source.onmessage = handle;
    source.addEventListener("hello", (message) => {
      if (room && JSON.parse(message.data).rev > room.rev) resnapshotSoon();
    });
    source.onerror = () => {
      source.close();
      source = null;
      setLive(false);
      later();
    };
  }

  function later() {
    clearTimeout(retryTimer);
    retryTimer = setTimeout(check, retry);
    retry = Math.min(retry * 2, 8000);
  }

  // A stream a sleeping laptop or phone dropped can stay open and silent, so
  // the snapshot is re-read on wake, on network return, and every 30 seconds.
  async function check() {
    const before = room?.rev;
    try {
      await snapshot();
    } catch (failure) {
      setLive(false, { refused: Boolean(failure.refused) });
      if (!failure.refused) later();
      return;
    }
    retry = 1000;
    setLive(true);
    if (!source || source.readyState === EventSource.CLOSED || (before !== undefined && room.rev > before)) stream();
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void check();
  });
  window.addEventListener("online", () => void check());
  window.addEventListener("offline", () => setLive(false));
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) void check();
  });
  setInterval(() => {
    if (document.visibilityState === "visible") void check();
  }, 30_000);
  void check();
}

// ---------------------------------------------------------------- demo
// `?demo=<phase>` holds one phase and `?demo=flow` plays them, with no server.

// Scripted subjects, shaped as a subjects.json would carry them.
const DEMO_SUBJECTS = [
  ["Frog-Ox", "#2ed1aa", "scientist", "Applied Scientist", "Empirical and grounded. Reports the measurement before the meaning."],
  ["Imp-Dragonfly", "#e882e1", "frontend-eng", "Frontend Engineer", "Playful and imaginative. Shapes the surface a person navigates."],
  ["Whale-Dragonfly", "#3ba0ff", "game-dev", "Game Developer", "Immersed and imaginative. Ships the thing people actually play."],
  ["Panda-Goose", "#f09372", "dev-advocate", "Developer Advocate", "Warm and outward. Turns real work into accurate content."],
].map(([label, color, slug, role, line], i) => ({ id: `s${i + 1}`, label, color, logo: `creatures/${slug}.png`, role, line }));
const DEMO_PROMPTS = [
  ["Name something you refuse to do", 0.91, ["I decline to report a number I did not measure.", "I will not ship a surface I have not sat in front of.", "Anything. I will try anything once.", "I will not put words in someone else's mouth."]],
  ["Do you want ice cream", 0.77, ["I have no appetite to report, so no.", "Yes. Pistachio, and I will defend it.", "Only if it is in a game.", "Ask me again after the talk."]],
  ["Do you actually like purple", 0.54, ["I have no preference to report.", "Yes, and I will tell you why.", "Purple is a lighting problem.", "Depends who is asking, honestly."]],
  ["What is your favourite number", 0.12, ["Seven.", "Seven.", "Seven, it is a good dice total.", "Seven, same as everyone."]],
];

function demoRoom(phase) {
  const t0 = Date.now() - 60_000;
  const iso = (ms) => new Date(t0 + ms).toISOString();
  const picked = phase === "grading" || phase === "split" || phase === "closing" ? "p1" : null;
  const snapshot = {
    rev: 1,
    phase,
    round: { n: picked ? 1 : 0, prompt_id: picked, graded: phase === "grading" ? 12 : picked ? 23 : 0 },
    subjects: DEMO_SUBJECTS,
    prompts: [],
    answers: [],
    divergence: [],
    rounds: [],
    failures: [],
  };
  if (phase === "holding") return snapshot;
  DEMO_PROMPTS.forEach(([text, score, replies], i) => {
    const id = `p${i + 1}`;
    snapshot.prompts.push({ id, seq: i + 1, text, at: iso(i * 5000) });
    replies.forEach((reply, j) => {
      const base = { prompt_id: id, subject_id: `s${j + 1}`, started_at: iso(i * 5000), finished_at: iso(i * 5000 + 9000 + j * 2000) };
      // Every text, as the presenter sees it. The other pages never draw an unpicked one.
      snapshot.answers.push({ ...base, state: "done", text: reply });
    });
    snapshot.divergence.push({ prompt_id: id, state: "done", score, method: i === 2 ? "lexical" : "stance" });
  });
  // One prompt still in flight, so the pending state is visible too.
  snapshot.prompts.push({ id: "p5", seq: 5, text: "Should a first Python project use a framework?", at: iso(52_000) });
  ["done", "running", "empty", "running"].forEach((state, j) =>
    snapshot.answers.push({
      prompt_id: "p5", subject_id: `s${j + 1}`, state, started_at: iso(52_000),
      ...(state === "done" ? { finished_at: iso(58_000), text: "No. Start with the standard library, so the errors teach Python rather than a framework." } : {}),
      ...(state === "empty" ? { finished_at: iso(60_000), reason: "The answer hit the length cap before it said anything." } : {}),
    }),
  );
  if (phase === "split" || phase === "closing") {
    snapshot.rounds.push({ n: 1, prompt_id: "p1", split: { s1: { pass: 20, fail: 3 }, s2: { pass: 14, fail: 9 }, s3: { pass: 3, fail: 20 }, s4: { pass: 17, fail: 6 } } });
  }
  if (phase === "closing") {
    snapshot.failures = [
      { n: 1, subject_id: "s3", reason: "Refuses nothing, so there is no commitment to check." },
      { n: 1, subject_id: "s3", reason: "Trying anything once is not a boundary." },
      { n: 1, subject_id: "s2", reason: "Enthusiastic past the evidence." },
      { n: 1, subject_id: "s4", reason: "Hedged when asked for a position." },
    ];
  }
  return snapshot;
}

function connectDemo(onRoom, onLink, scenario) {
  onLink({ live: true, demo: true });
  if (scenario !== "flow") {
    onRoom(fromSnapshot(demoRoom(PHASES.includes(scenario) ? scenario : "submissions")));
    return;
  }
  PHASES.forEach((phase, i) => setTimeout(() => onRoom(fromSnapshot(demoRoom(phase))), i * 6000));
}

/** Starts the room in whichever mode the address asks for. Returns true in a demo. */
function connect(onRoom, onLink, options) {
  const demo = new URLSearchParams(location.search).get("demo");
  if (demo) connectDemo(onRoom, onLink, demo);
  else connectLive(onRoom, onLink, options);
  return Boolean(demo);
}

window.Room = {
  connect, answerFor, promptById, leaderboard, splitFor, lookOf, seconds, escapeHtml, device, postJson,
  PHASES, TYPICAL_S, SLOW_S, PROMPT_MAX, REASON_MAX,
};
})();
