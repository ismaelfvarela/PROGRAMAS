"""Relatório da íntegra (vira o PDF da colação): partes, horários, cortes, trocas e avisos."""
from __future__ import annotations

from collections import Counter
from html import escape

from roteiro_ia.areas.formatura.colacao.plano import PlanoIntegra
from roteiro_ia.areas.formatura.colacao.xml_integra import nome_sequencia


def _hms(t: float) -> str:
    t = int(round(t))
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


def render_relatorio(plano: PlanoIntegra, evento: str) -> str:
    linhas = []
    for p in plano.partes:
        dur = sum(b - a for a, b in p.trechos)
        cortado = sum(b - a for a, b in p.cortes)
        fontes = Counter("ISO" if t.fonte.startswith("iso:") else "imagem fria"
                         if t.fonte.startswith("fria:") else "sem cobertura" for t in p.trocas)
        trocas = ", ".join(f"{n} {k}" for k, n in fontes.items()) or "nenhuma"
        linhas.append(
            f"<tr><td>{escape(nome_sequencia(p))}</td><td>{_hms(p.inicio_s)}</td>"
            f"<td>{_hms(dur)}</td><td>{_hms(cortado)}</td><td>{escape(trocas)}</td></tr>")
    alertas = "".join(f"<li>{escape(a)}</li>" for a in plano.alertas) or "<li>Nenhum.</li>"
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Íntegra — {escape(evento)}</title>
<style>
body {{ font-family: 'Segoe UI', sans-serif; font-size: 11pt; color: #222; margin: 28px; }}
h1 {{ font-size: 18pt; margin: 0 0 4px; }} .sub {{ color: #666; margin-bottom: 18px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 1px solid #ddd; padding: 6px 8px; text-align: left; }}
th {{ background: #f2f2f2; }} h2 {{ font-size: 13pt; margin-top: 22px; }}
</style></head><body>
<h1>Íntegra da colação</h1>
<div class="sub">{escape(evento)} · uma sequência por parte no Premiere; cada troca e corte tem um
marcador. Confira os marcadores e use "Pedir ajuste" se uma parte começou no lugar errado.</div>
<table><tr><th>Sequência (nome de entrega)</th><th>Começa na mesa</th><th>Duração final</th>
<th>Espaço morto cortado</th><th>Trocas de imagem</th></tr>
{''.join(linhas)}
</table>
<h2>Avisos</h2><ul>{alertas}</ul>
</body></html>"""
