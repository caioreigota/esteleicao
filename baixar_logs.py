"""
Baixa os "Arquivos transmitidos para totalização" do TSE (um zip por UF com
.bu, .imgbu, .logjez, .rdv e .vscmr de cada seção), lê os logs das urnas e
gera, por seção, métricas do horário dos votos.

Os arquivos são GRANDES (de centenas de MB a dezenas de GB por UF, pois incluem
imagens dos boletins). Comece por um estado pequeno:

    python baixar_logs.py --ufs AC              # testa com o Acre
    python baixar_logs.py --ufs SP RJ MG        # alguns estados
    python baixar_logs.py                       # todas as UFs (muito demorado)
    python baixar_logs.py --ufs SP --apagar-zip # apaga o zip depois de processar
    python baixar_logs.py --zip ~/Downloads/bu_imgbu_logjez_rdv_vscmr_2026_1t_AC.zip

O download é retomado de onde parou se for interrompido (rode de novo).
Resultado: dados/logs_<ano>_t<turno>_<UF>.parquet  (o painel lê automaticamente)

Fonte: https://dadosabertos.tse.jus.br/dataset/resultados-2026-arquivos-transmitidos-para-totalizacao
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import time
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, as_completed, wait
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from logs_urna import ABERTURA, EXT_LOG, estimar_fuso, metricas, processar_logjez

URL = ("https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{ano}/arqurnatot/"
       "bu_imgbu_logjez_rdv_vscmr_{ano}_{turno}t_{uf}.zip")
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
       "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO", "ZZ"]
PASTA = Path(__file__).parent / "dados"


# ------------------------------------------------------------------ download
def baixar(url: str, destino: Path) -> Path:
    if destino.exists():
        print(f"  zip já baixado: {destino.name}")
        return destino
    parcial = destino.with_suffix(".zip.part")
    ja = parcial.stat().st_size if parcial.exists() else 0
    cab = {"User-Agent": "Mozilla/5.0 (analise-horario-votacao)"}
    if ja:
        cab["Range"] = f"bytes={ja}-"
        print(f"  retomando download a partir de {ja / 1e6:,.0f} MB")
    with requests.get(url, stream=True, timeout=60, headers=cab) as r:
        if r.status_code == 404:
            raise FileNotFoundError(f"não publicado (404): {url}")
        r.raise_for_status()
        if ja and r.status_code != 206:  # servidor ignorou o Range: recomeça
            ja = 0
        total = ja + int(r.headers.get("Content-Length", 0))
        modo = "ab" if ja else "wb"
        feito, t0 = ja, time.time()
        with open(parcial, modo) as f:
            for bloco in r.iter_content(chunk_size=4 << 20):
                f.write(bloco)
                feito += len(bloco)
                vel = (feito - ja) / max(time.time() - t0, 1e-6) / 1e6
                print(f"\r  {feito / 1e6:,.0f} / {total / 1e6:,.0f} MB  ({vel:,.1f} MB/s)   ",
                      end="", flush=True)
    print()
    parcial.rename(destino)
    return destino


# ------------------------------------------------------------------ leitura do zip
def iterar_logjez(zf: zipfile.ZipFile, prefixo: str = ""):
    """Percorre o zip (e zips dentro dele) devolvendo (nome, bytes) de cada log de urna."""
    for info in zf.infolist():
        nome = info.filename.lower()
        if nome.endswith(EXT_LOG):
            yield prefixo + info.filename, zf.read(info)
        elif nome.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(zf.read(info))) as interno:
                yield from iterar_logjez(interno, prefixo + info.filename + "/")


def _tarefa(lote):
    return [processar_logjez(nome, dados) for nome, dados in lote]


def _em_paralelo(itens, processos: int, tam_lote: int = 32):
    """Processa em paralelo com memória limitada (no máximo ~4 lotes por processo em voo)."""
    def lotes():
        lote = []
        for item in itens:
            lote.append(item)
            if len(lote) == tam_lote:
                yield lote
                lote = []
        if lote:
            yield lote

    if processos <= 1:
        for lote in lotes():
            yield from _tarefa(lote)
        return
    with ProcessPoolExecutor(max_workers=processos) as ex:
        pendentes = set()
        for lote in lotes():
            pendentes.add(ex.submit(_tarefa, lote))
            if len(pendentes) >= processos * 4:
                prontos, pendentes = wait(pendentes, return_when=FIRST_COMPLETED)
                for f in prontos:
                    yield from f.result()
        for f in as_completed(pendentes):
            yield from f.result()


def processar_zip(caminho: Path, uf: str, processos: int) -> pd.DataFrame:
    por_secao = defaultdict(list)
    erros = []
    with zipfile.ZipFile(caminho) as zf:
        n_log = sum(1 for i in zf.infolist() if i.filename.lower().endswith(EXT_LOG))
        n_zip = sum(1 for i in zf.infolist() if i.filename.lower().endswith(".zip"))
        total = n_log if not n_zip else None
        print(f"  {n_log:,} logs" + (f" e {n_zip:,} zips internos" if n_zip else "") + " a processar")
        t0 = time.time()
        for i, r in enumerate(_em_paralelo(iterar_logjez(zf), processos), 1):
            if "erro" in r:
                erros.append((r["nome"], r["erro"]))
            else:
                por_secao[r["chave"]].append(r)
            if i % 500 == 0:
                de = f"/{total:,}" if total else ""
                print(f"\r  {i:,}{de} logs lidos  ({i / (time.time() - t0):,.0f}/s)   ", end="", flush=True)
    print(f"\r  {sum(len(v) for v in por_secao.values()):,} logs lidos, {len(por_secao):,} seções, "
          f"{len(erros)} com erro")
    for nome, erro in erros[:10]:
        print(f"    ! {nome}: {erro}")

    # fuso de cada seção e harmonização pelo fuso mais comum do município
    linhas = []
    for (mun, zona, secao), logs in por_secao.items():
        votos = np.concatenate([l["votos_s"] for l in logs])
        hab = np.concatenate([l["hab"] for l in logs])
        ordem = np.argsort(votos, kind="stable")
        votos, hab = votos[ordem], hab[ordem]
        aberturas = [l["abertura_s"] for l in logs if l["abertura_s"] is not None]
        abertura = min(aberturas) if aberturas else None
        linhas.append({"cd_municipio": mun, "zona": zona, "secao": secao,
                       "_votos": votos, "_hab": hab, "_abertura": abertura,
                       "_fuso": estimar_fuso(abertura, int(votos[0]) if len(votos) else None),
                       "n_logs": len(logs), "n_urnas": len(set().union(*[l["urnas"] for l in logs])),
                       "dia": next((l["dia"] for l in logs if l["dia"]), None)})
    fuso_mun = defaultdict(Counter)
    for l in linhas:
        fuso_mun[l["cd_municipio"]][l["_fuso"]] += 1
    saida = []
    for l in linhas:
        fuso = fuso_mun[l["cd_municipio"]].most_common(1)[0][0]
        m = metricas(l["_votos"], l["_hab"], fuso)
        m["abertura"] = (l["_abertura"] / 3600 - fuso) if l["_abertura"] is not None else np.nan
        m["abertura_atrasada_min"] = max(0.0, (m["abertura"] - ABERTURA) * 60) if l["_abertura"] else np.nan
        saida.append({"uf": uf, **{k: v for k, v in l.items() if not k.startswith("_")}, **m})
    if not saida:
        with zipfile.ZipFile(caminho) as zf:
            exemplos = [i.filename for i in zf.infolist()][:8]
        print("  ! nenhum log de urna reconhecido neste zip. Primeiros arquivos encontrados:")
        for n in exemplos:
            print(f"      {n}")
        print("    O formato pode ter mudado; envie esta lista para ajustar o script.")
        return pd.DataFrame()
    df = pd.DataFrame(saida)
    hcols = [f"{p}{h:02d}" for p in "hsm" for h in range(24)]
    df[hcols] = df[hcols].astype("int16")
    return df


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, default=2026)
    p.add_argument("--turno", type=int, default=1)
    p.add_argument("--ufs", nargs="+", default=UFS, type=str.upper)
    p.add_argument("--zip", type=Path, help="Processar um zip já baixado (a UF é lida do nome)")
    p.add_argument("--apagar-zip", action="store_true", help="Apagar o zip após processar")
    p.add_argument("--refazer", action="store_true", help="Reprocessar UFs já processadas")
    p.add_argument("--processos", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = p.parse_args()
    PASTA.mkdir(exist_ok=True)

    if a.zip:
        m = re.search(r"_(\d{4})_(\d)t_([A-Z]{2})\.zip$", a.zip.name, re.I)
        uf = m.group(3).upper() if m else input("UF deste zip: ").strip().upper()
        ano, turno = (int(m.group(1)), int(m.group(2))) if m else (a.ano, a.turno)
        tarefas = [(uf, ano, turno, a.zip)]
    else:
        tarefas = [(uf, a.ano, a.turno, None) for uf in a.ufs]

    for uf, ano, turno, zip_local in tarefas:
        saida = PASTA / f"logs_{ano}_t{turno}_{uf}.parquet"
        if saida.exists() and not a.refazer:
            print(f"{uf}: já processado ({saida.name}); use --refazer para refazer")
            continue
        print(f"\n=== {uf} ({ano}, {turno}º turno) ===")
        try:
            caminho = zip_local or baixar(URL.format(ano=ano, turno=turno, uf=uf),
                                          PASTA / f"arqurna_{ano}_{turno}t_{uf}.zip")
        except Exception as e:
            print(f"  ! falha no download: {e}")
            continue
        df = processar_zip(caminho, uf, a.processos)
        if df.empty:
            print("  ! nenhum log válido encontrado")
            continue
        df.to_parquet(saida, index=False)
        print(f"  sem digital {1 - df['votos_digital'].sum() / df['votos_log'].sum():.1%} "
              f"(sem cadastro {df['votos_sem_cadastro'].sum() / df['votos_log'].sum():.1%}, "
              f"manual {df['votos_manual'].sum() / df['votos_log'].sum():.1%})")
        print(f"  hora média {df['hora_media'].mean():.2f}h | "
              f"{df['votos_apos_17'].sum():,} votos após 17h "
              f"({df['votos_apos_17'].sum() / df['votos_log'].sum():.2%}) | salvo em {saida.name}")
        if a.apagar_zip and not zip_local:
            caminho.unlink()
            print("  zip apagado")
    print("\nPronto. Rode:  streamlit run painel.py")


if __name__ == "__main__":
    sys.exit(main())
