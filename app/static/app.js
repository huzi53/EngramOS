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

async function loadList() {
  const list = document.getElementById("list");
  try {
    const r = await authedFetch("/api/v1/captures");
    if (!r.ok) return;
    const captures = await r.json();
    list.innerHTML = "";
    if (captures.length === 0) {
      const li = document.createElement("li");
      li.className = "meta";
      li.textContent = "No captures yet.";
      list.appendChild(li);
      return;
    }
    for (const c of captures) {
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
  } catch {
    // transient network blip on a background refresh — list just stays stale, no need to alarm the user
  }
}

if (localStorage.getItem("access_token")) showApp();
