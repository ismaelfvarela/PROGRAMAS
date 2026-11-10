// Testa premiere_panel/pedidos.js no Node: uso: node pedidos_teste.js <pedidos.js> <pasta>
// Imprime JSON com o que aconteceu (o pytest confere).
var fs = require("fs"), vm = require("vm"), path = require("path");
var arquivo = process.argv[2], pasta = process.argv[3];
var chamadas = [];
function carregar() {
  var ctx = {
    require: require, Date: Date, JSON: JSON,
    window: { ROTEIRO_SISTEMA: pasta, __adobe_cep__: {
      evalScript: function (s, cb) { chamadas.push(s.slice(0, s.indexOf("("))); cb("ok|ok:feito"); } } }
  };
  ctx.window.window = ctx.window;
  vm.createContext(ctx);
  vm.runInContext("(function(window){" + fs.readFileSync(arquivo, "utf8") + "})(window);", ctx);
  return ctx.window.RoteiroPedidos;
}
var painel = carregar(), servico = carregar();
var job = path.join(pasta, "job.json");
fs.writeFileSync(job, JSON.stringify({ evento: "EV", prproj: "E:\\EV.prproj" }));
function pedir(acao, quando) {
  fs.writeFileSync(path.join(pasta, "pedido_premiere.json"),
    JSON.stringify({ acao: acao, job: job, quando: quando || new Date().toISOString() }));
}
var out = {};
pedir("puxar");
var a = servico.pegar("servico"), b = painel.pegar("painel");
out.so_um_pega = !!a !== !!b;
out.acao = (a || b).acao;
out.sobrou_pedido = fs.existsSync(path.join(pasta, "pedido_premiere.json"));
servico.executar(a || b, "servico", function () {});
out.chamadas = chamadas;
out.resultado = JSON.parse(fs.readFileSync(path.join(pasta, "resultado_premiere.json"), "utf8"));
pedir("abrir", "2020-01-01T00:00:00");
out.velho_ignorado = servico.pegar("servico") === null;
pedir("apagar_tudo");
out.desconhecido_ignorado = servico.pegar("servico") === null;
out.lendo_sobrando = fs.readdirSync(pasta).filter(function (f) { return /\.lendo$/.test(f); }).length;
process.stdout.write(JSON.stringify(out));
