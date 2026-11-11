// Premiere falso (ExtendScript) para rodar host/montar.jsx no Node.
// Uso: node premiere_falso.js <montar.jsx> <cenario.json>  -> imprime JSON com o resultado.
var fs = require("fs"), vm = require("vm");
var jsx = fs.readFileSync(process.argv[2], "utf8");
var cen = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
var existentes = {};
(cen.arquivos || []).forEach(function (f) { existentes[f.replace(/\\/g, "/").toLowerCase()] = true; });
function existe(p) { return !!existentes[String(p).replace(/\\/g, "/").toLowerCase()]; }

var ProjectItemType = { CLIP: 1, BIN: 2, ROOT: 3, FILE: 4 };
function Item(nome, tipo, caminho, seq) {
  this.name = nome; this.type = tipo; this._caminho = caminho || ""; this._seq = !!seq;
  this._pai = null; this._filhos = []; this._proxy = null;
  var self = this;
  this.children = { get numItems() { return self._filhos.length; } };
  Object.defineProperty(this.children, "length", { get: function () { return self._filhos.length; } });
}
function sync(it) { for (var i = 0; i < 1000; i++) delete it.children[i]; it._filhos.forEach(function (f, i) { it.children[i] = f; }); }
Item.prototype.add = function (f) { if (f._pai) f._pai.remove(f); f._pai = this; this._filhos.push(f); sync(this); return f; };
Item.prototype.remove = function (f) { this._filhos.splice(this._filhos.indexOf(f), 1); f._pai = null; sync(this); };
Item.prototype.createBin = function (n) { return this.add(new Item(n, ProjectItemType.BIN)); };
Item.prototype.moveBin = function (b) { b.add(this); };
Item.prototype.deleteBin = function () { this._pai.remove(this); };
Item.prototype.getMediaPath = function () { return this._caminho; };
Item.prototype.isSequence = function () { return this._seq; };
Item.prototype.hasProxy = function () { return !!this._proxy; };
Item.prototype.canProxy = function () { return !this._seq; };
Item.prototype.attachProxy = function (p) { this._proxy = p; return true; };

function Projeto(caminho) { this.path = caminho; this.rootItem = new Item("root", ProjectItemType.ROOT); this.salvo = 0; }
Projeto.prototype.save = function () { this.salvo++; existentes[this.path.replace(/\\/g, "/").toLowerCase()] = true; };
Projeto.prototype.consolidateDuplicates = function () {
  // mantém o primeiro item de cada arquivo (o que já estava no projeto) e tira os repetidos
  var vistos = {}, todos = [];
  (function col(it) { it._filhos.forEach(function (f) { if (f.type === ProjectItemType.BIN) col(f); else todos.push(f); }); })(this.rootItem);
  var ordem = todos.sort(function (a, b) { return (a._ordem || 0) - (b._ordem || 0); });
  ordem.forEach(function (f) { if (!f._caminho) return; var k = f._caminho.toLowerCase(); if (vistos[k]) f._pai.remove(f); else vistos[k] = true; });
};
var contador = 0;
Projeto.prototype.importFiles = function (lista, ui, bin) {
  var self = this;
  lista.forEach(function (p) {
    if (/\.xml$/i.test(p)) {
      if (cen.xml_falha) return;
      var b = bin.createBin(p.replace(/^.*[\\\/]/, "").replace(/\.xml$/i, ""));
      cen.xml.sequencias.forEach(function (n) { b.add(new Item(n, ProjectItemType.CLIP, "", true)); });
      cen.xml.midias.forEach(function (m) { var it = b.add(new Item(m.replace(/^.*[\\\/]/, ""), ProjectItemType.CLIP, m)); it._ordem = ++contador; });
    } else {
      var it = bin.add(new Item(p.replace(/^.*[\\\/]/, ""), ProjectItemType.CLIP, p)); it._ordem = ++contador;
    }
  });
  return true;
};

var app = {
  projects: [], get project() { return this._ativo || null; },
  newProject: function (p) { if (cen.novo_falha) { throw new Error("Unknown error exception"); } var pr = new Projeto(p); this.projects.push(pr); this._ativo = pr; return true; },
  openDocument: function (p) { var pr = new Projeto(p); this.projects.push(pr); this._ativo = pr; return true; }
};
Object.defineProperty(app.projects, "numProjects", { get: function () { return this.length; } });
if (cen.projeto_existente) { existentes[cen.projeto_existente.replace(/\\/g, "/").toLowerCase()] = true; }

function File(p) { this.fsName = p; this.name = encodeURI(String(p).replace(/^.*[\\\/]/, "")); }
Object.defineProperty(File.prototype, "exists", { get: function () { return existe(this.fsName); } });
File.prototype.copy = function (d) { existentes[d.replace(/\\/g, "/").toLowerCase()] = true; return true; };
function Folder(p) { this.fsName = p; }
Object.defineProperty(Folder.prototype, "exists", { get: function () { return true; } });
Folder.prototype.create = function () { return true; };

var ctx = { app: app, File: File, Folder: Folder, ProjectItemType: ProjectItemType, $: { sleep: function () {} } };
vm.createContext(ctx);
vm.runInContext(jsx, ctx);

function arvore(it) {
  var o = {};
  it._filhos.forEach(function (f) {
    if (f.type === ProjectItemType.BIN) o[f.name + "/"] = arvore(f);
    else o[f.name] = f._seq ? "SEQ" : (f._proxy ? "proxy" : "clip");
  });
  return o;
}
var saidas = cen.passos.map(function (passo) { return ctx[passo](cen.job); });
var proj = app.project;
process.stdout.write(JSON.stringify({ saidas: saidas, arvore: proj ? arvore(proj.rootItem) : null,
  projetos: app.projects.length, salvo: proj ? proj.salvo : 0 }));
