"""Contexto do pré-roteiro de um clipe de formatura (usado no lugar do texto do Casamento)."""
from __future__ import annotations

import os
from typing import Callable

from roteiro_ia.areas.formatura.cadastro import Formatura
from roteiro_ia.areas.formatura.projeto import ProjetoFormatura
from roteiro_ia.areas.formatura.tipos import INFO_TIPO, TipoTrabalho
from roteiro_ia.script.generate import _FORMATO, _style_text, build_catalog, music_shortlist

_POR_TIPO = {
    TipoTrabalho.oficina: (
        "O clipe mostra os alunos trabalhando na oficina ou sala de aula, com alguns depoimentos "
        "(as falas reais dos alunos são o ponto alto)."),
    TipoTrabalho.feira: (
        "O vídeo é documental: mostra os projetos expostos na feira e é guiado pelas falas dos "
        "alunos explicando o trabalho; a música fica por baixo das falas."),
    TipoTrabalho.prova_toga: (
        "O clipe tem trilha e só os áudios de assuntos importantes (falas marcantes); o resto é "
        "montagem no ritmo da música."),
    TipoTrabalho.paraninfo: (
        "O clipe tem trilha e só os áudios de assuntos importantes (o anúncio, a reação, falas "
        "marcantes); o resto é montagem no ritmo da música."),
}


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(str(p).replace("/", "\\")))


class IndiceSem:
    """Visão do índice sem as trilhas de `excluir`; o resto delega para o índice original."""

    def __init__(self, idx, excluir: set[str]):
        self._idx = idx
        self._fora = {_norm(p) for p in excluir}

    def all(self):
        return [t for t in self._idx.all() if _norm(t.path) not in self._fora]

    def __getattr__(self, nome):
        return getattr(self._idx, nome)


def _titulo(pf: ProjetoFormatura) -> str:
    partes = " ".join(p for p in (pf.curso, pf.turma) if p)
    return f"{INFO_TIPO[pf.tipo].nome} — {partes}" if partes else INFO_TIPO[pf.tipo].nome


def _dados(pf: ProjetoFormatura, ficha: Formatura | None) -> str:
    linhas = []
    if ficha is not None:
        linhas += [f"- instituição: {ficha.instituicao}", f"- formatura: {ficha.ano}/{ficha.semestre}"]
    if pf.curso:
        linhas.append(f"- curso: {pf.curso}")
    if pf.turma:
        linhas.append(f"- turma: {pf.turma}")
    return "\n".join(linhas) or "- (sem dados cadastrados)"


def contexto_clipe(pf: ProjetoFormatura, ficha: Formatura | None,
                   ideia_json: str | None) -> Callable[..., str]:
    """Função com a assinatura de generate._context para o clipe deste projeto."""
    info = INFO_TIPO[pf.tipo]
    dur_s = round((pf.duracao_min or info.duracao_min or 4) * 60)

    def ctx(db, idx, style, n_episodios, derivados, compact: bool = False) -> str:
        regras = f"""Regras de edição da Fokuss para clipes de formatura (siga todas):
1. UMA peça só: tipo "episodio", numero 1, gancho null e gancho_resolve_em null. Título: "{_titulo(pf)}". Nada de série, episódios ou ganchos.
2. Duração: cerca de {dur_s} s; pode passar um pouco se o conteúdo pedir.
3. Abertura: os primeiros segundos ficam reservados para a cartela com os dados do evento (abaixo); a cena de abertura é o fundo da cartela — escolha uma imagem bonita e estável.
4. Qualidade de imagem: nada de chicote, imagem desfocada ou cena mal enquadrada fotograficamente. O assunto vale mais que a técnica: se um momento importante só existe numa imagem imperfeita, ele entra pelo menor tempo possível e você registra um alerta.
5. Música comercial, popular e o mais moderna possível (público jovem): dê 2–3 opções da biblioteca (só as da lista abaixo) e também sugestões pelo nome com origem "popular" (o editor confere se ainda estão em alta). Cortes no compasso da música: padrao_corte "1-3" (tempos 1 e 3) ou "2-4" (tempos 2 e 4); nunca "misto".
6. {_POR_TIPO.get(pf.tipo, "")}
7. Fala dos alunos: use as falas verdadeiras (veja 'falas' no catálogo), sempre a FRASE INTEIRA (start_s/end_s cobrindo do começo ao fim da frase, sem cortar no meio), e coloque a fala em 'fala'. Na montagem o aluno aparece falando no começo e no fim da fala e, no meio, as cenas SEM fala que vêm logo depois dela no roteiro cobrem a imagem enquanto a voz continua por baixo: depois de cada fala, coloque 2–4 cenas de cobertura do mesmo assunto. Mídias [só áudio] servem só como 'fala' sobre uma cena de vídeo do mesmo momento.
8. Montagem profissional e lisa: cada cena entre 1,5 e 4 s (os cortes serão alinhados à batida da música automaticamente); use os pontos bons de entrada e saída do catálogo ('bons:'); nunca comece nem termine uma cena com a câmera ainda se movendo (o plano precisa terminar o enquadramento); nada de chicote, imagem desfocada ou tremida; lembranca sempre false (clipe não tem flashback)."""
        partes = [
            "Você é o roteirista da produtora Fokuss e vai escrever o PRÉ-ROTEIRO de um clipe de "
            f"formatura: {info.nome}.",
            "Dados do evento (vão na cartela de abertura):", _dados(pf, ficha), "",
            regras, "", _FORMATO,
        ]
        if style is not None:
            partes += ["", _style_text(style)]
        trilhas = music_shortlist(idx)
        partes += [
            "", "CATÁLOGO DO MATERIAL (rel_path | início–fim do segmento | dia | momento | emoção | "
            "qualidade | descrição | falas | gancho):",
            build_catalog(db, compact=compact) or "(vazio)",
            "", "TRILHAS DA BIBLIOTECA (path | BPM | perfil | duração | instrumental ou cantada | "
            "clima | instrumentos | tipo de voz | intro instrumental | tonalidade):",
            trilhas or "(nenhuma trilha disponível; sugira só pelo nome, com origem \"popular\")",
        ]
        if ideia_json:
            partes += [
                "", "IDEIA DA ORIGINAL (roteiro aprovado de outra turma, em JSON): mantenha os "
                "mesmos assuntos e a ordem dos blocos, mas use OUTRA música; o ritmo e a escolha "
                "das cenas seguem a trilha nova e o sentimento dela.",
                ideia_json,
            ]
        return "\n".join(partes)
    return ctx
