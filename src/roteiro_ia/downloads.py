"""Músicas a baixar (Artlist e afins): links de busca para cada peça do roteiro e a chegada dos
downloads à biblioteca, no padrão da Fokuss: M:\\<ANO>\\<MM - MÊS>\\NN - <nome>.<ext>, com NN
seguindo a numeração que já existe na pasta do mês.

ÚNICA escrita do sistema no M: (protegido): cria a pasta do ano/mês se faltar e arquivos NOVOS.
Nunca sobrescreve nem apaga nada que já esteja lá."""
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

MESES = ["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO",
         "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]
AUDIO_EXTS = {".mp3", ".wav", ".aif", ".aiff", ".m4a", ".aac", ".flac", ".ogg"}
# buscas por texto dos sites ({q} = termos, espaços como "+"), conforme links reais do editor
ARTLIST_BUSCA = "https://artlist.io/royalty-free-music/search?terms={q}"
MUSICBED_BUSCA = "https://www.musicbed.com/sounds?search={q}"
YOUTUBE_BUSCA = "https://www.youtube.com/results?search_query={q}"
DOWNLOADS_DIAS = 7  # downloads mais antigos que isso não aparecem na lista
_NUM = re.compile(r"^\s*(\d{1,3})\s*-")


class DestinoInvalido(ValueError):
    pass


def link_artlist(termos: str) -> str:
    return ARTLIST_BUSCA.format(q=quote_plus(termos.strip()))


def link_musicbed(termos: str) -> str:
    return MUSICBED_BUSCA.format(q=quote_plus(termos.strip()))


def link_youtube(busca: str) -> str:
    return YOUTUBE_BUSCA.format(q=quote_plus(busca.strip()))


def _raiz(music_root: str) -> Path:
    r = music_root.strip()
    return Path(r + "\\") if len(r) == 2 and r[1] == ":" else Path(r)


def pasta_do_mes(music_root: str, hoje: datetime | None = None) -> Path:
    """M:\\<ANO>\\<pasta do mês>: a que já existe com o número do mês (aceita "11- NOVEMBRO"
    e "11 - NOVEMBRO"); se não existir, o nome padrão "MM - MÊS"."""
    hoje = hoje or datetime.now()
    ano = _raiz(music_root) / str(hoje.year)
    try:
        for d in sorted(ano.iterdir()):
            m = _NUM.match(d.name)
            if d.is_dir() and m and int(m.group(1)) == hoje.month:
                return d
    except OSError:
        pass
    return ano / f"{hoje.month:02d} - {MESES[hoje.month - 1]}"


def proximo_numero(pasta: Path) -> int:
    """Depois do maior número já usado na pasta (1 se não houver nenhum)."""
    maior = 0
    try:
        for f in pasta.iterdir():
            m = _NUM.match(f.name)
            if m:
                maior = max(maior, int(m.group(1)))
    except OSError:
        pass
    return maior + 1


def nome_destino(n: int, original: Path) -> str:
    """"NN - <nome da música>.<ext>" (tira uma numeração que já venha no nome baixado)."""
    stem = _NUM.sub("", original.stem).strip() or original.stem
    return f"{n:02d} - {stem}{original.suffix.lower()}"


def pasta_downloads() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads"


def downloads_recentes(pasta: Path, dias: int = DOWNLOADS_DIAS,
                       agora: datetime | None = None) -> list[Path]:
    """Áudios da pasta de downloads dos últimos `dias`, do mais recente para o mais antigo."""
    limite = (agora or datetime.now()) - timedelta(days=dias)
    out = []
    try:
        for f in pasta.iterdir():
            if f.is_file() and f.suffix.lower() in AUDIO_EXTS:
                quando = datetime.fromtimestamp(f.stat().st_mtime)
                if quando >= limite:
                    out.append((quando, f))
    except OSError:
        return []
    return [f for _q, f in sorted(out, reverse=True)]


def _dentro(filho: Path, pai: Path) -> bool:
    a = os.path.normcase(os.path.abspath(filho))
    b = os.path.normcase(os.path.abspath(pai)).rstrip("\\/")
    return a.startswith(b + os.sep)


def trazer_para_biblioteca(arquivos: list[Path], music_root: str,
                           hoje: datetime | None = None) -> list[Path]:
    """Move cada download para a pasta do mês no M:, numerado na sequência e com o nome da
    música. Cria a pasta do ano/mês se faltar; nunca sobrescreve (o número sobe até achar um
    nome livre). Devolve os caminhos novos, na ordem dada."""
    raiz = _raiz(music_root)
    destino = pasta_do_mes(music_root, hoje)
    if not _dentro(destino, raiz):
        raise DestinoInvalido(f"Pasta de destino fora da biblioteca de músicas: {destino}")
    for a in arquivos:
        if _dentro(Path(a), raiz):
            raise DestinoInvalido(f"Esta música já está na biblioteca: {a}")
    destino.mkdir(parents=True, exist_ok=True)
    novos = []
    n = proximo_numero(destino)
    for a in arquivos:
        a = Path(a)
        alvo = destino / nome_destino(n, a)
        while alvo.exists():  # nunca por cima de nada
            n += 1
            alvo = destino / nome_destino(n, a)
        shutil.move(str(a), str(alvo))
        novos.append(alvo)
        n += 1
    return novos
