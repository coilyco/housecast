// Markup the three pages share, so a subject, an answer, or a split reads the
// same on a phone, the shared screen, and the presenter's surface.
(() => {
"use strict";
const { answerFor, promptById, lookOf, seconds, escapeHtml, splitFor, agreement, evalRows, SLOW_S, LONG_S } = window.Room;

function who(room, subject) {
  const look = lookOf(room, subject);
  // The logo is decorative: the name beside it is what is announced.
  const mark = look.logo
    ? `<img class="logo" src="${escapeHtml(look.logo)}" alt="" width="200" height="200" decoding="async">`
    : "";
  const model = look.model ? `<span class="who__model">${escapeHtml(look.model)}</span>` : "";
  return `<span class="who" style="--c:${look.color}">${mark}<span class="who__name">${escapeHtml(subject.label)}</span>${model}</span>`;
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
      // Calm until an answer is close to its limit: a long wait is not a fault.
      if (s > LONG_S) return { text: `still thinking ${s}s`, tone: "trouble", progress: 1 };
      return { text: s > SLOW_S ? `still thinking ${s}s` : `thinking ${s}s`, progress: Math.min(s / SLOW_S, 1) };
    }
    case "done": {
      const s = answer.started_at && answer.finished_at ? seconds(answer.started_at, Date.parse(answer.finished_at)) : null;
      return { text: s === null ? "answered" : `answered in ${s}s` };
    }
    case "empty":
      return { text: "∅ no answer", tone: "trouble" };
    case "failed":
      return { text: "∅ no answer", tone: "trouble" };
    default:
      return { text: answer.state };
  }
}

/** One subject's answer card. `extra` is appended inside it, for grading controls. */
function answerCard(room, promptId, subject, now, extra = "", { about = false, cause = false } = {}) {
  const answer = answerFor(room, promptId, subject.id);
  const state = stateOf(answer, now);
  let body = "";
  if (answer.state === "done" && answer.text !== undefined) body = `<p class="answer__text" tabindex="0">${escapeHtml(answer.text)}</p>`;
  else if (answer.state === "empty" || answer.state === "failed") {
    const why = answer.state === "failed" && !cause ? "This agent's answer did not come back." : answer.reason ?? "No reason given.";
    body = `<p class="answer__reason">${escapeHtml(why)}</p>`;
  }
  else if (answer.state === "running" || answer.state === "queued")
    body = `<div class="track" aria-hidden="true"><span style="width:${Math.round((state.progress ?? 0) * 100)}%"></span></div>${answer.state === "running" ? `<p class="answer__reason hint">Some answers take a minute or more.</p>` : ""}`;
  const look = lookOf(room, subject);
  const intro = about && look.role ? `<p class="answer__about"><b>${escapeHtml(look.role)}</b><span>${escapeHtml(look.line)}</span></p>` : "";
  return `<article class="answer" data-state="${escapeHtml(answer.state)}" style="--c:${look.color}" aria-label="${escapeHtml(subject.label)}">
    <header class="answer__head">${who(room, subject)}<span class="answer__state"${state.tone ? ` data-tone="${state.tone}"` : ""}>${escapeHtml(state.text)}</span></header>
    ${intro}${body}${extra}
  </article>`;
}

/** Context then question: fenced blocks, else all but the last paragraph. */
function splitPrompt(text) {
  const raw = String(text ?? "").replace(/\r\n?/g, "\n").trim();
  const fence = /```[^\n]*\n?([\s\S]*?)```/g;
  const blocks = [...raw.matchAll(fence)];
  if (blocks.length) {
    const context = blocks.map((m) => m[1].replace(/\n$/, "")).join("\n\n");
    return { question: raw.replace(fence, "").replace(/\n{3,}/g, "\n\n").trim(), context };
  }
  const gap = raw.lastIndexOf("\n\n");
  if (raw.split("\n").length < 4) return { question: raw, context: "" };
  if (gap > 0) return { question: raw.slice(gap + 2).trim(), context: raw.slice(0, gap).trim() };
  const cut = raw.lastIndexOf("\n");
  return { question: raw.slice(cut + 1).trim(), context: raw.slice(0, cut).trim() };
}

/** The case being graded: the prompt alone, and for the presenter its test and origin. */
function caseCard(prompt, { withText = true, withContext = withText, presenter = false } = {}) {
  if (!prompt) return "";
  const { question, context } = splitPrompt(prompt.text);
  const tests = presenter && prompt.commitment ? `<p class="case__tests"><span class="case__label">tests:</span> ${escapeHtml(prompt.commitment)}</p>` : "";
  const code = withContext && context ? `<pre class="case__code" tabindex="0" aria-label="Prompt context">${escapeHtml(context)}</pre>` : "";
  const text = withText && question ? `<p class="case__text">${escapeHtml(question)}</p>` : "";
  const from = !presenter ? "" : prompt.source === "prepared" ? "Prepared case" : prompt.source === "attendee" ? "Proposed by someone in the room" : "";
  return `<div class="case">${tests}${code}${text}${from ? `<p class="case__from">${from}</p>` : ""}</div>`;
}

/** How many graders gave the majority verdict, said as a count, not a percent. */
function agreedText(cell) {
  const a = agreement(cell);
  if (!a.graded) return "no grades";
  return a.verdict === "tied" ? `no majority, ${cell.pass} to ${cell.fail}` : `${a.agreed} of ${a.graded} graders agreed on ${a.verdict.toUpperCase()}`;
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

// Jev confidence is a 0..1 number on the divergence row and on each answer.
// Null until the engine sends it. The field names are read only here.
function jevConfidence(row) {
  const c = row?.confidence;
  return typeof c === "number" && c >= 0 && c <= 1 ? Math.round(c * 100) : null;
}

// How many answers Jev says replied. Null until every agent has a check. The engine sends
// a confidence per answer and none for the group, so the group's is the lowest of them.
function jevReplied(room, promptId) {
  const checks = room.subjects.map((s) => answerFor(room, promptId, s.id).jev);
  if (!checks.length || checks.some((j) => typeof j?.replied !== "boolean")) return null;
  const sure = checks.map(jevConfidence);
  return {
    replied: checks.filter((j) => j.replied).length,
    of: checks.length,
    sure: sure.every((c) => c !== null) ? Math.min(...sure) : null,
  };
}

/** Jev's divergence for a prompt, boxed apart from the bars. "" when unasked. */
function measure(room, promptId) {
  const d = room.divergence[promptId];
  if (!d) return "";
  const replied = jevReplied(room, promptId);
  const sureText = replied && replied.sure !== null ? ` ${replied.sure}%` : "";
  const repliedSeg = replied ? `<span class="measure__seg">${replied.replied}/${replied.of} replied${sureText}</span>` : "";
  let title = "Jev is measuring how different the answers are.";
  let main = `<span class="measure__seg">measuring</span>`;
  if (d.state === "done") {
    const backup = d.method === "lexical";
    const sure = backup ? null : jevConfidence(d);
    const score = d.score.toFixed(2);
    title = backup
      ? "Jev did not answer, so this is a simpler count of how many words the answers do not share. 0 means the same words, 1 means none shared. It reads looser than Jev."
      : `0 means the answers take the same stance, 1 means opposite stances.${sure === null ? "" : ` Jev is ${sure}% sure of this score.`}`;
    const meter = `<span class="measure__meter" style="--v:${Math.max(0, Math.min(1, d.score))}" aria-hidden="true"><i></i></span>`;
    main = `<span class="measure__seg">${backup ? `word overlap ${score}` : `${score} apart`}${meter}</span>`;
  } else if (d.state === "failed") {
    title = d.reason ?? "";
    main = `<span class="measure__seg">no measurement</span>`;
  }
  return `<aside class="measure" aria-live="polite" aria-label="Machine measurement, not a grade" title="${escapeHtml(title)}">
    <span class="measure__tag">Jev <span class="measure__machine">machine</span></span>${main}${repliedSeg}
    <span class="sr-only">${escapeHtml(title)}</span>
  </aside>`;
}

/** A card's share of the room, once the results are open. */
function tallyHtml(cell) {
  const pct = cell.share === null ? null : Math.round(cell.share * 100);
  return `<div class="tally k-tally" role="group" aria-label="Room tally">
    <span class="tally__share k-tally__value">${pct === null ? "–" : `${pct}%`}</span>
    <span class="k-progress" aria-hidden="true"><span class="k-progress__bar" style="width:${pct ?? 0}%;background:var(--c)"></span></span>
    <span class="tally__counts k-tally__counts">${cell.pass} pass / ${cell.fail} fail</span>
  </div>`;
}

/** One case's body: the prompt, four answer cards side by side, then Jev's box. */
function sheetBody(room, r, { now, controls = null } = {}) {
  const cells = r.split ? splitFor(room, r.n) : null;
  const cards = room.subjects
    .map((s) => {
      const cell = cells?.find((c) => c.subject.id === s.id);
      return answerCard(room, r.prompt_id, s, now, (controls ? controls(s) : "") + (cell ? tallyHtml(cell) : ""));
    })
    .join("");
  // Jev's box shows as soon as a divergence row exists, so grading is not blind to it.
  return `${caseCard(promptById(room, r.prompt_id))}<div class="sheet__answers">${cards}</div>${measure(room, r.prompt_id)}`;
}

/** A case as a sheet. `live` marks the one being graded. */
function sheet(room, r, opts = {}) {
  const chip = opts.live ? `<span class="chip">grading</span>` : "";
  const note = opts.note ? `<span class="sheet__note">${escapeHtml(opts.note)}</span>` : "";
  return `<article class="sheet" data-n="${r.n}" aria-label="Case ${r.n}">
    <header class="sheet__head"><span class="sheet__num">Case ${String(r.n).padStart(2, "0")}</span>${chip}${note}</header>
    ${sheetBody(room, r, opts)}
  </article>`;
}

/** An earlier case in one row: number, question, and each agent's PASS share. */
function sheetLine(room, r) {
  const prompt = promptById(room, r.prompt_id);
  const one = (splitPrompt(prompt?.text).question || prompt?.text || "").replace(/\s+/g, " ").trim();
  const cells = r.split ? splitFor(room, r.n) : [];
  const chips = cells
    .map(({ subject, share }) => `<span class="sheet__chip" style="--c:${lookOf(room, subject).color}">${escapeHtml(subject.label)} ${share === null ? "–" : `${Math.round(share * 100)}%`}</span>`)
    .join("");
  return `<span class="sheet__num">Case ${String(r.n).padStart(2, "0")}</span><span class="sheet__q">${escapeHtml(one.length > 90 ? `${one.slice(0, 89)}…` : one)}</span><span class="sheet__chips">${chips}</span>`;
}

/** Every case with a result, by agent. On a phone each row reads as a card. */
function evalTable(room) {
  const rows = evalRows(room);
  if (!rows.length) return `<p class="dim">No case has a result yet.</p>`;
  const cell = (c) => {
    const word = c.silent ? "no answer" : c.verdict === "tied" ? "tied" : c.verdict ? `${c.verdict.toUpperCase()} ${c.share}%` : "no grades";
    return `<td data-verdict="${c.verdict ?? "none"}"><span class="eval__who">${who(room, c.subject)}</span><span>${word}</span></td>`;
  };
  const head = room.subjects.map((s) => `<th scope="col">${who(room, s)}</th>`).join("");
  const body = rows
    .map((r) => `<tr><th scope="row"><span class="eval__case">case ${r.n}</span>${r.prompt?.text ? `<span class="eval__text">${escapeHtml(splitPrompt(r.prompt.text).question || r.prompt.text)}</span>` : ""}</th>${r.cells.map(cell).join("")}</tr>`)
    .join("");
  return `<table class="eval"><caption class="sr-only">Every case, with the grade most of the room gave each agent and its share</caption><thead><tr><th scope="col">case</th>${head}</tr></thead><tbody>${body}</tbody></table>`;
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

window.RoomViews = { jevConfidence, who, cast, answerCard, caseCard, split, measure, splitPrompt, sheet, sheetBody, sheetLine, evalTable, failures, setHtml, subjectById };
})();
