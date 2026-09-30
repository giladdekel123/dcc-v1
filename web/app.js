"use strict";

// Readable names for evidence fields returned by /api/search.
const FIELD_LABELS = {
  title: "Title", doc_code: "Document code", filename: "Filename", doc_type: "Document type",
  discipline: "Discipline", wbs: "WBS", originator: "Originator", sender: "Sender", stage: "Stage",
  status: "Current status", owner: "Owner", org: "Organisation", date_from: "Date", date_to: "Date",
};
// Where each kind of evidence comes from, as shown to the user.
const EVIDENCE_GROUPS = {
  metadata_match: "Register", content_snippet: "File", revision_note: "Revision", status_note: "Status",
  discrepancy: "Check", related_document: "Related",
};

const form = document.getElementById("search-form");
const input = document.getElementById("q");
const summary = document.getElementById("summary");
const list = document.getElementById("results");
let latestRequest = 0;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

// Text with <mark> around the API's [start, end) character spans. Never uses innerHTML.
function highlighted(text, spans) {
  const fragment = document.createDocumentFragment();
  let pos = 0;
  for (const [start, end] of [...spans].sort((a, b) => a[0] - b[0])) {
    if (start < pos) continue;
    fragment.append(text.slice(pos, start), el("mark", null, text.slice(start, end)));
    pos = end;
  }
  fragment.append(text.slice(pos));
  return fragment;
}

function formatDate(iso) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function badge(text, tone) {
  return el("span", `badge badge-${tone}`, text);
}

function renderRevision(revision) {
  const parts = [`Rev ${revision.rev_code}`, formatDate(revision.revision_date), revision.stage.label];
  if (revision.current_status) parts.push(`${revision.current_status.code} ${revision.current_status.label}`);
  const line = el("p", "rev", parts.join(" · "));

  const badges = el("p", "badges");
  badges.append(revision.is_latest
    ? badge("Latest revision", "ok")
    : badge(`Not the latest: ${revision.latest_rev_code} is newer`, "warn"));
  const construction = revision.latest_by_use.construction;
  if (construction) {
    badges.append(construction === revision.rev_code
      ? badge("Latest for construction", "ok")
      : badge(`For construction: ${construction}`, "info"));
  }
  return [line, badges];
}

function renderEvidence(evidence) {
  const section = el("section", "evidence");
  section.append(el("h4", null, "Why it was found"));
  const items = el("dl");
  for (const item of evidence) {
    const group = EVIDENCE_GROUPS[item.kind] ?? item.kind;
    const detail = el("dd");
    const label = item.kind === "metadata_match" ? FIELD_LABELS[item.field] ?? item.field
      : item.kind === "content_snippet" ? item.locator : null;
    if (label) detail.append(el("span", "label", `${label}: `));
    detail.append(highlighted(item.text, item.highlights));
    items.append(el("dt", `source source-${item.kind}`, group), detail);
  }
  section.append(items);
  return section;
}

function renderLocation(result) {
  const { location: place, document: doc, revision } = result;
  const section = el("section", "location");
  section.append(el("h4", null, "Filed at"));
  const path = `${place.original_location}\\${place.filename}`;
  section.append(el("code", "path", path));

  if (place.other_locations.length) {
    section.append(el("h4", null, "Also filed at"));
    for (const other of place.other_locations) section.append(el("code", "path", other));
  }

  const actions = el("p", "actions");
  const open = el("a", "button", "Open file");
  open.href = place.open_url;
  open.target = "_blank";
  open.rel = "noopener";
  open.setAttribute("aria-label", `Open ${doc.doc_code} revision ${revision.rev_code}`);

  const copy = el("button", "secondary", "Copy path");
  copy.type = "button";
  copy.setAttribute("aria-label", `Copy the file path of ${doc.doc_code} revision ${revision.rev_code}`);
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(path);
      copy.textContent = "Copied";
    } catch {
      copy.textContent = "Copy failed";
    }
    setTimeout(() => { copy.textContent = "Copy path"; }, 1500);
  });
  actions.append(open, copy);
  section.append(actions);
  return section;
}

function renderResult(result) {
  const { document: doc, revision } = result;
  const card = el("li", "card");
  const head = el("div", "card-head");
  head.append(el("span", "rank", String(result.rank)), el("h3", null, doc.title));
  card.append(head);
  card.append(el("p", "meta", [doc.doc_code, doc.doc_type.label, doc.discipline.label,
    doc.wbs.label, doc.originator.label].join(" · ")));
  card.append(...renderRevision(revision), renderEvidence(result.evidence), renderLocation(result));
  return card;
}

async function runSearch(query, { updateHistory = true } = {}) {
  query = query.trim();
  input.value = query;
  list.replaceChildren();
  const request = ++latestRequest;  // also invalidates any search still in flight
  if (!query) {
    summary.textContent = "Type something you remember about the document.";
    return;
  }
  const params = new URLSearchParams({ q: query });
  if (updateHistory && new URLSearchParams(location.search).get("q") !== query) {
    history.pushState({ q: query }, "", `?${params}`);
  }
  summary.textContent = "Searching…";
  try {
    const response = await fetch(`/api/search?${params}`);
    if (response.status === 503) throw new Error("The document database is not available right now.");
    if (!response.ok) throw new Error(`The search failed (error ${response.status}).`);
    const data = await response.json();
    if (request !== latestRequest) return;  // a newer search has started
    const count = data.results.length;
    summary.textContent = count
      ? `${count} candidate${count === 1 ? "" : "s"} for “${query}”`
      : `No documents matched “${query}”. Try fewer or different words.`;
    list.replaceChildren(...data.results.map(renderResult));
  } catch (error) {
    if (request !== latestRequest) return;
    summary.textContent = error instanceof TypeError ? "Could not reach the DCC server." : error.message;
  }
  summary.focus();
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  runSearch(input.value);
});

window.addEventListener("popstate", () => {
  runSearch(new URLSearchParams(location.search).get("q") ?? "", { updateHistory: false });
});

fetch("/api/health")
  .then((response) => response.json())
  .then((health) => {
    document.getElementById("health").textContent =
      `Backend ${health.status} · database ${health.database.replace("_", " ")}`;
  })
  .catch(() => { document.getElementById("health").textContent = "Backend unreachable"; });

const initialQuery = new URLSearchParams(location.search).get("q");
if (initialQuery) runSearch(initialQuery, { updateHistory: false });
else input.focus();
