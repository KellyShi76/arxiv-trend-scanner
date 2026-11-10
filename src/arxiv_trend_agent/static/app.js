const form = document.querySelector("#runForm");
const startButton = document.querySelector("#startButton");
const statusPanel = document.querySelector("#statusPanel");
const statusTitle = document.querySelector("#statusTitle");
const statusPercent = document.querySelector("#statusPercent");
const statusMessage = document.querySelector("#statusMessage");
const statusError = document.querySelector("#statusError");
const progressBar = document.querySelector("#progressBar");
const results = document.querySelector("#results");
const reportText = document.querySelector("#reportText");
const metricCards = document.querySelector("#metricCards");
const downloadLinks = document.querySelector("#downloadLinks");
const parsePdfs = document.querySelector("#parsePdfs");
const pdfLimitRow = document.querySelector("#pdfLimitRow");
const backend = document.querySelector("#backend");
const backendHint = document.querySelector("#backendHint");

document.querySelector("#asOf").value = new Date().toISOString().slice(0, 10);

const presets = {
  causal: {
    topic: "causal inference for longitudinal data and personalized treatment effects",
    themes: `Personalization=personalized,personalization,heterogeneous,individualized
Longitudinal modeling=longitudinal,sequential,recurrent,rnn,transformer
Doubly robust estimation=doubly robust,orthogonal,propensity
Continuous treatment=continuous treatment,dose-response,dosage`,
  },
  irl: {
    topic: "inverse reinforcement learning",
    themes: `Reward recovery=inverse reinforcement,reward recovery,reward inference
Imitation and preference learning=imitation learning,preference learning,demonstration
Deep methods=neural network,transformer,representation learning
Theory and guarantees=finite-sample,convergence,identifiability,oracle inequality`,
  },
  representation: {
    topic: "self-supervised representation learning for biological data",
    themes: `Representation objectives=self-supervised,contrastive,masked prediction,jepa
Biological applications=genomics,proteomics,single-cell,biological
Architectures=transformer,encoder,graph neural network
Evaluation=benchmark,downstream task,transfer learning`,
  },
};

document.querySelectorAll("[data-preset]").forEach((button) => {
  button.addEventListener("click", () => {
    const preset = presets[button.dataset.preset];
    document.querySelector("#topic").value = preset.topic;
    document.querySelector("#themes").value = preset.themes;
  });
});

parsePdfs.addEventListener("change", () => {
  pdfLimitRow.hidden = !parsePdfs.checked;
});

backend.addEventListener("change", () => {
  backendHint.textContent = backend.value === "openai"
    ? "Uses OPENAI_API_KEY from the terminal that started this app."
    : "No API key or model charges.";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  resetRunUi();
  const payload = {
    topic: document.querySelector("#topic").value.trim(),
    as_of: document.querySelector("#asOf").value,
    recent_days: Number(document.querySelector("#recentDays").value),
    baseline_days: Number(document.querySelector("#baselineDays").value),
    max_results: Number(document.querySelector("#maxResults").value),
    backend: backend.value,
    model: "gpt-6-astra",
    parse_pdfs: parsePdfs.checked,
    max_pdfs: Number(document.querySelector("#maxPdfs").value),
    themes: parseThemes(document.querySelector("#themes").value),
  };

  try {
    const response = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(formatApiError(data));
    await pollRun(data.job_id);
  } catch (error) {
    showFailure(error.message);
  }
});

function parseThemes(raw) {
  return raw.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const index = line.indexOf("=");
    if (index < 1) throw new Error(`Invalid theme line: ${line}`);
    const name = line.slice(0, index).trim();
    const keywords = line.slice(index + 1).split(",").map((value) => value.trim()).filter(Boolean);
    if (!keywords.length) throw new Error(`Theme has no keywords: ${name}`);
    return { name, keywords };
  });
}

async function pollRun(jobId) {
  while (true) {
    const response = await fetch(`/api/runs/${jobId}`);
    const job = await response.json();
    if (!response.ok) throw new Error(formatApiError(job));
    updateStatus(job);
    if (job.status === "complete") {
      await showResults(job);
      return;
    }
    if (job.status === "failed") throw new Error(job.error || "The run failed.");
    await new Promise((resolve) => setTimeout(resolve, 900));
  }
}

function updateStatus(job) {
  statusTitle.textContent = job.status === "queued" ? "Queued" : "Researching";
  statusPercent.textContent = `${job.progress}%`;
  progressBar.style.width = `${job.progress}%`;
  statusMessage.textContent = job.message;
}

async function showResults(job) {
  startButton.disabled = false;
  startButton.querySelector("span").textContent = "Start another scan";
  statusTitle.textContent = "Complete";
  const reportResponse = await fetch(job.report_url);
  reportText.textContent = await reportResponse.text();
  const summary = job.summary || {};
  metricCards.innerHTML = [
    [summary.retrieved ?? 0, "records retrieved"],
    [summary.included ?? 0, "records included"],
    [summary.parsed_pdfs ?? 0, "PDFs parsed"],
    [summary.insights ?? 0, "trend observations"],
  ].map(([value, label]) => `<div class="metric"><b>${value}</b><span>${label}</span></div>`).join("");
  downloadLinks.innerHTML = Object.entries(job.download_urls || {}).map(([name, url]) =>
    `<a href="${url}" download>${friendlyName(name)}</a>`
  ).join("");
  results.hidden = false;
  results.scrollIntoView({ behavior: "smooth", block: "start" });
}

function resetRunUi() {
  startButton.disabled = true;
  startButton.querySelector("span").textContent = "Running research scan…";
  statusPanel.hidden = false;
  statusError.hidden = true;
  results.hidden = true;
  updateStatus({ status: "queued", progress: 0, message: "Preparing the workflow." });
}

function showFailure(message) {
  startButton.disabled = false;
  startButton.querySelector("span").textContent = "Try again";
  statusTitle.textContent = "Needs attention";
  statusError.textContent = message;
  statusError.hidden = false;
}

function formatApiError(data) {
  if (Array.isArray(data.detail)) return data.detail.map((item) => item.msg).join("; ");
  return data.detail || data.error || "Request failed.";
}

function friendlyName(name) {
  return ({
    "trend_report.md": "Report",
    "papers.csv": "Paper table",
    "papers.json": "Evidence JSON",
    "pdf_extraction.json": "PDF record",
    "run_manifest.json": "Run manifest",
  })[name] || name;
}

document.querySelector("#copyReport").addEventListener("click", async (event) => {
  await navigator.clipboard.writeText(reportText.textContent);
  const original = event.currentTarget.textContent;
  event.currentTarget.textContent = "Copied";
  setTimeout(() => { event.currentTarget.textContent = original; }, 1200);
});

