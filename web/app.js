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

// ---------------------------------------------------------------------------
// Filters: the controls in the Refine panel are the single source of truth.
// ---------------------------------------------------------------------------

const FILTER_NAMES = {
  doc_type: "Document type", discipline: "Discipline", stage: "Stage", org: "Organisation",
  wbs: "WBS", date_from: "Issued from", date_to: "Issued to",
};
const refine = document.getElementById("refine");
const refineCount = document.getElementById("refine-count");
const chips = document.getElementById("chips");
const notice = document.getElementById("notice");
const controls = Object.fromEntries(
  [...document.querySelectorAll("[data-filter]")].map((control) => [control.dataset.filter, control]));
const facetLabels = {};  // filter key -> { code: label }
let facetsLoaded = false;

function populate(key, values, withCode = false) {
  const select = controls[key];
  select.replaceChildren(new Option("Any", ""));
  facetLabels[key] = {};
  const add = (value, depth) => {
    const label = withCode ? `${value.code} ${value.label}` : value.label;
    select.append(new Option(`${" ".repeat(depth)}${label} (${value.count})`, value.code));
    facetLabels[key][value.code] = label;
    (value.children ?? []).forEach((child) => add(child, depth + 1));
  };
  values.forEach((value) => add(value, 0));
}

async function loadFacets() {
  try {
    const response = await fetch("/api/facets");
    if (!response.ok) throw new Error(`facets ${response.status}`);
    const facets = await response.json();
    populate("doc_type", facets.doc_types);
    populate("discipline", facets.disciplines);
    populate("stage", facets.stages);
    populate("org", facets.organisations);
    populate("wbs", facets.wbs, true);
    for (const key of ["date_from", "date_to"]) {
      controls[key].min = facets.date_range.min ?? "";
      controls[key].max = facets.date_range.max ?? "";
    }
    facetsLoaded = true;
  } catch {
    refine.hidden = true;  // searching without filters still works
  }
}

function currentFilters() {
  return Object.fromEntries(
    Object.entries(controls).map(([key, control]) => [key, control.value]).filter(([, value]) => value));
}

// Set the controls from a filters object; returns descriptions of values that aren't valid choices.
function setFilters(filters) {
  const rejected = [];
  for (const [key, control] of Object.entries(controls)) {
    const value = filters[key] ?? "";
    const valid = !value || (control.tagName === "SELECT"
      ? [...control.options].some((option) => option.value === value)
      : /^\d{4}-\d{2}-\d{2}$/.test(value));
    control.value = valid ? value : "";
    if (!valid) rejected.push(`${FILTER_NAMES[key]} “${value}”`);
  }
  return rejected;
}

function filterText(key, value) {
  return `${FILTER_NAMES[key]}: ${facetLabels[key]?.[value] ?? formatDate(value)}`;
}

function renderChips(filters) {
  const entries = Object.entries(filters);
  refineCount.textContent = entries.length ? `(${entries.length} active)` : "";
  chips.replaceChildren(...entries.map(([key, value]) => {
    const chip = el("span", "chip", filterText(key, value));
    const remove = el("button", "chip-remove", "✕");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove filter ${filterText(key, value)}`);
    remove.addEventListener("click", () => {
      controls[key].value = "";
      runSearch(input.value, currentFilters());
    });
    chip.append(remove);
    return chip;
  }));
}

function readUrl() {
  const params = new URLSearchParams(location.search);
  const filters = {};
  for (const key of Object.keys(FILTER_NAMES)) {
    if (params.get(key)) filters[key] = params.get(key);
  }
  return { query: params.get("q") ?? "", filters };
}

function urlFor(query, filters) {
  const params = new URLSearchParams();
  if (query) params.set("q", query);
  for (const [key, value] of Object.entries(filters)) params.set(key, value);
  return params.size ? `${location.pathname}?${params}` : location.pathname;
}

function showNotice(text) {
  notice.textContent = text;
  notice.hidden = !text;
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

async function runSearch(query, filters = {}, { updateHistory = true } = {}) {
  query = query.trim();
  input.value = query;
  renderChips(filters);
  list.replaceChildren();
  const request = ++latestRequest;  // also invalidates any search still in flight
  const active = Object.keys(filters).length;

  const url = urlFor(query, filters);
  if (updateHistory) {
    showNotice("");  // a notice about the loaded URL no longer applies after the user acts
    if (url !== `${location.pathname}${location.search}`) history.pushState(null, "", url);
  }

  if (!query && !active) {
    summary.textContent = "Type something you remember about the document, or choose filters under Refine.";
    return;
  }
  if (filters.date_from && filters.date_to && filters.date_from > filters.date_to) {
    summary.textContent = "The “Issued from” date is later than the “to” date.";
    return;
  }

  summary.textContent = "Searching…";
  try {
    const params = new URLSearchParams({ ...(query ? { q: query } : {}), ...filters });
    const response = await fetch(`/api/search?${params}`);
    if (response.status === 503) throw new Error("The document database is not available right now.");
    if (!response.ok) throw new Error(`The search failed (error ${response.status}).`);
    const data = await response.json();
    if (request !== latestRequest) return;  // a newer search has started
    const count = data.results.length;
    const plural = count === 1 ? "" : "s";
    if (query) {
      const withFilters = active ? ` with ${active} filter${active === 1 ? "" : "s"}` : "";
      summary.textContent = count
        ? `${count} candidate${plural} for “${query}”${withFilters}`
        : `No documents matched “${query}”${withFilters}. Try fewer or different words${active ? ", or remove a filter" : ""}.`;
    } else {
      summary.textContent = count
        ? `${count} document${plural} matching the filters, newest first${count === 10 ? " (showing the 10 newest)" : ""}`
        : "No documents match these filters.";
    }
    list.replaceChildren(...data.results.map(renderResult));
  } catch (error) {
    if (request !== latestRequest) return;
    summary.textContent = error instanceof TypeError ? "Could not reach the DCC server." : error.message;
  }
  summary.focus();
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  runSearch(input.value, currentFilters());
});

for (const control of Object.values(controls)) {
  control.addEventListener("change", () => runSearch(input.value, currentFilters()));
}

document.getElementById("clear-filters").addEventListener("click", () => {
  setFilters({});
  runSearch(input.value, {});
});

window.addEventListener("popstate", () => {
  const { query, filters } = readUrl();
  if (facetsLoaded) setFilters(filters);
  runSearch(query, facetsLoaded ? currentFilters() : filters, { updateHistory: false });
});

fetch("/api/health")
  .then((response) => response.json())
  .then((health) => {
    document.getElementById("health").textContent =
      `Backend ${health.status} · database ${health.database.replace("_", " ")}`;
  })
  .catch(() => { document.getElementById("health").textContent = "Backend unreachable"; });

loadFacets().then(() => {
  const { query, filters } = readUrl();
  let active = filters;
  if (facetsLoaded) {
    const rejected = setFilters(filters);
    if (rejected.length) showNotice(`Ignored unknown filter values: ${rejected.join(", ")}.`);
    active = currentFilters();
  }
  if (Object.keys(active).length) refine.open = true;
  if (query || Object.keys(active).length) {
    history.replaceState(null, "", urlFor(query, active));  // drop any rejected values from the URL
    runSearch(query, active, { updateHistory: false });
  } else {
    input.focus();
  }
});
