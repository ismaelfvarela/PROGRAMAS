// Servi\u00e7o invis\u00edvel do Roteiro IA: abre sozinho com o Premiere (manifest: StartOn) e atende os
// pedidos do app mesmo com o painel fechado.
(function () {
  var P = window.RoteiroPedidos;
  var ocupado = false;
  function conferir() {
    if (ocupado) { return; }
    var pedido = P.pegar("servico");
    if (!pedido) { return; }
    ocupado = true;
    P.executar(pedido, "servico", function () { ocupado = false; });
  }
  conferir();
  setInterval(conferir, 2000);
})();
