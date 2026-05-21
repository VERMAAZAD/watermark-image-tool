fetch("/api/app-size")
  .then(r => r.json())
  .then(d => { document.getElementById("appSize").textContent = d.size + " used"; })
  .catch(() => { document.getElementById("appSize").textContent = "—"; });

const foldersInput = document.getElementById("folders");
foldersInput.addEventListener("change", () => {
  const max = parseInt(foldersInput.max, 10);
  const val = parseInt(foldersInput.value, 10);
  if (val > max) { alert(`Maximum allowed is ${max}.`); foldersInput.value = max; }
  else if (val < 1) foldersInput.value = 1;
});

function setStatus(msg, type = "") {
  const el = document.getElementById("status");
  el.textContent = msg;
  el.className = "status-bar " + type;
}

async function generateImages() {
  const baseFiles = document.getElementById("baseImages").files;
  const logoFile  = document.getElementById("logoImage").files[0];

  if (!baseFiles.length || !logoFile) {
    setStatus("Please select base images and a logo.", "error"); return;
  }
  if (!document.getElementById("folderName").value.trim()) {
    setStatus("Please enter an output name.", "error"); return;
  }

  const formData = new FormData();
  for (let f of baseFiles) formData.append("baseImages", f);
  formData.append("logoImage", logoFile);
  formData.append("folders",    document.getElementById("folders").value);
  formData.append("posX",       document.getElementById("posX").value);
  formData.append("posY",       document.getElementById("posY").value);
  formData.append("folderName", document.getElementById("folderName").value.trim());

  document.getElementById("genBtn").disabled = true;
  setStatus("⏳ Uploading…", "processing");

  try {
    const res  = await fetch("/generate", { method: "POST", body: formData });
    const data = await res.json();

    if (!data.success) { setStatus("Server error. Please try again.", "error"); document.getElementById("genBtn").disabled = false; return; }

    const jobId = data.job_id;
    setStatus("⏳ Processing images… please wait.", "processing");

    const poll = setInterval(async () => {
      try {
        const s = await (await fetch(`/api/job-status/${jobId}`)).json();
        if (s.status === "done") {
          clearInterval(poll);
          setStatus("✓ Images generated successfully!", "success");
          document.getElementById("genBtn").disabled = false;
          setTimeout(() => window.location.href = "/results", 800);
        } else if (s.status === "error") {
          clearInterval(poll);
          setStatus("Error: " + (s.error || "Unknown error"), "error");
          document.getElementById("genBtn").disabled = false;
        }
      } catch {
        clearInterval(poll);
        setStatus("Server not reachable.", "error");
        document.getElementById("genBtn").disabled = false;
      }
    }, 2000);

  } catch {
    setStatus("Server not reachable.", "error");
    document.getElementById("genBtn").disabled = false;
  }
}