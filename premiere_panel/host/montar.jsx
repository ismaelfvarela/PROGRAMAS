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

function montarProjeto(job) {
    var msgs = [];
    try {
        if (!job || !job.prproj || !job.xml) {
            return "erro|Job inválido: faltam os campos prproj ou xml.";
        }
        var xmlFile = new File(job.xml);
        if (!xmlFile.exists) {
            return "erro|XML do Premiere não encontrado: " + job.xml;
        }

        // 1. pastas
        _ri_garantirPasta(_ri_pai(job.prproj));
        if (job.backup_dir) { _ri_garantirPasta(job.backup_dir); }
        if (job.export_dir) {
            if (_ri_garantirPasta(job.export_dir)) {
                msgs.push("Pasta de exportação pronta: " + job.export_dir);
            } else {
                msgs.push("Não consegui criar a pasta de exportação: " + job.export_dir);
            }
        }

        // 2. projeto novo (nunca sobrescreve)
        var criado = app.newProject(job.prproj);
        if (criado === false) {
            return "erro|O Premiere não conseguiu criar o projeto em " + job.prproj + ". Nada foi alterado.";
        }
        msgs.push("Projeto criado: " + job.prproj);

        // 3. importar XML
        var imp = app.project.importFiles([job.xml], true, app.project.rootItem, false);
        if (imp === false) {
            return "erro|Falha ao importar o XML: " + job.xml;
        }
        msgs.push("XML importado (sequências por episódio).");

        // 4. proxies
        var mapa = {};
        var lista = job.proxies || [];
        var i;
        for (i = 0; i < lista.length; i++) {
            mapa[_ri_norm(lista[i].original)] = lista[i].proxy;
        }
        var itens = [];
        _ri_coletar(app.project.rootItem, itens);
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
        msgs.push("Proxies anexados: " + anexados + " de " + lista.length + ".");
        if (naoAchados > 0) {
            msgs.push(naoAchados + " original(is) da lista não aparece(m) no projeto (não usados nas sequências).");
        }
        if (falhas > 0) {
            msgs.push("Falha ao anexar proxy em " + falhas + " clipe(s): " + falhados.slice(0, 10).join(", ")
                + ". Plano B: selecione a bin MATERIAL, Proxy > Anexar proxies, e aponte para a pasta PROXIES.");
        }

        // 5. salvar e backup
        app.project.save();
        msgs.push("Projeto salvo.");
        if (job.backup_dir) {
            var d = new Date();
            var base = decodeURI(new File(job.prproj).name).replace(/\.prproj$/i, "");
            var nome = base + " - backup " + d.getFullYear() + "-" + _ri_dois(d.getMonth() + 1) + "-" + _ri_dois(d.getDate())
                + " " + _ri_dois(d.getHours()) + "h" + _ri_dois(d.getMinutes()) + ".prproj";
            var destino = String(job.backup_dir).replace(/\\/g, "/").replace(/\/+$/, "") + "/" + nome;
            if (new File(job.prproj).copy(destino)) {
                msgs.push("Backup copiado: " + destino);
            } else {
                msgs.push("Não consegui copiar o backup para " + job.backup_dir + ".");
            }
        }
        return "ok|" + msgs.join("\n");
    } catch (e) {
        msgs.push("Erro inesperado: " + e);
        return "erro|" + msgs.join("\n");
    }
}
