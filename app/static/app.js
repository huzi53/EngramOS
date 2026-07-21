// Minimal quick-note + captures list. No framework, no build — this is the private
// text-only path (media goes via Telegram, see plans/004 Cut).

function showApp() {
  document.getElementById("login").style.display = "none";
  document.getElementById("app").style.display = "block";
  loadList();
}

async function login() {
  const username = document.getElementById("username").value;
  const password = document.getElementById("password").value;
  const btn = document.getElementById("loginBtn");
  const error = document.getElementById("error");
  error.textContent = "";
  btn.disabled = true;
  btn.textContent = "Logging in...";
  try {
    const r = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!r.ok) {
      error.textContent = "Login failed";
      return;
    }
    const body = await r.json();
    localStorage.setItem("access_token", body.access_token);
    localStorage.setItem("refresh_token", body.refresh_token);
    showApp();
  } catch {
    error.textContent = "Network error, try again";
  } finally {
    btn.disabled = false;
    btn.textContent = "Log in";
  }
}

async function authedFetch(url, options = {}) {
  options.headers = { ...options.headers, Authorization: `Bearer ${localStorage.getItem("access_token")}` };
  let r = await fetch(url, options);
  if (r.status === 401) {
    const rr = await fetch("/api/v1/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: localStorage.getItem("refresh_token") }),
    });
    if (!rr.ok) return r;
    const body = await rr.json();
    localStorage.setItem("access_token", body.access_token);
    options.headers.Authorization = `Bearer ${body.access_token}`;
    r = await fetch(url, options);
  }
  return r;
}

async function save() {
  const note = document.getElementById("note");
  const text = note.value.trim();
  if (!text) return;
  const btn = document.getElementById("saveBtn");
  const status = document.getElementById("noteStatus");
  status.textContent = "";
  status.className = "status";
  btn.disabled = true;
  btn.textContent = "Saving...";
  try {
    const form = new FormData();
    form.append("text", text);
    form.append("source", "quicknote");
    const r = await authedFetch("/api/v1/capture", { method: "POST", body: form });
    if (r.ok) {
      note.value = "";
      status.textContent = "Saved";
      status.className = "status ok";
      loadList();
    } else {
      status.textContent = "Save failed, try again";
      status.className = "status error";
    }
  } catch {
    status.textContent = "Network error, try again";
    status.className = "status error";
  } finally {
    btn.disabled = false;
    btn.textContent = "Save note";
  }
}

// Shared render for both the recent-captures list and search results — textContent only,
// never innerHTML on capture content (M1's stored-XSS fix).
function renderList(items, emptyText) {
  const list = document.getElementById("list");
  list.innerHTML = "";
  if (items.length === 0) {
    const li = document.createElement("li");
    li.className = "meta";
    li.textContent = emptyText;
    list.appendChild(li);
    return;
  }
  for (const c of items) {
    const li = document.createElement("li");
    const when = new Date(c.created_at).toLocaleString();
    const kind = document.createElement("span");
    kind.className = "kind";
    kind.textContent = c.kind;
    li.appendChild(kind);
    li.appendChild(document.createTextNode(c.content || c.file_name || ""));
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = when;
    li.appendChild(meta);
    list.appendChild(li);
  }
}

async function loadList() {
  try {
    const r = await authedFetch("/api/v1/captures");
    if (!r.ok) return;
    renderList(await r.json(), "No captures yet.");
  } catch {
    // transient network blip on a background refresh — list just stays stale, no need to alarm the user
  }
}

// Bumped on every search/clear so a slow, superseded request can't clobber a
// newer one's view (e.g. user hits Clear, or fires a second search, while the
// first request is still in flight).
let searchSeq = 0;

async function search() {
  const q = document.getElementById("q").value.trim();
  if (!q) { loadList(); return; }
  const btn = document.getElementById("searchBtn");
  if (btn.disabled) return; // already searching — ignore rapid Enter/click mashing
  const seq = ++searchSeq;
  const status = document.getElementById("searchStatus");
  status.textContent = "";
  status.className = "status";
  btn.disabled = true;
  btn.textContent = "Searching...";
  try {
    const r = await authedFetch("/api/v1/search?q=" + encodeURIComponent(q));
    if (seq !== searchSeq) return; // superseded — a clear or newer search already updated the view
    if (!r.ok) {
      status.textContent = "Search failed, try again";
      status.className = "status error";
      return;
    }
    renderList(await r.json(), `No results for "${q}".`);
  } catch {
    if (seq !== searchSeq) return;
    status.textContent = "Network error, try again";
    status.className = "status error";
  } finally {
    if (seq === searchSeq) {
      btn.disabled = false;
      btn.textContent = "Search";
    }
  }
}

function clearSearch() {
  searchSeq++; // invalidate any in-flight search response
  document.getElementById("q").value = "";
  document.getElementById("searchStatus").textContent = "";
  document.getElementById("searchBtn").disabled = false;
  document.getElementById("searchBtn").textContent = "Search";
  loadList();
}

if (localStorage.getItem("access_token")) showApp();
