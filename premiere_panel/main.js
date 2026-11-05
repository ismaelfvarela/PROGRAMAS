// Painel Roteiro IA (CEP). Roda no Chromium com Node habilitado (ver manifest).
(function () {
  var PADRAO = "Y:\\SISTEMA ROTEIRO\\ultimo_job.json";
  var jobPath = PADRAO;
  var fs = null;
  try { fs = require("fs"); } catch (e) { fs = null; }

  var elJob = document.getElementById("jobCaminho");
  var elLog = document.getElementById("log");
  var btnMontar = document.getElementById("btnMontar");
  var btnEscolher = document.getElementById("btnEscolher");
  var elArquivo = document.getElementById("arquivo");

  function log(texto, tipo) {
    var p = document.createElement("div");
    p.className = "linha " + (tipo || "info");
    var icone = tipo === "ok" ? "\u2714 " : tipo === "erro" ? "\u2716 " : "\u25B6 ";
    p.textContent = icone + texto;
    elLog.appendChild(p);
    elLog.scrollTop = elLog.scrollHeight;
  }

  function mostrarJob() { elJob.textContent = "Job: " + jobPath; }

  function escolher() {
    try {
      if (window.cep && window.cep.fs && window.cep.fs.showOpenDialogEx) {
        var r = window.cep.fs.showOpenDialogEx(false, false, "Escolher job", jobPath, ["json"]);
        if (r && r.data && r.data.length) { jobPath = r.data[0]; mostrarJob(); }
        return;
      }
    } catch (e) { /* cai no seletor simples */ }
    elArquivo.click();
  }

  elArquivo.addEventListener("change", function () {
    var f = elArquivo.files && elArquivo.files[0];
    if (f && f.path) { jobPath = f.path; mostrarJob(); }
    else if (f) { log("N\u00e3o foi poss\u00edvel obter o caminho do arquivo escolhido.", "erro"); }
  });

  function lerJob() {
    if (!fs) throw new Error("Node n\u00e3o est\u00e1 habilitado no painel (reinstale o painel).");
    var texto = fs.readFileSync(jobPath, "utf8");
    if (texto.charCodeAt(0) === 0xFEFF) texto = texto.slice(1);
    return JSON.parse(texto);
  }

  function montar() {
    elLog.innerHTML = "";
    var job;
    try { job = lerJob(); }
    catch (e) { log("N\u00e3o consegui ler o job: " + e.message, "erro"); return; }
    if (!window.__adobe_cep__) { log("Este painel precisa rodar dentro do Premiere.", "erro"); return; }
    btnMontar.disabled = true;
    log("Montando o projeto \u201C" + (job.evento || "") + "\u201D... isso pode levar alguns minutos.");
    var script = "montarProjeto(" + JSON.stringify(job) + ")";
    window.__adobe_cep__.evalScript(script, function (res) {
      btnMontar.disabled = false;
      res = String(res || "");
      var i = res.indexOf("|");
      var estado = i >= 0 ? res.slice(0, i) : "erro";
      var corpo = i >= 0 ? res.slice(i + 1) : (res || "Sem resposta do Premiere.");
      var tipo = estado === "ok" ? "ok" : "erro";
      var linhas = corpo.split("\n");
      for (var k = 0; k < linhas.length; k++) {
        if (linhas[k]) log(linhas[k], tipo);
      }
    });
  }

  btnEscolher.addEventListener("click", escolher);
  btnMontar.addEventListener("click", montar);
  mostrarJob();
})();
