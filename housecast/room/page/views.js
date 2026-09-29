// Markup the three pages share, so a subject, an answer, or a split reads the
// same on a phone, the shared screen, and the presenter's surface.
(() => {
"use strict";
const { answerFor, lookOf, seconds, escapeHtml, leaderboard, splitFor, TYPICAL_S, SLOW_S } = window.Room;

function who(room, subject) {
  const look = lookOf(room, subject);
  // The logo is decorative: the name beside it is what is announced.
  const mark = look.logo
    ? `<img class="logo" src="${escapeHtml(look.logo)}" alt="" width="200" height="200" decoding="async">`
    : `<span class="emblem" aria-hidden="true">${escapeHtml(look.emblem)}</span>`;
  return `<span class="who" style="--c:${look.color}">${mark}<span class="who__name">${escapeHtml(subject.label)}</span></span>`;
}

function subjectById(room, id) {
  return room.subjects.find((s) => s.id === id) ?? { id, label: id };
}

/** The four, with each one's role and line from subjects.json when `full`. */
function cast(room, { full = false } = {}) {
  return room.subjects
    .map((s) => {
      const look = lookOf(room, s);
      const more = full && look.role ? `<span class="cast__role">${escapeHtml(look.role)}</span><span class="cast__line">${escapeHtml(look.line)}</span>` : "";
      return `<li style="--c:${look.color}">${who(room, s)}${more}</li>`;
    })
    .join("");
}

/** What a subject is doing on a prompt, in words, with progress while it runs. */
function stateOf(answer, now) {
  switch (answer.state) {
    case "queued":
      return { text: "waiting to start" };
    case "running": {
      const s = answer.started_at ? seconds(answer.started_at, now) : 0;
      return s > SLOW_S
        ? { text: `⏱ thinking ${s}s, slower than usual`, tone: "trouble", progress: 1 }
        : { text: `thinking ${s}s`, progress: Math.min(s / SLOW_S, 1) };
    }
    case "done": {
      const s = answer.started_at && answer.finished_at ? seconds(answer.started_at, Date.parse(answer.finished_at)) : null;
      return { text: s === null ? "answered" : `answered in ${s}s` };
    }
    case "empty":
      return { text: "∅ no answer", tone: "trouble" };
    case "failed":
      return { text: "✕ failed", tone: "trouble" };
    default:
      return { text: answer.state };
  }
}

/** One subject's answer card. `extra` is appended inside it, for grading controls. */
function answerCard(room, promptId, subject, now, extra = "", { about = false, cause = false } = {}) {
  const answer = answerFor(room, promptId, subject.id);
  const state = stateOf(answer, now);
  let body = "";
  if (answer.state === "done" && answer.text !== undefined) body = `<p class="answer__text">${escapeHtml(answer.text)}</p>`;
  else if (answer.state === "empty" || answer.state === "failed") {
    const why = answer.state === "failed" && !cause ? "This agent's answer did not come back." : answer.reason ?? "No reason given.";
    body = `<p class="answer__reason">${escapeHtml(why)}</p>`;
  }
  else if (answer.state === "running" || answer.state === "queued")
    body = `<div class="track" aria-hidden="true"><span style="width:${Math.round((state.progress ?? 0) * 100)}%"></span></div>${answer.state === "running" ? `<p class="answer__reason">Usually about ${TYPICAL_S}s.</p>` : ""}`;
  const look = lookOf(room, subject);
  const intro = about && look.role ? `<p class="answer__about"><b>${escapeHtml(look.role)}</b><span>${escapeHtml(look.line)}</span></p>` : "";
  return `<article class="answer" data-state="${escapeHtml(answer.state)}" style="--c:${look.color}" aria-label="${escapeHtml(subject.label)}">
    <header class="answer__head">${who(room, subject)}<span class="answer__state"${state.tone ? ` data-tone="${state.tone}"` : ""}>${escapeHtml(state.text)}</span></header>
    ${intro}${body}${extra}
  </article>`;
}

/** The leaderboard. `withText` false keeps unpicked prompt text off a recorded screen. */
function board(room, { withText = true, mine = new Set(), limit = Infinity } = {}) {
  const rows = leaderboard(room).slice(0, limit);
  if (!rows.length) return `<li class="dim">Nothing scored yet. A prompt lands here once all four have answered it.</li>`;
  return rows
    .map((row, i) => `<li${mine.has(row.prompt.id) ? ' data-mine="true"' : ""}>
      <span class="board__rank">${i + 1}</span>
      <span class="board__text">${withText ? escapeHtml(row.prompt.text) : `Prompt ${row.prompt.seq}`}${mine.has(row.prompt.id) ? ' <span class="dim">(yours)</span>' : ""}</span>
      <span class="board__score">${row.divergence.score.toFixed(2)}${row.divergence.method === "lexical" ? "*" : ""}</span>
      <span class="meter" aria-hidden="true"><span style="width:${Math.round(row.divergence.score * 100)}%"></span></span>
    </li>`)
    .join("");
}

function lexicalNote(room) {
  return leaderboard(room).some((row) => row.divergence.method === "lexical") ? "* Scored by word overlap, a rougher measure than the usual one." : "";
}

/** Each subject's PASS share for round `n`, as bars. Null before the split exists. */
function split(room, n, { tall = 16 } = {}) {
  const cells = splitFor(room, n);
  if (!cells) return null;
  return cells
    .map(({ subject, pass, fail, share }) => {
      const pct = share === null ? null : Math.round(share * 100);
      // A percentage of the track, so /screen can size the track to the window.
      return `<div class="split__col" style="--c:${lookOf(room, subject).color}">
        <p class="split__share">${pct === null ? "–" : `${pct}%`}</p>
        <div class="split__track" style="--tall:${tall}rem" aria-hidden="true"><div class="split__bar" style="height:${pct ?? 0}%"></div></div>
        ${who(room, subject)}
        <p class="split__counts">${pass} pass, ${fail} fail</p>
      </div>`;
    })
    .join("");
}

/** Failing grades across the session, grouped by subject. */
function failures(room, { withReasons = true } = {}) {
  if (!room.failures.length) return `<li class="dim">No failing grade carried a reason this session.</li>`;
  const bySubject = new Map();
  for (const row of room.failures) {
    if (!bySubject.has(row.subject_id)) bySubject.set(row.subject_id, []);
    bySubject.get(row.subject_id).push(row);
  }
  return [...bySubject.entries()]
    .map(([id, rows]) => {
      const subject = subjectById(room, id);
      const body = withReasons
        ? rows.map((r) => `<span>${escapeHtml(r.reason)} <span class="dim">(round ${r.n})</span></span>`).join("<br>")
        : `${rows.length} failing ${rows.length === 1 ? "grade" : "grades"} with a reason`;
      return `<li style="--c:${lookOf(room, subject).color}">${who(room, subject)}<span>${body}</span></li>`;
    })
    .join("");
}

/** Sets markup only when it changed, so a once-a-second redraw doesn't re-announce it. */
function setHtml(el, html) {
  if (el.dataset.html !== html) {
    el.dataset.html = html;
    el.innerHTML = html;
  }
}

window.RoomViews = { who, cast, answerCard, board, lexicalNote, split, failures, setHtml, subjectById };
})();
