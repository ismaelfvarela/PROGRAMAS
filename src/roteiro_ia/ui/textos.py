"""Textos da janela: nomes amigáveis das etapas e dos papéis das subpastas."""
from __future__ import annotations

from roteiro_ia.models import Role

STAGE_NAMES: dict[str, str] = {
    "inventario": "Inventário",
    "proxies": "Proxies 480p",
    "audio": "Áudio",
    "sync": "Sincronização",
    "transcricao": "Transcrição",
    "cenas": "Cenas",
    "estilo": "Estilo",
    "analise": "Análise com IA",
    "trilhas": "Trilhas",
    "roteiro": "Roteiro",
    "pdf": "PDF",
    "premiere": "Premiere",
}

ROLE_LABELS: dict[Role, str] = {
    Role.camera: "Câmera",
    Role.drone: "Drone",
    Role.pocket: "Pocket / celular",
    Role.audio_ambiente: "Áudio ambiente (gravador)",
    Role.mesa: "Mesa de som",
    Role.lapela_noivo: "Lapela do noivo",
    Role.lapela_noiva: "Lapela da noiva",
    Role.outro_dia: "Outro dia",
    Role.ignorar: "Ignorar",
}
_BY_LABEL = {v: k for k, v in ROLE_LABELS.items()}


def role_label(r: Role) -> str:
    return ROLE_LABELS[Role(r)]


def label_to_role(label: str) -> Role:
    try:
        return _BY_LABEL[label]
    except KeyError:
        raise ValueError(f"Papel desconhecido: '{label}'.") from None


PREMIERE_INSTRUCAO = "No Premiere: Janela → Extensões → Roteiro IA → Montar projeto"
