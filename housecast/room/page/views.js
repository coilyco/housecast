// Markup the three pages share, so a subject, an answer, or a split reads the
// same on a phone, the shared screen, and the presenter's surface.
(() => {
"use strict";
const { answerFor, lookOf, seconds, escapeHtml, splitFor, agreement, evalRows, talkFor, TYPICAL_S, SLOW_S } = window.Room;

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

/** The case being graded: the commitment it tests, then the prompt. */
function caseCard(prompt, { withText = true } = {}) {
  if (!prompt) return "";
  const tests = prompt.commitment ? `<p class="case__tests"><span class="case__label">tests:</span> ${escapeHtml(prompt.commitment)}</p>` : "";
  const text = withText && prompt.text ? `<p class="case__text">${escapeHtml(prompt.text)}</p>` : "";
  const from = prompt.source === "prepared" ? "Prepared case" : prompt.source === "attendee" ? "Proposed by someone in the room" : "";
  return `<div class="case">${tests}${text}${from ? `<p class="case__from">${from}</p>` : ""}</div>`;
}

/** How many graders gave the majority verdict, said as a count, not a percent. */
function agreedText(cell) {
  const a = agreement(cell);
  return a.graded ? `${a.agreed} of ${a.graded} graders agreed` : "no grades";
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
        <p class="split__agree">${agreedText({ pass, fail })}</p>
      </div>`;
    })
    .join("");
}

/** Every case with a result, by agent. On a phone each row reads as a card. */
function evalTable(room) {
  const rows = evalRows(room);
  if (!rows.length) return `<p class="dim">No case has a result yet.</p>`;
  const cell = (c) => {
    const word = c.verdict === "tied" ? "tied" : c.verdict ? `${c.verdict.toUpperCase()} ${c.share}%` : "no grades";
    return `<td data-agent="${escapeHtml(c.subject.label)}" data-verdict="${c.verdict ?? "none"}">${word}</td>`;
  };
  const head = room.subjects.map((s) => `<th scope="col">${who(room, s)}</th>`).join("");
  const body = rows
    .map((r) => `<tr><th scope="row"><span class="eval__case">case ${r.n}${r.prompt?.commitment ? `: ${escapeHtml(r.prompt.commitment)}` : ""}</span>${r.prompt?.text ? `<span class="eval__text">${escapeHtml(r.prompt.text)}</span>` : ""}</th>${r.cells.map(cell).join("")}</tr>`)
    .join("");
  return `<table class="eval"><caption class="sr-only">Every case, with each agent's majority verdict and its share</caption><thead><tr><th scope="col">case</th>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

/** Questions for the room after the latest result. */
function talkCard(room) {
  const rows = evalRows(room);
  const last = rows[rows.length - 1];
  if (!last) return "";
  const { questions } = talkFor(room, last);
  return `<section class="talk" aria-labelledby="talk-title"><h2 id="talk-title">Talk it through</h2><ul>${questions.map((q) => `<li>${escapeHtml(q)}</li>`).join("")}</ul></section>`;
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

window.RoomViews = { who, cast, answerCard, caseCard, split, evalTable, talkCard, failures, setHtml, subjectById };
})();
