
async function loadAllTables() {
    try {
  const res = await fetch("/api/all-results");
  const data = await res.json();
  const container = document.getElementById("content");
  container.innerHTML = "";

   if (data.length === 0) {
    container.innerHTML = `
      <div class="empty">
        <div class="empty-icon">📭</div>
        <p>No results found</p>
        <small>Generated batches will appear here</small>
      </div>`;
    return;
  }

   document.getElementById("tableCount").textContent = `${data.length} batch${data.length > 1 ? 'es' : ''}`;
    container.appendChild(createTableBox(data[0].name, data[0].rows));

    if (data.length > 1) {
      const wrap = document.createElement("div");
      wrap.className = "show-old-wrap";
      const btn = document.createElement("button");
      btn.className = "show-old-btn";
      btn.innerHTML = `&#8635; Show older batches (${data.length - 1})`;
      btn.onclick = () => {
        wrap.remove();
        for (let i = 1; i < data.length; i++) {
          container.appendChild(createTableBox(data[i].name, data[i].rows));
        }
      };
      wrap.appendChild(btn);
      container.appendChild(wrap);
    }

  } catch (err) {
    document.getElementById("content").innerHTML = `
      <div class="empty">
        <div class="empty-icon">⚠️</div>
        <p>Failed to load results</p>
        <small>Check your connection and try refreshing</small>
      </div>`;
  }
}

function createTableBox(tableName, rows) {
  const PAGE = 50;
  let page = 0;

  const box = document.createElement("div");
  box.className = "box";

  // Header
  const header = document.createElement("div");
  header.className = "box-header";

  const titleDiv = document.createElement("div");
  titleDiv.className = "box-title";
  titleDiv.innerHTML = `
    <div class="folder-icon">📁</div>
    <h2>${tableName}</h2>
    <span class="count-badge">${rows.length} images</span>
  `;

  const actions = document.createElement("div");
  actions.className = "box-actions";

  const copyBtn = document.createElement("button");
  copyBtn.className = "btn btn-primary";
  copyBtn.innerHTML = "&#128203; Copy URLs";
  copyBtn.onclick = async () => {
    try {
      await navigator.clipboard.writeText(rows.map(r => r[1]).join("\n"));
      copyBtn.innerHTML = "&#10003; Copied!";
      copyBtn.disabled = true;
      setTimeout(() => { copyBtn.innerHTML = "&#128203; Copy URLs"; copyBtn.disabled = false; }, 1500);
    } catch {
      copyBtn.innerHTML = "&#10007; Error";
      setTimeout(() => { copyBtn.innerHTML = "&#128203; Copy URLs"; }, 1500);
    }
  };

  const deleteBtn = document.createElement("button");
  deleteBtn.className = "btn btn-danger";
  deleteBtn.innerHTML = "&#128465; Delete";
  deleteBtn.onclick = () => {
    if (!confirm(`Delete "${tableName}"?\nAll images and CSV will be removed.`)) return;
    fetch("/api/delete-table", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ table: tableName })
    }).then(r => r.json()).then(d => {
      if (!d.success) { alert(d.error); return; }
      box.remove();
    });
  };

  actions.appendChild(copyBtn);
  actions.appendChild(deleteBtn);
  header.appendChild(titleDiv);
  header.appendChild(actions);
  box.appendChild(header);

  // Table
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";

  const table = document.createElement("table");
  table.innerHTML = `<thead><tr><th>#</th><th>Filename</th><th>URL</th><th>Preview</th></tr></thead>`;
  const tbody = document.createElement("tbody");
  table.appendChild(tbody);
  wrap.appendChild(table);
  box.appendChild(wrap);

  // Load more footer
  const footer = document.createElement("div");
  footer.className = "load-more-wrap";
  footer.style.display = "none";

  const loadMoreBtn = document.createElement("button");
  loadMoreBtn.className = "btn btn-outline";
  loadMoreBtn.onclick = () => renderPage();
  footer.appendChild(loadMoreBtn);
  box.appendChild(footer);

  function renderPage() {
    const slice = rows.slice(page * PAGE, (page + 1) * PAGE);
    slice.forEach(([name, url], i) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="color:var(--text-3);font-size:11px;font-family:var(--mono)">${page * PAGE + i + 1}</td>
        <td class="td-name">${name}</td>
        <td class="td-url"><a href="${url}" target="_blank">${url}</a></td>
        <td class="td-preview"><img src="${url}" loading="lazy"></td>
      `;
      tbody.appendChild(tr);
    });
    page++;

    const remaining = rows.length - page * PAGE;
    if (remaining > 0) {
      loadMoreBtn.textContent = `Load more — ${remaining} remaining`;
      footer.style.display = "block";
    } else {
      footer.style.display = "none";
    }
  }

  renderPage();
  return box;
}

loadAllTables();
