"""Momentos de uma formatura (do briefing); a etapa seguinte usa na análise."""
from __future__ import annotations

MOMENTOS_FORMATURA: list[str] = [
    "Oficina",
    "Prova de toga",
    "Escolha do paraninfo",
    "Decoração",
    "Bastidores",
    "Abertura do mestre de cerimônias e entrada dos professores",
    "Entrada das turmas",
    "Hino Nacional",
    "Fala do diretor ou representante",
    "Colação de grau",
    "Oradores",
    "Paraninfos",
    "Homenagens",
    "Hino e encerramento",
]

# Momentos por tipo de trabalho (aprovados no desenho 2.1, seção 3); a análise do Gemini usa a
# lista do tipo do projeto. Todas terminam em "extra" (momento fora da lista).
MOMENTOS_POR_TIPO: dict[str, list[str]] = {
    "oficina": ["chegada e ambiente", "alunos trabalhando", "detalhes (mãos, ferramentas, peças)",
                "professor ensinando", "depoimento", "interação e risadas", "turma reunida",
                "momento final", "extra"],
    "feira": ["visão geral da feira", "estande ou projeto", "aluno explicando o projeto",
              "demonstração funcionando", "visitantes", "equipe reunida", "extra"],
    "prova_toga": ["vestindo a beca", "ajudando o colega", "espelho e detalhes", "reações",
                   "fotos em grupo", "falas", "extra"],
    "paraninfo": ["anúncio", "reação do escolhido", "falas", "turma reunida", "extra"],
    "colacao": ["decoração", "bastidores",
                "abertura do mestre de cerimônias e entrada dos professores", "entrada das turmas",
                "hino nacional", "fala do diretor ou representante", "colação de grau",
                "oradores", "paraninfos", "homenagens", "fala do diretor", "hino e encerramento",
                "plateia e família", "emoção", "beca jogada", "comemoração", "extra"],
}

PROBLEMAS_TECNICOS = ["chicote", "desfocado", "mal enquadrado", "tremido", "escuro"]
