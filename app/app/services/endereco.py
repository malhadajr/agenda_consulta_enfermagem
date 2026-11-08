"""
Autocompletar de endereço via ViaCEP (com reserva na BrasilAPI).
Somente o CEP ou o nome da rua são enviados — nunca dados do paciente.
Qualquer falha devolve uma resposta amigável e os campos continuam editáveis à mão.
"""

import re
from typing import Any, Dict
from urllib.parse import quote

import httpx

from app.config import settings

_HEADERS = {"User-Agent": "NovaAgenda2027/2.0", "Accept": "application/json"}
_TIMEOUT = httpx.Timeout(4.0)
_MANUAL = {"ok": False, "manual_fallback": True}


def _get(url: str):
    with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=False) as c:
        r = c.get(url)
        if r.status_code != 200 or len(r.content) > 200_000:
            return None
        return r.json()


def buscar_cep(cep: str) -> Dict[str, Any]:
    digitos = re.sub(r"\D", "", cep or "")
    if len(digitos) != 8:
        return {**_MANUAL, "erro": "CEP deve conter 8 dígitos (ex.: 20230-092)."}
    if not settings.cep_online:
        return {**_MANUAL, "erro": "Consulta de CEP desativada. Preencha o endereço manualmente."}
    try:
        d = _get(f"https://viacep.com.br/ws/{digitos}/json/")
        if isinstance(d, dict) and d.get("erro"):
            return {**_MANUAL, "erro": "CEP não encontrado. Preencha os campos manualmente."}
        if isinstance(d, dict):
            return {"ok": True, "provedor": "ViaCEP", "cep": f"{digitos[:5]}-{digitos[5:]}",
                    "logradouro": str(d.get("logradouro") or "")[:200], "bairro": str(d.get("bairro") or "")[:120],
                    "cidade": str(d.get("localidade") or "")[:120], "uf": str(d.get("uf") or "")[:2].upper()}
    except Exception:
        pass
    try:
        d = _get(f"https://brasilapi.com.br/api/cep/v1/{digitos}")
        if isinstance(d, dict) and d.get("cep"):
            return {"ok": True, "provedor": "BrasilAPI", "cep": f"{digitos[:5]}-{digitos[5:]}",
                    "logradouro": str(d.get("street") or "")[:200], "bairro": str(d.get("neighborhood") or "")[:120],
                    "cidade": str(d.get("city") or "")[:120], "uf": str(d.get("state") or "")[:2].upper()}
    except Exception:
        pass
    return {**_MANUAL, "erro": "Serviço de CEP indisponível no momento. Preencha o endereço manualmente."}


def buscar_logradouro(uf: str, cidade: str, logradouro: str) -> Dict[str, Any]:
    uf = re.sub(r"[^A-Za-z]", "", uf or "").upper()[:2]
    cidade = (cidade or "").strip()[:80]
    rua = (logradouro or "").strip()[:80]
    if len(uf) != 2 or len(cidade) < 3 or len(rua) < 3:
        return {**_MANUAL, "resultados": [], "erro": "Informe UF, cidade e ao menos 3 letras do logradouro."}
    if not settings.cep_online:
        return {**_MANUAL, "resultados": [], "erro": "Consulta de endereço desativada."}
    try:
        d = _get(f"https://viacep.com.br/ws/{quote(uf)}/{quote(cidade)}/{quote(rua)}/json/")
        if isinstance(d, list):
            return {"ok": True, "provedor": "ViaCEP", "resultados": [
                {"cep": str(i.get("cep") or ""), "logradouro": str(i.get("logradouro") or ""),
                 "bairro": str(i.get("bairro") or ""), "cidade": str(i.get("localidade") or cidade),
                 "uf": str(i.get("uf") or uf)} for i in d[:10] if isinstance(i, dict)]}
    except Exception:
        pass
    return {**_MANUAL, "resultados": [], "erro": "Busca de endereço indisponível. Preencha manualmente."}
