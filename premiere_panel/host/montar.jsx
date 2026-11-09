// Roteiro IA - ExtendScript (ES3) do Premiere Pro.
// abrirProjeto(job): cria o projeto no padrao de pastas da Fokuss (ou so abre, se ja existe).
// puxarRoteiro(job): importa as midias para VIDEOS\<pasta>, as timelines do XML para a pasta
//   de pecas (EPS / PARTES DA COLACAO) e anexa os proxies. Pode ser repetido: as timelines
//   antigas vao para <pecas>\ANTERIORES.
// Devolvem "ok|msgs", "aviso|msgs" ou "erro|msgs".
// Obs.: textos com acentos em escapes \u para nao depender da codificacao do arquivo.

var _RI_TEMP = "_IMPORTANDO ROTEIRO IA";
var _RI_ANTERIORES = "ANTERIORES";
var _RI_AUDIO = /\.(mp3|wav|m4a|aac|aif|aiff|flac|ogg|wma)$/i;

function _ri_norm(p) {
    var s = String(p).replace(/\\/g, "/").toLowerCase();
    return s.replace(/\s+$/, "");
}

function _ri_dois(n) { return (n < 10 ? "0" : "") + n; }

function _ri_garantirPasta(pathStr) {
    var f = new Folder(pathStr);
    if (!f.exists) { f.create(); }
    return f.exists;
}

function _ri_pai(pathStr) {
    return String(pathStr).replace(/\\/g, "/").replace(/\/[^\/]*$/, "");
}

function _ri_coletar(item, saida) {
    var n = item.children ? item.children.numItems : 0;
    for (var i = 0; i < n; i++) {
        var c = item.children[i];
        if (c.type === ProjectItemType.BIN) {
            _ri_coletar(c, saida);
        } else if (c.type === ProjectItemType.CLIP || c.type === ProjectItemType.FILE) {
            saida.push(c);
        }
    }
}

function _ri_resumo(msgs, falhou) {
    var estado = falhou ? "erro" : "ok";
    for (var i = 0; i < msgs.length; i++) {
        if (!falhou && msgs[i].indexOf("aviso:") === 0) { estado = "aviso"; }
    }
    return estado + "|" + msgs.join("\n");
}

function _ri_caminho(item) {
    var mp = "";
    try { mp = item.getMediaPath(); } catch (e) { mp = ""; }
    return mp ? String(mp) : "";
}

function _ri_ehSequencia(item) {
    try { return item.isSequence(); } catch (e) { return false; }
}

// bin filho com esse nome (cria se nao existe)
function _ri_binFilho(pai, nome) {
    var i, n = pai.children ? pai.children.numItems : 0;
    for (i = 0; i < n; i++) {
        var c = pai.children[i];
        if (c.type === ProjectItemType.BIN && c.name === nome) { return c; }
    }
    var novo = pai.createBin(nome);
    if (novo) { return novo; }
    n = pai.children ? pai.children.numItems : 0;
    for (i = 0; i < n; i++) {
        if (pai.children[i].type === ProjectItemType.BIN && pai.children[i].name === nome) { return pai.children[i]; }
    }
    return null;
}

// --- projeto

function _ri_projetoAberto(caminho) {
    var alvo = _ri_norm(caminho);
    try {
        for (var i = 0; i < app.projects.numProjects; i++) {
            if (_ri_norm(app.projects[i].path) === alvo) { return app.projects[i]; }
        }
    } catch (e) { /* sem lista de projetos */ }
    if (app.project && _ri_norm(app.project.path) === alvo) { return app.project; }
    return null;
}

// Abre o projeto do job (ou cria, se ainda nao existe). Devolve o projeto ou null.
function _ri_abrir(job, msgs) {
    var proj = _ri_projetoAberto(job.prproj);
    if (proj) { return proj; }
    _ri_garantirPasta(_ri_pai(job.prproj));
    if (job.backup_dir) { _ri_garantirPasta(job.backup_dir); }
    if (job.export_dir && !_ri_garantirPasta(job.export_dir)) {
        msgs.push("aviso:N\u00e3o consegui criar a pasta dos v\u00eddeos prontos: " + job.export_dir);
    }
    if (new File(job.prproj).exists) {
        if (!app.openDocument(job.prproj, true, true, true)) {
            msgs.push("erro:O Premiere n\u00e3o conseguiu abrir o projeto " + job.prproj + ".");
            return null;
        }
        msgs.push("ok:Projeto aberto: " + job.prproj);
    } else {
        if (app.newProject(job.prproj) === false) {
            msgs.push("erro:O Premiere n\u00e3o conseguiu criar o projeto em " + job.prproj + ". Nada foi alterado.");
            return null;
        }
        msgs.push("ok:Projeto criado: " + job.prproj);
    }
    proj = _ri_projetoAberto(job.prproj) || app.project;
    return proj;
}

// Pastas do padrao Fokuss: COISAS, CREDITOS, <pecas>, SEQUENCIA, TRILHA, VIDEOS\<pasta>.
function _ri_estrutura(proj, job) {
    var p = job.pastas || {};
    var raiz = proj.rootItem;
    var fixas = p.fixas || ["COISAS", "CREDITOS"];
    var e = { fixas: {}, videosPor: {} };
    for (var i = 0; i < fixas.length; i++) { e.fixas[fixas[i]] = _ri_binFilho(raiz, fixas[i]); }
    e.pecas = _ri_binFilho(raiz, p.pecas || "EPS");
    e.sequencia = _ri_binFilho(raiz, p.sequencia || "SEQUENCIA");
    e.trilha = _ri_binFilho(raiz, p.trilha || "TRILHA");
    e.videos = _ri_binFilho(raiz, p.videos || "V\u00cdDEOS");
    e.coisas = e.fixas[fixas[0]] || e.videos;
    var nomes = [], vistos = {}, lista = job.midias || [];
    for (i = 0; i < lista.length; i++) {
        var nome = lista[i].pasta;
        if (nome && !vistos.hasOwnProperty(nome)) { vistos[nome] = true; nomes.push(nome); }
    }
    nomes.sort();
    for (i = 0; i < nomes.length; i++) { e.videosPor[nomes[i]] = _ri_binFilho(e.videos, nomes[i]); }
    return e;
}

function _ri_salvar(proj, job, msgs) {
    proj.save();
    msgs.push("ok:Projeto salvo.");
    if (!job.backup_dir) { return; }
    var d = new Date();
    var base = decodeURI(new File(job.prproj).name).replace(/\.prproj$/i, "");
    var nome = base + " - backup " + d.getFullYear() + "-" + _ri_dois(d.getMonth() + 1) + "-" + _ri_dois(d.getDate())
        + " " + _ri_dois(d.getHours()) + "h" + _ri_dois(d.getMinutes()) + ".prproj";
    var destino = String(job.backup_dir).replace(/\\/g, "/").replace(/\/+$/, "") + "/" + nome;
    if (new File(job.prproj).copy(destino)) {
        msgs.push("ok:Backup copiado: " + destino);
    } else {
        msgs.push("aviso:N\u00e3o consegui copiar o backup para " + job.backup_dir + ".");
    }
}

function abrirProjeto(job) {
    var msgs = [];
    try {
        if (!job || !job.prproj) {
            msgs.push("erro:Job inv\u00e1lido: falta o caminho do projeto (prproj).");
            return _ri_resumo(msgs, true);
        }
        var proj = _ri_abrir(job, msgs);
        if (!proj) { return _ri_resumo(msgs, true); }
        _ri_estrutura(proj, job);
        msgs.push("ok:Pastas no padr\u00e3o da Fokuss.");
        _ri_salvar(proj, job, msgs);
        return _ri_resumo(msgs, false);
    } catch (e) {
        msgs.push("erro:Erro inesperado: " + e);
        return _ri_resumo(msgs, true);
    }
}

// --- puxar o roteiro

function _ri_mapaMidias(job) {
    var m = {}, lista = job.midias || [];
    for (var i = 0; i < lista.length; i++) { m[_ri_norm(lista[i].original)] = lista[i]; }
    return m;
}

function _ri_guardarAnteriores(e) {
    var seqs = [], i, n = e.pecas.children ? e.pecas.children.numItems : 0;
    for (i = 0; i < n; i++) {
        var c = e.pecas.children[i];
        if (c.type !== ProjectItemType.BIN && _ri_ehSequencia(c)) { seqs.push(c); }
    }
    if (!seqs.length) { return 0; }
    var ant = _ri_binFilho(e.pecas, _RI_ANTERIORES);
    var d = new Date();
    var sufixo = " (anterior " + _ri_dois(d.getDate()) + "-" + _ri_dois(d.getMonth() + 1) + " "
        + _ri_dois(d.getHours()) + "h" + _ri_dois(d.getMinutes()) + ")";
    for (i = 0; i < seqs.length; i++) {
        try { seqs[i].name = seqs[i].name + sufixo; } catch (e1) { /* fica com o nome */ }
        seqs[i].moveBin(ant);
    }
    return seqs.length;
}

// espera a importacao (pode ser assincrona) popular o bin
function _ri_esperarItens(bin) {
    var itens = [], ultimo = -1, estavel = 0;
    for (var t = 0; t < 120; t++) {
        itens = [];
        _ri_coletar(bin, itens);
        if (itens.length > 0 && itens.length === ultimo) { estavel++; } else { estavel = 0; }
        if (estavel >= 3) { break; }
        ultimo = itens.length;
        $.sleep(500);
    }
    return itens;
}

function _ri_distribuir(itens, e, mapa) {
    var r = { sequencias: 0, videos: 0, trilha: 0, coisas: 0 };
    for (var i = 0; i < itens.length; i++) {
        var it = itens[i];
        if (_ri_ehSequencia(it)) { it.moveBin(e.pecas); r.sequencias++; continue; }
        var mp = _ri_caminho(it);
        var m = mp ? mapa[_ri_norm(mp)] : null;
        if (m && e.videosPor[m.pasta]) { it.moveBin(e.videosPor[m.pasta]); r.videos++; }
        else if (mp && _RI_AUDIO.test(mp)) { it.moveBin(e.trilha); r.trilha++; }
        else { it.moveBin(e.coisas); r.coisas++; }
    }
    return r;
}

function _ri_importarFaltando(proj, e, job, msgs) {
    var presentes = {}, itens = [], i;
    _ri_coletar(proj.rootItem, itens);
    for (i = 0; i < itens.length; i++) {
        var mp = _ri_caminho(itens[i]);
        if (mp) { presentes[_ri_norm(mp)] = true; }
    }
    var porPasta = {}, lista = job.midias || [], total = 0, faltam = 0;
    for (i = 0; i < lista.length; i++) {
        var m = lista[i];
        if (presentes[_ri_norm(m.original)]) { continue; }
        if (!new File(m.original).exists) { faltam++; continue; }
        if (!porPasta.hasOwnProperty(m.pasta)) { porPasta[m.pasta] = []; }
        porPasta[m.pasta].push(m.original);
        total++;
    }
    var falhas = [];
    for (var pasta in porPasta) {
        if (!porPasta.hasOwnProperty(pasta)) { continue; }
        var destino = e.videosPor[pasta] || e.videos;
        if (proj.importFiles(porPasta[pasta], true, destino, false) === false) { falhas.push(pasta); }
    }
    if (total) { msgs.push((falhas.length ? "aviso:" : "ok:") + "M\u00eddias importadas do disco para V\u00cdDEOS: " + total + "."); }
    if (falhas.length) { msgs.push("aviso:O Premiere recusou a importa\u00e7\u00e3o das pastas: " + falhas.join(", ") + "."); }
    if (faltam) { msgs.push("aviso:" + faltam + " m\u00eddia(s) n\u00e3o encontrada(s) no disco de origem (o R: est\u00e1 conectado?)."); }
}

function _ri_proxies(proj, job, msgs) {
    var mapa = {}, lista = job.proxies || [], i;
    for (i = 0; i < lista.length; i++) { mapa[_ri_norm(lista[i].original)] = lista[i].proxy; }
    var itens = [];
    _ri_coletar(proj.rootItem, itens);
    var anexados = 0, ja = 0, falhados = [];
    for (i = 0; i < itens.length; i++) {
        var it = itens[i], mp = _ri_caminho(it);
        if (!mp || !mapa.hasOwnProperty(_ri_norm(mp))) { continue; }
        try {
            if (it.hasProxy()) { ja++; continue; }
            if (it.canProxy() && it.attachProxy(mapa[_ri_norm(mp)], 0)) { anexados++; } else { falhados.push(it.name); }
        } catch (e) { falhados.push(it.name); }
    }
    msgs.push((falhados.length ? "aviso:" : "ok:") + "Proxies anexados: " + anexados + (ja ? " (" + ja + " j\u00e1 tinham)" : "") + ".");
    if (falhados.length) {
        msgs.push("aviso:Falha ao anexar proxy em " + falhados.length + " clipe(s): " + falhados.slice(0, 10).join(", ")
            + ". Plano B: selecione a pasta V\u00cdDEOS, Proxy > Anexar proxies, e aponte para a pasta PROXIES.");
    }
}

function puxarRoteiro(job) {
    var msgs = [];
    try {
        if (!job || !job.prproj) {
            msgs.push("erro:Job inv\u00e1lido: falta o caminho do projeto (prproj).");
            return _ri_resumo(msgs, true);
        }
        if (!job.xml || !new File(job.xml).exists) {
            msgs.push("erro:O roteiro (XML) ainda n\u00e3o foi gerado" + (job.xml ? ": " + job.xml : "") + ".");
            return _ri_resumo(msgs, true);
        }
        var proj = _ri_abrir(job, msgs);
        if (!proj) { return _ri_resumo(msgs, true); }
        var e = _ri_estrutura(proj, job);
        var mapa = _ri_mapaMidias(job);

        var antes = _ri_guardarAnteriores(e);
        if (antes) { msgs.push("ok:" + antes + " timeline(s) anterior(es) guardada(s) em " + e.pecas.name + "\\" + _RI_ANTERIORES + "."); }

        var temp = _ri_binFilho(proj.rootItem, _RI_TEMP);
        if (proj.importFiles([job.xml], true, temp, false) === false) {
            msgs.push("erro:O Premiere n\u00e3o aceitou o XML do roteiro: " + job.xml);
            return _ri_resumo(msgs, true);
        }
        var itens = _ri_esperarItens(temp);
        if (!itens.length) {
            msgs.push("erro:O XML do roteiro foi importado, mas nada apareceu no projeto.");
            return _ri_resumo(msgs, true);
        }
        // une os clipes que o XML trouxe aos que ja estavam no projeto (mesmo arquivo)
        try { proj.consolidateDuplicates(); } catch (e2) { /* versao sem a funcao */ }
        itens = [];
        _ri_coletar(temp, itens);
        var r = _ri_distribuir(itens, e, mapa);
        try { temp.deleteBin(); } catch (e3) { msgs.push("aviso:Apague a pasta " + _RI_TEMP + " (ficou vazia)."); }
        msgs.push("ok:Timelines do roteiro em " + e.pecas.name + ": " + r.sequencias + ".");
        if (r.trilha) { msgs.push("ok:M\u00fasicas em " + e.trilha.name + ": " + r.trilha + "."); }

        _ri_importarFaltando(proj, e, job, msgs);
        _ri_proxies(proj, job, msgs);

        // cartela do ano (Formatura): MOGRT preenchido com os dados da ficha
        if (job.cartela && job.cartela.mogrt) { _ri_cartela(job, msgs); }

        _ri_salvar(proj, job, msgs);
        return _ri_resumo(msgs, false);
    } catch (err) {
        msgs.push("erro:Erro inesperado: " + err);
        return _ri_resumo(msgs, true);
    }
}

// ------------------------------------------------------------ entregas (Formatura: colacao)
// exportarEntregas(job): manda cada sequencia de job.entregas para a fila do Media Encoder,
// com o nome de entrega, na pasta de exportacao (G). O preset (.epr) e pedido uma vez e
// guardado em Folder.userData/RoteiroIA/preset_exportacao.txt.

function _ri_presetExportacao() {
    var pasta = new Folder(Folder.userData.fsName + "/RoteiroIA");
    if (!pasta.exists) { pasta.create(); }
    var arq = new File(pasta.fsName + "/preset_exportacao.txt");
    var caminho = "";
    if (arq.exists && arq.open("r")) { caminho = arq.read(); arq.close(); }
    caminho = String(caminho).replace(/^\s+|\s+$/g, "");
    if (caminho && new File(caminho).exists) { return caminho; }
    var escolhido = File.openDialog("Escolha o preset de exporta\u00e7\u00e3o (.epr) das entregas", "*.epr", false);
    if (!escolhido) { return ""; }
    if (arq.open("w")) { arq.write(escolhido.fsName); arq.close(); }
    return escolhido.fsName;
}

function _ri_acharSequencia(nome) {
    var seqs = app.project.sequences;
    for (var i = 0; i < seqs.numSequences; i++) {
        if (seqs[i].name === nome) { return seqs[i]; }
    }
    return null;
}

function exportarEntregas(job) {
    var msgs = [];
    try {
        var lista = (job && job.entregas) ? job.entregas : [];
        if (!lista.length) {
            msgs.push("erro:Este job n\u00e3o tem entregas (s\u00f3 a \u00edntegra da cola\u00e7\u00e3o tem).");
            return _ri_resumo(msgs, true);
        }
        if (!app.project) {
            msgs.push("erro:Abra o projeto da cola\u00e7\u00e3o no Premiere antes de exportar.");
            return _ri_resumo(msgs, true);
        }
        var preset = _ri_presetExportacao();
        if (!preset) {
            msgs.push("erro:Nenhum preset de exporta\u00e7\u00e3o escolhido; nada foi exportado.");
            return _ri_resumo(msgs, true);
        }
        if (job.export_dir && !_ri_garantirPasta(job.export_dir)) {
            msgs.push("erro:N\u00e3o consegui criar a pasta de exporta\u00e7\u00e3o: " + job.export_dir);
            return _ri_resumo(msgs, true);
        }
        app.encoder.launchEncoder();
        var n = 0;
        for (var i = 0; i < lista.length; i++) {
            var e = lista[i];
            var seq = _ri_acharSequencia(e.sequencia);
            if (!seq) {
                msgs.push("aviso:Sequ\u00eancia n\u00e3o encontrada no projeto: " + e.sequencia);
                continue;
            }
            var id = app.encoder.encodeSequence(seq, e.arquivo, preset, app.encoder.ENCODE_ENTIRE, 0);
            if (id) { n++; } else { msgs.push("aviso:O Media Encoder recusou: " + e.sequencia); }
        }
        if (n > 0) {
            app.encoder.startBatch();
            msgs.push("ok:" + n + " entrega(s) na fila do Media Encoder, para " + (job.export_dir || "a pasta de exporta\u00e7\u00e3o") + ".");
        }
        return _ri_resumo(msgs, n === 0);
    } catch (err) {
        msgs.push("erro:Erro inesperado: " + err);
        return _ri_resumo(msgs, true);
    }
}

// ------------------------------------------------------------ cartela (Formatura)
// _ri_cartela(job, msgs): insere o MOGRT do ano no inicio de cada sequencia de job.cartela,
// na faixa de video mais alta (o XML ja traz uma faixa vazia reservada), e preenche cada campo
// cujo nome de exibicao e igual a um nome de job.cartela.campos.

function _ri_cartela(job, msgs) {
    var c = job.cartela;
    var arq = new File(c.mogrt);
    if (!arq.exists) {
        msgs.push("aviso:Cartela MOGRT n\u00e3o encontrada: " + c.mogrt);
        return;
    }
    var nomes = c.sequencias || [];
    for (var i = 0; i < nomes.length; i++) {
        var seq = _ri_acharSequencia(nomes[i]);
        if (!seq) {
            msgs.push("aviso:Sequ\u00eancia da cartela n\u00e3o encontrada: " + nomes[i]);
            continue;
        }
        try {
            var faixa = seq.videoTracks.numTracks - 1;
            var clip = seq.importMGT(arq.fsName, "0", faixa, 0);
            if (!clip) {
                msgs.push("aviso:O Premiere n\u00e3o p\u00f4s a cartela em " + nomes[i] + ".");
                continue;
            }
            var comp = clip.getMGTComponent();
            var semLugar = [];
            for (var campo in c.campos) {
                if (!c.campos.hasOwnProperty(campo)) { continue; }
                var prm = comp ? comp.properties.getParamForDisplayName(campo) : null;
                if (prm) { prm.setValue(c.campos[campo], true); } else { semLugar.push(campo); }
            }
            msgs.push("ok:Cartela do ano posta e preenchida em " + nomes[i] + ".");
            if (semLugar.length) {
                msgs.push("aviso:Campos sem lugar na cartela (" + nomes[i] + "): " + semLugar.join(", ")
                    + ". Os nomes dos campos do MOGRT devem ser iguais (Institui\u00e7\u00e3o, Curso, Turma...).");
            }
        } catch (e) {
            msgs.push("aviso:N\u00e3o consegui p\u00f4r a cartela em " + nomes[i] + ": " + e);
        }
    }
}
