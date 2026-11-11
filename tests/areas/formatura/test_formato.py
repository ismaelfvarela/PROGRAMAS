from roteiro_ia.areas.formatura.formato import pasta_principal
from roteiro_ia.areas.formatura.funcoes import FuncaoFormatura as F
from roteiro_ia.models import MediaInfo


def _m(folder, dur):
    return MediaInfo.model_construct(folder=folder, duration_s=dur)


def test_camera_com_audio_principal_vem_primeiro():
    f = {"CAM A": F.camera_iso, "CAM B": F.camera_iso, "CENTRAL": F.camera_audio}
    assert pasta_principal(f, [_m("CAM A", 900), _m("CAM B", 900), _m("CENTRAL", 10)]) == "CENTRAL"


def test_cam_a_pelo_nome_mesmo_com_menos_tempo():
    f = {"DIA/CAM B": F.camera, "DIA/CAM A": F.camera, "DIA/H6": F.gravador}
    vs = [_m("DIA/CAM B", 900), _m("DIA/CAM A", 100), _m("DIA/H6", 5000)]
    assert pasta_principal(f, vs) == "DIA/CAM A"
    assert pasta_principal({"CAMERA 01": F.camera, "CAMERA 02": F.camera},
                           [_m("CAMERA 01", 1), _m("CAMERA 02", 9)]) == "CAMERA 01"


def test_sem_nome_vale_a_que_gravou_mais():
    f = {"SONY": F.camera, "CANON": F.camera, "DRONE": F.drone}
    assert pasta_principal(f, [_m("SONY", 100), _m("CANON", 300), _m("DRONE", 999)]) == "CANON"
    assert pasta_principal({"H6": F.gravador}, [_m("H6", 10)]) is None
    assert pasta_principal({"CAM B": F.camera}, [_m("CAM B", 10)]) == "CAM B"
