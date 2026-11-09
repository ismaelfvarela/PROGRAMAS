"""Estudo de estilo da Formatura: prompts próprios e cache separado (estilo_cache/formatura/)."""
from __future__ import annotations

from roteiro_ia.gemini import style

PROMPT_VIDEO = (
    "Assista a este vídeo de formatura publicado pela Fokuss (clipe de oficina, feira, prova de "
    "toga, escolha do paraninfo, abertura ou encerramento da colação de grau, ou íntegra da "
    "cerimônia) e descreva de forma técnica e objetiva o ESTILO DE EDIÇÃO, sem descrever as "
    "pessoas. Informe: tipo (use 'episodio' para um clipe, 'trailer' para abertura ou "
    "encerramento da colação, 'outro' para o resto); duração total em segundos; ritmo médio de "
    "corte em segundos por plano; como o vídeo abre (cartela com dados do evento, logos, "
    "vinhetas); como fecha (no campo gancho); uso de falas e depoimentos dos alunos e como "
    "entram; trilha musical e energia; tratamento de cor; e observações relevantes de montagem. "
    "Responda em português."
)
PROMPT_AGG = (
    "A seguir estão anotações técnicas de edição de vários vídeos de formatura da Fokuss, em "
    "JSON. Consolide-as em um perfil de estilo reutilizável para guiar roteiros de clipes de "
    "formatura: duração média dos clipes (campo de episódio), ritmo médio de corte, padrões de "
    "abertura e cartela, padrões de fechamento (campo de gancho), uso de falas reais, trilhas, "
    "cor, estrutura de abertura e encerramento da colação (campo de teaser/trailer) e um resumo "
    "curto. Seja objetivo e técnico, em português. Anotações:\n"
)

style.registrar_area("formatura", PROMPT_VIDEO, PROMPT_AGG)
