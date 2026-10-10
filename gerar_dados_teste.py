"""
Gera um zip FALSO no mesmo formato do arquivo do TSE, para testar o sistema
sem baixar nada. Inclui algumas seções anômalas plantadas de propósito.

    python gerar_dados_teste.py
    python baixar_dados.py --ano 1999 --zip dados/teste_detalhe_votacao_secao.zip
    streamlit run painel.py
"""
import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
UFS = {"SP": 0.225, "CE": 0.153, "MG": 0.226, "MS": 0.238, "RJ": 0.233}
CARGOS = [(1, "Presidente"), (3, "Governador"), (6, "Deputado Federal")]

linhas = []
for uf, base in UFS.items():
    for m in range(rng.integers(8, 20)):
        cd = int(rng.integers(10000, 99999))
        nm = f"MUNICIPIO {uf}-{m + 1:02d}"
        p_mun = np.clip(base + rng.normal(0, 0.03), 0.05, 0.6)
        for zona in range(1, rng.integers(2, 5)):
            for s in range(1, rng.integers(15, 120)):
                aptos = int(rng.integers(30, 420))
                p = np.clip(p_mun + rng.normal(0, 0.035), 0.01, 0.95)  # superdispersão
                abst = int(rng.binomial(aptos, p))
                linhas.append([uf, cd, nm, zona, s, aptos, abst, (zona * 1000 + s // 8)])

df = pd.DataFrame(linhas, columns=["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA",
                                   "NR_SECAO", "QT_APTOS", "QT_ABSTENCOES", "NR_LOCAL_VOTACAO"])
# anomalias plantadas
idx = rng.choice(len(df), 12, replace=False)
for i, j in enumerate(idx):
    df.loc[j, "QT_ABSTENCOES"] = int(df.loc[j, "QT_APTOS"] * (0.02 if i % 2 else 0.65))
print("Seções plantadas:\n", df.loc[idx, ["SG_UF", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO"]].to_string())

df["QT_COMPARECIMENTO"] = df["QT_APTOS"] - df["QT_ABSTENCOES"]
df["NM_LOCAL_VOTACAO"] = "ESCOLA " + df["NR_LOCAL_VOTACAO"].astype(str)
df["NR_TURNO"] = 1
df["ANO_ELEICAO"] = 1999
partes = []
for cd, ds in CARGOS:
    d = df.copy()
    d["CD_CARGO"], d["DS_CARGO"] = cd, ds
    partes.append(d)
tudo = pd.concat(partes)

saida = Path(__file__).parent / "dados" / "teste_detalhe_votacao_secao.zip"
saida.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
    for uf, g in tudo.groupby("SG_UF"):
        buf = io.StringIO()
        g.to_csv(buf, sep=";", index=False)
        z.writestr(f"detalhe_votacao_secao_1999_{uf}.csv", buf.getvalue().encode("latin-1"))
print(f"\n{len(df):,} seções sintéticas -> {saida}")
