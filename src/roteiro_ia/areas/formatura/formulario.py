"""Formulário da Formatura: prepara o evento, mas ainda não processa."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QWidget

from roteiro_ia.areas.base import Area
from roteiro_ia.config import Settings
from roteiro_ia.ui.formulario import FormularioEvento
from roteiro_ia.ui.worker import Runner

AVISO_FORMATURA = "A Formatura chega na próxima etapa."


class FormularioFormatura(FormularioEvento):
    def __init__(self, s: Settings, runner: Runner, parent: QWidget | None = None,
                 area: str = "formatura"):
        super().__init__(s, runner, parent, area)
        self.card_entregas.hide()  # episódios/trailer… são do Casamento
        self.btn_iniciar.setToolTip(AVISO_FORMATURA)
        self.lbl_aviso = QLabel(AVISO_FORMATURA)
        self.lbl_aviso.setProperty("muted", True)
        self.layout().addWidget(self.lbl_aviso)

    def _atualizar_iniciar(self) -> None:
        self.btn_iniciar.setEnabled(False)


FORMATURA = Area("formatura", "Formatura", FormularioFormatura, pode_iniciar=False,
                 aviso_iniciar=AVISO_FORMATURA)
