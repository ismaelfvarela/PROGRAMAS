// Pedidos do app Roteiro IA ao Premiere (compartilhado pelo painel vis\u00edvel e pelo servi\u00e7o
// invis\u00edvel que abre junto com o Premiere). O app grava <SISTEMA>\pedido_premiere.json
// ({acao: "abrir"|"puxar", job, quando}); quem pegar primeiro renomeia o arquivo (s\u00f3 um
// consegue), executa e grava <SISTEMA>\resultado_premiere.json para o app mostrar.
(function (raiz) {
  var SISTEMA = raiz.ROTEIRO_SISTEMA || "Y:\\SISTEMA ROTEIRO";  // ROTEIRO_SISTEMA: testes
  var PEDIDO = SISTEMA + "\\pedido_premiere.json";
  var RESULTADO = SISTEMA + "\\resultado_premiere.json";
  var VALIDO_MS = 30 * 60 * 1000;
  var FUNCOES = { abrir: "abrirProjeto", puxar: "puxarRoteiro" };
  var fs = null;
  try { fs = require("fs"); } catch (e) { fs = null; }

  function lerJson(caminho) {
    if (!fs) throw new Error("Node n\u00e3o est\u00e1 habilitado no painel (reinstale o painel).");
    var texto = fs.readFileSync(caminho, "utf8");
    if (texto.charCodeAt(0) === 0xFEFF) texto = texto.slice(1);
    return JSON.parse(texto);
  }

  // Pega o pedido para si (rename \u00e9 at\u00f4mico: se outro j\u00e1 pegou, falha). Devolve o pedido ou null.
  function pegar(quem) {
    if (!fs) { return null; }
    var meu = PEDIDO + "." + quem + "." + Date.now() + ".lendo";
    try {
      if (!fs.existsSync(PEDIDO)) { return null; }
      fs.renameSync(PEDIDO, meu);
    } catch (e) { return null; }
    var pedido = null;
    try { pedido = lerJson(meu); } catch (e2) { pedido = null; }
    try { fs.unlinkSync(meu); } catch (e3) { /* fica para tr\u00e1s, sem efeito */ }
    if (!pedido || !FUNCOES.hasOwnProperty(pedido.acao)) { return null; }
    var quando = Date.parse(pedido.quando || "");
    if (!isNaN(quando) && Date.now() - quando > VALIDO_MS) { return null; }  // pedido velho
    return pedido;
  }

  function gravarResultado(pedido, res, quem) {
    if (!fs) { return; }
    var i = res.indexOf("|");
    var r = {
      acao: pedido.acao, job: pedido.job || "", pedido_em: pedido.quando || "",
      estado: i >= 0 ? res.slice(0, i) : "erro",
      mensagens: (i >= 0 ? res.slice(i + 1) : (res || "Sem resposta do Premiere.")).split("\n"),
      quando: new Date().toISOString(), por: quem
    };
    try { fs.writeFileSync(RESULTADO, JSON.stringify(r, null, 2), "utf8"); } catch (e) { /* sem disco */ }
  }

  // Executa o pedido no host (montar.jsx); `pronto(res)` recebe "ok|..."/"aviso|..."/"erro|...".
  function executar(pedido, quem, pronto) {
    var job;
    try { job = lerJson(pedido.job); }
    catch (e) {
      var res = "erro|erro:N\u00e3o consegui ler o job: " + e.message;
      gravarResultado(pedido, res, quem);
      if (pronto) { pronto(res, null); }
      return;
    }
    if (!window.__adobe_cep__) { return; }
    window.__adobe_cep__.evalScript(FUNCOES[pedido.acao] + "(" + JSON.stringify(job) + ")", function (r) {
      var res = String(r || "");
      gravarResultado(pedido, res, quem);
      if (pronto) { pronto(res, job); }
    });
  }

  raiz.RoteiroPedidos = {
    SISTEMA: SISTEMA, PEDIDO: PEDIDO, RESULTADO: RESULTADO, FUNCOES: FUNCOES,
    lerJson: lerJson, pegar: pegar, executar: executar, gravarResultado: gravarResultado
  };
})(typeof window !== "undefined" ? window : this);
