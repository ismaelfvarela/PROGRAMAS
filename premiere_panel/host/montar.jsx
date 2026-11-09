// Roteiro IA - ExtendScript (ES3) do Premiere Pro.
// montarProjeto(job) recebe o objeto do job.json e devolve "ok|msgs" ou "erro|msgs".
// Obs.: textos com acentos em escapes \u para nao depender da codificacao do arquivo.

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

// mesma regra do Python (next_free_prproj): X.prproj, X_v2.prproj, X_v3.prproj...
function _ri_prprojLivre(pathStr) {
    if (!new File(pathStr).exists) { return pathStr; }
    var base = String(pathStr).replace(/\.prproj$/i, "");
    var n = 2;
    while (new File(base + "_v" + n + ".prproj").exists) { n++; }
    return base + "_v" + n + ".prproj";
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

function _ri_contarCasados(mapa) {
    var itens = [];
    _ri_coletar(app.project.rootItem, itens);
    var casados = 0;
    for (var i = 0; i < itens.length; i++) {
        var mp = "";
        try { mp = itens[i].getMediaPath(); } catch (e) { mp = ""; }
        if (mp && mapa.hasOwnProperty(_ri_norm(mp))) { casados++; }
    }
    return { itens: itens, total: itens.length, casados: casados };
}

function montarProjeto(job) {
    var msgs = [];
    try {
        if (!job || !job.prproj || !job.xml) {
            msgs.push("erro:Job inv\u00e1lido: faltam os campos prproj ou xml.");
            return _ri_resumo(msgs, true);
        }
        var xmlFile = new File(job.xml);
        if (!xmlFile.exists) {
            msgs.push("erro:XML do Premiere n\u00e3o encontrado: " + job.xml);
            return _ri_resumo(msgs, true);
        }

        // 1. pastas
        _ri_garantirPasta(_ri_pai(job.prproj));
        if (job.backup_dir) { _ri_garantirPasta(job.backup_dir); }
        if (job.export_dir) {
            if (_ri_garantirPasta(job.export_dir)) {
                msgs.push("ok:Pasta de exporta\u00e7\u00e3o pronta: " + job.export_dir);
            } else {
                msgs.push("aviso:N\u00e3o consegui criar a pasta de exporta\u00e7\u00e3o: " + job.export_dir);
            }
        }

        // 2. projeto novo (nunca sobrescreve)
        var prproj = _ri_prprojLivre(job.prproj);
        if (prproj !== job.prproj) {
            msgs.push("aviso:O projeto " + job.prproj + " j\u00e1 existia; criei uma nova vers\u00e3o sem mexer nele.");
        }
        var criado = app.newProject(prproj);
        if (criado === false) {
            msgs.push("erro:O Premiere n\u00e3o conseguiu criar o projeto em " + prproj + ". Nada foi alterado.");
            return _ri_resumo(msgs, true);
        }
        msgs.push("ok:Projeto criado: " + prproj);

        // 3. importar XML
        var imp = app.project.importFiles([job.xml], true, app.project.rootItem, false);
        if (imp === false) {
            msgs.push("erro:Falha ao importar o XML: " + job.xml);
            return _ri_resumo(msgs, true);
        }

        var mapa = {};
        var lista = job.proxies || [];
        var i;
        for (i = 0; i < lista.length; i++) {
            mapa[_ri_norm(lista[i].original)] = lista[i].proxy;
        }

        // 3b. a importacao pode ser assincrona: espera a arvore do projeto popular
        var estado = _ri_contarCasados(mapa);
        var ultimo = estado.total, estavel = 0, tentativas = 0;
        while (estado.casados === 0 && tentativas < 40) {
            if (estado.total > 0 && estado.total === ultimo) { estavel++; } else { estavel = 0; }
            if (estavel >= 3) { break; }
            ultimo = estado.total;
            $.sleep(500);
            tentativas++;
            estado = _ri_contarCasados(mapa);
        }
        if (estado.casados === 0) {
            msgs.push("aviso:Nenhum clipe do XML encontrado ainda \u2014 use Proxy \u2192 Anexar proxies (plano B).");
        } else {
            msgs.push("ok:XML importado (sequ\u00eancias por epis\u00f3dio).");
        }

        // 4. proxies
        var itens = estado.itens;
        var anexados = 0, falhas = 0, achados = {};
        var falhados = [];
        for (i = 0; i < itens.length; i++) {
            var it = itens[i];
            var mp = "";
            try { mp = it.getMediaPath(); } catch (e1) { mp = ""; }
            if (!mp) { continue; }
            var chave = _ri_norm(mp);
            if (!mapa.hasOwnProperty(chave)) { continue; }
            achados[chave] = true;
            try {
                if (it.canProxy() && it.attachProxy(mapa[chave], 0)) {
                    anexados++;
                } else {
                    falhas++; falhados.push(it.name);
                }
            } catch (e2) {
                falhas++; falhados.push(it.name);
            }
        }
        var naoAchados = 0, k;
        for (k in mapa) {
            if (mapa.hasOwnProperty(k) && !achados[k]) { naoAchados++; }
        }
        var nivel = (falhas > 0 || (anexados < lista.length && estado.casados > 0)) ? "aviso:" : "ok:";
        if (estado.casados === 0 && lista.length > 0) { nivel = "aviso:"; }
        msgs.push(nivel + "Proxies anexados: " + anexados + " de " + lista.length + ".");
        if (naoAchados > 0) {
            msgs.push("aviso:" + naoAchados + " original(is) da lista n\u00e3o aparece(m) no projeto (n\u00e3o usados nas sequ\u00eancias).");
        }
        if (falhas > 0) {
            msgs.push("aviso:Falha ao anexar proxy em " + falhas + " clipe(s): " + falhados.slice(0, 10).join(", ")
                + ". Plano B: selecione a bin MATERIAL, Proxy > Anexar proxies, e aponte para a pasta PROXIES.");
        }

        // 4b. cartela do ano (Formatura): MOGRT preenchido com os dados da ficha
        if (job.cartela && job.cartela.mogrt) { _ri_cartela(job, msgs); }

        // 5. salvar e backup
        app.project.save();
        msgs.push("ok:Projeto salvo.");
        if (job.backup_dir) {
            var d = new Date();
            var base = decodeURI(new File(prproj).name).replace(/\.prproj$/i, "");
            var nome = base + " - backup " + d.getFullYear() + "-" + _ri_dois(d.getMonth() + 1) + "-" + _ri_dois(d.getDate())
                + " " + _ri_dois(d.getHours()) + "h" + _ri_dois(d.getMinutes()) + ".prproj";
            var destino = String(job.backup_dir).replace(/\\/g, "/").replace(/\/+$/, "") + "/" + nome;
            if (new File(prproj).copy(destino)) {
                msgs.push("ok:Backup copiado: " + destino);
            } else {
                msgs.push("aviso:N\u00e3o consegui copiar o backup para " + job.backup_dir + ".");
            }
        }
        return _ri_resumo(msgs, false);
    } catch (e) {
        msgs.push("erro:Erro inesperado: " + e);
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
