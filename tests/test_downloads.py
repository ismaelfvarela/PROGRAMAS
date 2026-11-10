import os
from datetime import datetime, timedelta

import pytest

from roteiro_ia.downloads import (DestinoInvalido, downloads_recentes, link_artlist, link_musicbed,
                                  link_youtube,
                                  nome_destino, pasta_do_mes, proximo_numero,
                                  trazer_para_biblioteca)

HOJE = datetime(2026, 11, 10, 9, 0)


def test_pasta_do_mes_usa_a_que_ja_existe_ou_o_padrao(tmp_path):
    (tmp_path / "2026" / "11- NOVEMBRO").mkdir(parents=True)  # grafia real do M: (sem espaço)
    assert pasta_do_mes(str(tmp_path), HOJE) == tmp_path / "2026" / "11- NOVEMBRO"
    assert pasta_do_mes(str(tmp_path), datetime(2026, 12, 1)) == tmp_path / "2026" / "12 - DEZEMBRO"
    assert pasta_do_mes(str(tmp_path), datetime(2027, 3, 5)) == tmp_path / "2027" / "03 - MARÇO"


def test_numeracao_segue_a_pasta(tmp_path):
    for n in ("01  - suspense.aac", "02 - Invasion.mp3", "09 - Christmas.mp3", "Sem numero.mp3",
              "Song.mp3 44100.pek"):
        (tmp_path / n).write_bytes(b"x")
    assert proximo_numero(tmp_path) == 10
    assert proximo_numero(tmp_path / "nao existe") == 1
    from pathlib import Path
    assert nome_destino(10, Path("Artist - Song.MP3")) == "10 - Artist - Song.mp3"
    assert nome_destino(3, Path("07 - Ja numerada.wav")) == "03 - Ja numerada.wav"


def test_traz_numerando_sem_sobrescrever(tmp_path):
    m = tmp_path / "M"
    mes = m / "2026" / "11- NOVEMBRO"
    mes.mkdir(parents=True)
    (mes / "Altered Images - Happy Birthday.mp3").write_bytes(b"antiga")
    (mes / "01 - Ja estava.mp3").write_bytes(b"antiga")
    (mes / "02 - Unbreakable Spirit.mp3").write_bytes(b"ocupado")  # nome que colidiria
    down = tmp_path / "Downloads"
    down.mkdir()
    a = down / "Unbreakable Spirit.mp3"
    b = down / "Send It.wav"
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    novos = trazer_para_biblioteca([a, b], str(m), HOJE)
    assert [n.name for n in novos] == ["03 - Unbreakable Spirit.mp3", "04 - Send It.wav"]
    assert novos[0].read_bytes() == b"A" and not a.exists() and not b.exists()
    assert (mes / "02 - Unbreakable Spirit.mp3").read_bytes() == b"ocupado"
    assert (mes / "Altered Images - Happy Birthday.mp3").read_bytes() == b"antiga"


def test_cria_a_pasta_do_mes_e_recusa_o_que_ja_esta_na_biblioteca(tmp_path):
    m = tmp_path / "M"
    (m / "2026").mkdir(parents=True)
    down = tmp_path / "Downloads"
    down.mkdir()
    f = down / "x.mp3"
    f.write_bytes(b"x")
    novos = trazer_para_biblioteca([f], str(m), datetime(2026, 12, 2))
    assert novos == [m / "2026" / "12 - DEZEMBRO" / "01 - x.mp3"]
    with pytest.raises(DestinoInvalido):
        trazer_para_biblioteca([novos[0]], str(m), datetime(2026, 12, 2))


def test_downloads_recentes(tmp_path):
    novo, velho, doc = tmp_path / "a.mp3", tmp_path / "b.wav", tmp_path / "c.pdf"
    for f in (novo, velho, doc):
        f.write_bytes(b"x")
    antigo = (HOJE - timedelta(days=30)).timestamp()
    os.utime(velho, (antigo, antigo))
    agora = HOJE.timestamp()
    os.utime(novo, (agora, agora))
    os.utime(doc, (agora, agora))
    assert downloads_recentes(tmp_path, agora=HOJE) == [novo]


def test_links():
    # formatos dos links reais mandados pelo editor
    assert link_artlist("trilha piano wedding") == (
        "https://artlist.io/royalty-free-music/search?terms=trilha+piano+wedding")
    assert link_musicbed("trilha wedding instrumental") == (
        "https://www.musicbed.com/sounds?search=trilha+wedding+instrumental")
    assert link_youtube("Perfect - Ed Sheeran") == (
        "https://www.youtube.com/results?search_query=Perfect+-+Ed+Sheeran")
