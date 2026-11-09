// Painel Roteiro IA (CEP). Roda no Chromium com Node habilitado (ver manifest).
// O app Roteiro IA deixa pedidos em <SISTEMA>\pedido_premiere.json ({acao: "abrir"|"puxar",
// job}); o painel confere a cada 2 s, apaga o pedido e executa.
(function () {
  var SISTEMA = "Y:\\SISTEMA ROTEIRO";
  var PADRAO = SISTEMA + "\\ultimo_job.json";
  var PEDIDO = SISTEMA + "\\pedido_premiere.json";
  var PEDIDO_VALIDO_MS = 30 * 60 * 1000;
  var jobPath = PADRAO;
  var ocupado = false;
  var fs = null;
  try { fs = require("fs"); } catch (e) { fs = null; }

  var elJob = document.getElementById("jobCaminho");
  var elLog = document.getElementById("log");
  var btnAbrir = document.getElementById("btnAbrir");
  var btnPuxar = document.getElementById("btnPuxar");
  var btnExportar = document.getElementById("btnExportar");
  var btnEscolher = document.getElementById("btnEscolher");
  var elArquivo = document.getElementById("arquivo");
  var botoes = [btnAbrir, btnPuxar, btnExportar, btnEscolher];

  function log(texto, tipo) {
    var p = document.createElement("div");
    p.className = "linha " + (tipo || "info");
    var icone = tipo === "ok" ? "\u2714 " : tipo === "erro" ? "\u2716 " : tipo === "aviso" ? "\u26A0 " : "\u25B6 ";
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

  function lerJson(caminho) {
    if (!fs) throw new Error("Node n\u00e3o est\u00e1 habilitado no painel (reinstale o painel).");
    var texto = fs.readFileSync(caminho, "utf8");
    if (texto.charCodeAt(0) === 0xFEFF) texto = texto.slice(1);
    return JSON.parse(texto);
  }

  // Mostra a resposta do host ("ok|msgs", "aviso|msgs" ou "erro|msgs") no registro.
  function mostrar(res, titulos) {
    var i = res.indexOf("|");
    var estado = i >= 0 ? res.slice(0, i) : "erro";
    var corpo = i >= 0 ? res.slice(i + 1) : (res || "Sem resposta do Premiere.");
    var titulo = estado === "ok" ? titulos[0] : estado === "aviso" ? titulos[1] : titulos[2];
    log(titulo, estado === "ok" ? "ok" : estado === "aviso" ? "aviso" : "erro");
    var linhas = corpo.split("\n");
    for (var k = 0; k < linhas.length; k++) {
      var l = linhas[k];
      if (!l) continue;
      var tipo = "info";
      var m = /^(ok|aviso|erro):/.exec(l);
      if (m) { tipo = m[1]; l = l.slice(m[0].length); }
      else if (estado === "erro") { tipo = "erro"; }
      log(l, tipo);
    }
  }

  function travar(sim) {
    ocupado = sim;
    for (var i = 0; i < botoes.length; i++) { botoes[i].disabled = sim; }
  }

  // L\u00ea o job e chama a fun\u00e7\u00e3o do host (montar.jsx) com ele.
  function rodar(funcao, inicio, titulos) {
    if (ocupado) { return; }
    elLog.innerHTML = "";
    var job;
    try { job = lerJson(jobPath); }
    catch (e) { log("N\u00e3o consegui ler o job: " + e.message, "erro"); return; }
    if (!window.__adobe_cep__) { log("Este painel precisa rodar dentro do Premiere.", "erro"); return; }
    travar(true);
    log(inicio(job));
    window.__adobe_cep__.evalScript(funcao + "(" + JSON.stringify(job) + ")", function (res) {
      travar(false);
      mostrar(String(res || ""), titulos);
    });
  }

  var ACOES = {
    abrir: function () {
      rodar("abrirProjeto", function (job) {
        return "Abrindo o projeto \u201C" + (job.evento || "") + "\u201D no padr\u00e3o da Fokuss...";
      }, ["Projeto pronto", "Projeto pronto, com avisos", "N\u00e3o foi poss\u00edvel abrir o projeto"]);
    },
    puxar: function () {
      rodar("puxarRoteiro", function (job) {
        return "Puxando o roteiro de \u201C" + (job.evento || "") + "\u201D... isso pode levar alguns minutos.";
      }, ["Roteiro no projeto", "Roteiro no projeto, com avisos", "N\u00e3o foi poss\u00edvel puxar o roteiro"]);
    },
    // Formatura (cola\u00e7\u00e3o): cada parte vai para a fila do Media Encoder, com o nome de entrega, no G.
    exportar: function () {
      rodar("exportarEntregas", function (job) {
        return "Mandando as entregas de \u201C" + (job.evento || "") + "\u201D para o Media Encoder...";
      }, ["Entregas na fila do Media Encoder", "Entregas na fila, com avisos", "N\u00e3o foi poss\u00edvel exportar"]);
    }
  };

  // Pedido deixado pelo app Roteiro IA (bot\u00f5es "Abrir no Premiere" e "Puxar roteiro").
  function conferirPedido() {
    if (ocupado || !fs) { return; }
    var pedido;
    try {
      if (!fs.existsSync(PEDIDO)) { return; }
      pedido = lerJson(PEDIDO);
      fs.unlinkSync(PEDIDO);
    } catch (e) { return; }
    var quando = Date.parse(pedido.quando || "");
    if (!isNaN(quando) && Date.now() - quando > PEDIDO_VALIDO_MS) { return; }  // pedido velho
    if (!ACOES.hasOwnProperty(pedido.acao) || pedido.acao === "exportar") { return; }
    if (pedido.job) { jobPath = pedido.job; mostrarJob(); }
    ACOES[pedido.acao]();
  }

  btnEscolher.addEventListener("click", escolher);
  btnAbrir.addEventListener("click", ACOES.abrir);
  btnPuxar.addEventListener("click", ACOES.puxar);
  btnExportar.addEventListener("click", ACOES.exportar);
  mostrarJob();
  conferirPedido();
  setInterval(conferirPedido, 2000);
})();
