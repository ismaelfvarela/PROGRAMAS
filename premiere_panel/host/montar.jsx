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
