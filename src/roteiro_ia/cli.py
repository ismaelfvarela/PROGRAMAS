"""Linha de comando do Roteiro IA (roteiro-ia ...)."""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from roteiro_ia.config import DEFAULT_CONFIG_PATH, Settings, load_settings
from roteiro_ia.gemini.client import QuotaPaused
from roteiro_ia.inventory import list_subfolders, suggest_role
from roteiro_ia.models import FolderAssignment, Role
from roteiro_ia.paths import build_event_paths
from roteiro_ia.pipeline import PROJECT_FILE, Pipeline, ProjectRequest
from roteiro_ia.script.generate import DERIVADOS

EXIT_OK, EXIT_ERRO, EXIT_PAUSADO = 0, 1, 2
_ROLES = ", ".join(r.value for r in Role)


class CliError(Exception):
    pass


def _print_event(stage: str, msg: str, frac: float) -> None:
    print(f"[{stage}] {msg}", flush=True)


def _parse_papeis(items: list[str]) -> dict[str, Role]:
    out: dict[str, Role] = {}
    for it in items:
        folder, sep, role = it.rpartition("=")
        if not sep or not folder:
            raise CliError(f"Use --papel PASTA=papel (recebido: '{it}').")
        try:
            out[folder] = Role(role.strip())
        except ValueError:
            raise CliError(f"Papel inválido '{role}' para a pasta '{folder}'. Papéis: {_ROLES}.") from None
    return out


def _ask_role(folder: str, sug: Role) -> Role:
    while True:
        ans = input(f"  {folder} [{sug.value}]: ").strip()
        if not ans:
            return sug
        try:
            return Role(ans)
        except ValueError:
            print(f"  Papel inválido. Use um destes: {_ROLES}.")


def _assignments(src: Path, papeis: list[str]) -> list[FolderAssignment]:
    folders = list_subfolders(src)
    if not folders:
        raise CliError(f"A pasta '{src}' não tem subpastas de mídia.")
    given = _parse_papeis(papeis)
    unknown = sorted(set(given) - set(folders))
    if unknown:
        raise CliError(f"Subpasta(s) não encontrada(s) em '{src}': {', '.join(unknown)}.")
    out = []
    if not given:
        print(f"Confirme o papel de cada subpasta (Enter aceita a sugestão). Papéis: {_ROLES}.")
    for f in folders:
        sug = suggest_role(f)
        if given:
            role = given.get(f, sug)
            print(f"  {f}: {role.value}")
        else:
            role = _ask_role(f, sug)
        out.append(FolderAssignment(folder=f, role=role))
    return out


def _approve(req: ProjectRequest, cost: float, yes: bool) -> bool:
    if req.gemini_mode != "pago":
        return True
    print(f"Modo pago do Gemini: custo estimado da análise US$ {cost:.2f}.")
    if yes:
        return True
    return input("Confirmar o uso do modo pago? [s/N] ").strip().lower() in ("s", "sim")


def _finish(pipe, result: str, src: Path) -> int:
    if result == "pausado":
        when = pipe.resume_at.astimezone().strftime("%d/%m/%Y %H:%M") if pipe.resume_at else "?"
        print(f"Pausado: a cota gratuita do Gemini acabou. Retome a partir de {when} com:\n"
              f"  roteiro-ia continuar \"{src}\"")
        return EXIT_PAUSADO
    print("Concluído. PDF do roteiro e XML do Premiere gerados.")
    return EXIT_OK


def _paths_and_request(src: Path, s: Settings, disco: str | None) -> ProjectRequest:
    p = build_event_paths(src, s, disco)
    f = Path(p.analysis_dir) / PROJECT_FILE
    if not f.is_file():
        raise CliError(f"Projeto não encontrado ({f}). Comece com: roteiro-ia novo \"{src}\"")
    return ProjectRequest.load(f)


def _cmd_novo(a, s: Settings, cfg: Path) -> int:
    src = Path(a.pasta)
    if not src.is_dir():
        raise CliError(f"A pasta '{src}' não existe ou não está acessível.")
    derivados = set(DERIVADOS)
    for flag, d in ((a.sem_trailer, "trailer"), (a.sem_teaser, "teaser"), (a.sem_stories, "stories")):
        if flag:
            derivados.discard(d)
    req = ProjectRequest(source_dir=src, work_drive=a.disco or s.work_drive,
                         assignments=_assignments(src, a.papel), n_episodios=a.episodios,
                         derivados=derivados, gemini_mode=a.modo or s.gemini_mode)
    pipe = Pipeline(req, s, None, None, _print_event, settings_path=cfg)
    try:
        _paths, cost = pipe.prepare()
        if not _approve(req, cost, a.sim):
            print("Cancelado. Use 'roteiro-ia continuar' quando quiser retomar.")
            return EXIT_ERRO
        return _finish(pipe, pipe.run(aprovado_custo=True), src)
    finally:
        pipe.close()


def _cmd_continuar(a, s: Settings, cfg: Path) -> int:
    src = Path(a.pasta)
    req = _paths_and_request(src, s, a.disco)
    pipe = Pipeline(req, s, None, None, _print_event, settings_path=cfg)
    try:
        cost = pipe.estimate_cost() if req.gemini_mode == "pago" else 0.0
        if not _approve(req, cost, a.sim):
            print("Cancelado.")
            return EXIT_ERRO
        return _finish(pipe, pipe.run(aprovado_custo=True), src)
    finally:
        pipe.close()


def _cmd_ajustar(a, s: Settings, cfg: Path) -> int:
    src = Path(a.pasta)
    req = _paths_and_request(src, s, a.disco)
    pipe = Pipeline(req, s, None, None, _print_event, settings_path=cfg)
    try:
        if req.gemini_mode == "pago" and not a.sim and input(
                "O ajuste usa o Gemini no modo pago. Confirmar? [s/N] ").strip().lower() not in ("s", "sim"):
            print("Cancelado.")
            return EXIT_ERRO
        try:
            pipe.revise(a.pedido, aprovado_custo=True)
        except QuotaPaused:
            print(f"Pausado: a cota gratuita do Gemini acabou. Tente o ajuste a partir de "
                  f"{pipe.resume_at.astimezone():%d/%m/%Y %H:%M}.")
            return EXIT_PAUSADO
    finally:
        pipe.close()
    print("Roteiro ajustado: PDF e XML do Premiere atualizados.")
    return EXIT_OK


def _cmd_trilhas(a, s: Settings, cfg: Path) -> int:
    from roteiro_ia.music_index import MusicIndex, update_index
    with MusicIndex(Path(s.system_dir) / "trilhas.db", s) as idx:
        n = update_index(s, idx, on_progress=lambda i, t, name: print(f"  {i}/{t} {name}", flush=True))
        print(f"Índice de trilhas atualizado: {n} analisadas, {len(idx.all())} no total.")
    return EXIT_OK


def _cmd_estilo(a, s: Settings, cfg: Path) -> int:
    from roteiro_ia.gemini.client import GeminiClient
    from roteiro_ia.gemini.style import build_style_profile
    if not s.style_urls:
        raise CliError("Nenhum link de vídeo de referência configurado (style_urls).")
    prof = build_style_profile(GeminiClient(s), s)
    print(f"Perfil de estilo atualizado: {prof.resumo}")
    return EXIT_OK


def _cmd_chave(a, s: Settings, cfg: Path) -> int:
    from roteiro_ia.gemini.client import PRIVACY_NOTICE_PT, set_api_key
    print(PRIVACY_NOTICE_PT)
    key = getpass.getpass("Chave de API do Gemini (não aparece ao digitar): ").strip()
    if not key:
        raise CliError("Nenhuma chave informada.")
    set_api_key(key)
    print("Chave do Gemini gravada no cofre de credenciais do Windows.")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="roteiro-ia",
                                 description="Pré-roteiro de casamentos com IA (Fokuss).")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG_PATH),
                    help="arquivo de configuração (padrão: %(default)s)")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="comando")

    n = sub.add_parser("novo", help="processa um evento novo")
    n.add_argument("pasta", help="pasta do evento no R: (ex.: 'R:\\2023-01-01 NOIVA E NOIVO')")
    n.add_argument("--disco", help="disco de trabalho (padrão: o da configuração, ex.: Y:)")
    n.add_argument("--episodios", type=int, help="número de episódios (padrão: a IA decide)")
    n.add_argument("--sem-trailer", action="store_true", help="não gerar trailer")
    n.add_argument("--sem-teaser", action="store_true", help="não gerar teaser")
    n.add_argument("--sem-stories", action="store_true", help="não gerar stories")
    n.add_argument("--papel", action="append", default=[], metavar="PASTA=papel",
                   help=f"papel de uma subpasta, sem perguntar (repetível). Papéis: {_ROLES}")
    n.add_argument("--modo", choices=["gratis", "pago"], help="modo do Gemini nesta execução")
    n.add_argument("--sim", action="store_true", help="aprova o custo do modo pago sem perguntar")

    c = sub.add_parser("continuar", help="retoma um evento pausado ou interrompido")
    c.add_argument("pasta", help="pasta do evento no R:")
    c.add_argument("--disco", help="disco de trabalho usado no 'novo'")
    c.add_argument("--sim", action="store_true", help="aprova o custo do modo pago sem perguntar")

    j = sub.add_parser("ajustar", help="regera o roteiro com um pedido de ajuste")
    j.add_argument("pasta", help="pasta do evento no R:")
    j.add_argument("pedido", help="o que mudar, entre aspas")
    j.add_argument("--disco", help="disco de trabalho usado no 'novo'")
    j.add_argument("--sim", action="store_true", help="aprova o custo do modo pago sem perguntar")

    sub.add_parser("trilhas", help="atualiza o índice da biblioteca de trilhas")
    sub.add_parser("estilo", help="(re)cria o perfil de estilo a partir dos vídeos de referência")
    sub.add_parser("chave", help="grava a chave de API do Gemini")
    return ap


_CMDS = {"novo": _cmd_novo, "continuar": _cmd_continuar, "ajustar": _cmd_ajustar,
         "trilhas": _cmd_trilhas, "estilo": _cmd_estilo, "chave": _cmd_chave}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # console cp850/cp1252: não quebra com acentos
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    a = build_parser().parse_args(argv)
    cfg = Path(a.config)
    try:
        s = load_settings(cfg)
        return _CMDS[a.cmd](a, s, cfg)
    except KeyboardInterrupt:
        print("\nInterrompido. Use 'roteiro-ia continuar' para retomar.", file=sys.stderr)
        return EXIT_ERRO
    except Exception as e:  # noqa: BLE001 - mensagem amigável no terminal
        print(f"Erro: {e}", file=sys.stderr)
        return EXIT_ERRO


if __name__ == "__main__":
    sys.exit(main())
