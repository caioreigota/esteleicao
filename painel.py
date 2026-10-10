"""
Painel de abstenção por seção eleitoral.
    streamlit run painel.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analise import limites_funil, pontuar_secoes, resumo

st.set_page_config(page_title="Abstenção por seção", page_icon="🗳️", layout="wide")
PASTA = Path(__file__).parent / "dados"
COR_ALTA, COR_BAIXA, COR_NORMAL = "#d6453d", "#2f6fb5", "#9aa4b1"
TODOS = "— Todos —"


@st.cache_data(show_spinner="Carregando e calculando estatísticas…")
def carregar(caminho: str) -> pd.DataFrame:
    df = pd.read_parquet(caminho)
    for c in ["uf", "municipio"]:
        df[c] = df[c].astype("category")
    return pontuar_secoes(df)


def pct(x, casas=1):
    return "—" if pd.isna(x) else f"{x * 100:.{casas}f}%"


# ---------------------------------------------------------------- dados
arquivos = sorted(PASTA.glob("secoes_*.parquet"), reverse=True)
if not arquivos:
    st.error("Nenhum dado encontrado. Rode primeiro:  `python baixar_dados.py`")
    st.stop()

with st.sidebar:
    st.header("🗳️ Abstenção por seção")
    arquivo = st.selectbox("Eleição / turno", arquivos, format_func=lambda p: p.stem.replace("secoes_", ""))
    base = carregar(str(arquivo))

    st.subheader("Navegação")
    incluir_zz = st.checkbox("Incluir exterior (ZZ)", value=False)
    if not incluir_zz:
        base = base[base["uf"] != "ZZ"]

    ufs = sorted(base["uf"].unique().tolist())
    uf = st.selectbox("Estado", [TODOS] + ufs)
    df = base if uf == TODOS else base[base["uf"] == uf]

    mun = zona = secao = TODOS
    if uf != TODOS:
        muns = df[["cd_municipio", "municipio"]].drop_duplicates().sort_values("municipio")
        opc = dict(zip(muns["cd_municipio"], muns["municipio"]))
        mun = st.selectbox("Município", [TODOS] + list(opc), format_func=lambda c: opc.get(c, c))
        if mun != TODOS:
            df = df[df["cd_municipio"] == mun]
            zona = st.selectbox("Zona", [TODOS] + sorted(df["zona"].dropna().unique().tolist()))
            if zona != TODOS:
                df = df[df["zona"] == zona]
                secao = st.selectbox("Seção", [TODOS] + sorted(df["secao"].dropna().unique().tolist()))

    st.subheader("Critério de alerta")
    medida = st.radio("Medida", ["z_ajustado", "z_binomial", "z_simples"],
                      format_func={"z_ajustado": "z ajustado (recomendado)",
                                   "z_binomial": "z binomial",
                                   "z_simples": "z simples (média/desvio)"}.get,
                      help="Ver README: o z ajustado leva em conta o tamanho da seção "
                           "e a variação natural entre seções.")
    limite = st.slider("Sinalizar quando |z| ≥", 2.0, 6.0, 3.0, 0.5)
    min_aptos = st.number_input("Ignorar seções com menos aptos que", 0, 500, 50, 10)

df = df.assign(alerta=np.select(
    [(df[medida] >= limite) & (df["aptos"] >= min_aptos),
     (df[medida] <= -limite) & (df["aptos"] >= min_aptos)],
    ["alta", "baixa"], "normal"))

# ---------------------------------------------------------------- cabeçalho
nivel = ("Brasil" if uf == TODOS else uf if mun == TODOS else
         f"{df['municipio'].iloc[0]} / {uf}" + (f" · Zona {zona}" if zona != TODOS else ""))
st.title(nivel)

r = resumo(df).iloc[0]
c = st.columns(7)
c[0].metric("Seções", f"{int(r.secoes):,}".replace(",", "."))
c[1].metric("Aptos", f"{int(r.aptos):,}".replace(",", "."))
c[2].metric("Abstenção agregada", pct(r.taxa_agregada, 2),
            help="Total de abstenções ÷ total de aptos (número oficial)")
c[3].metric("Média das seções", pct(r.media),
            help="Média simples da taxa de abstenção de cada seção")
c[4].metric("Desvio padrão", pct(r.desvio_padrao),
            help="Desvio padrão da taxa de abstenção entre as seções")
c[5].metric("🔺 Sinalizadas alta", int((df["alerta"] == "alta").sum()))
c[6].metric("🔻 Sinalizadas baixa", int((df["alerta"] == "baixa").sum()))


# ---------------------------------------------------------------- detalhe de seção
def detalhe_secao(s: pd.Series):
    st.subheader(f"Seção {s['secao']} · Zona {s['zona']} · {s['municipio']}/{s['uf']}")
    if "nome_local" in s and pd.notna(s.get("nome_local")):
        st.caption(f"Local de votação: {s['nome_local']}"
                   + (f" — {s['endereco_local']}" if pd.notna(s.get('endereco_local')) else ""))
    k = st.columns(5)
    k[0].metric("Abstenção da seção", pct(s["taxa_abstencao"]),
                f"{(s['taxa_abstencao'] - s['taxa_esperada']) * 100:+.1f} p.p. vs esperado",
                delta_color="inverse")
    k[1].metric("Aptos / faltaram", f"{s['aptos']} / {s['abstencoes']}",
                f"esperado ≈ {s['abst_esperadas']:.0f}", delta_color="off")
    k[2].metric("z ajustado", f"{s['z_ajustado']:+.2f}")
    k[3].metric("Percentil no município", pct(s["pct_municipio"], 0))
    k[4].metric("Percentil no Brasil", pct(s["pct_brasil"], 0))

    zona_df = base[(base["cd_municipio"] == s["cd_municipio"]) & (base["zona"] == s["zona"])]
    mun_df = base[base["cd_municipio"] == s["cd_municipio"]]
    uf_df = base[base["uf"] == s["uf"]]
    comp = pd.DataFrame({
        "nível": ["Esta seção", f"Zona {s['zona']}", "Município", s["uf"], "Brasil"],
        "media": [s["taxa_abstencao"]] + [d["taxa_abstencao"].mean() for d in (zona_df, mun_df, uf_df, base)],
        "dp": [0] + [d["taxa_abstencao"].std() for d in (zona_df, mun_df, uf_df, base)],
    })
    a, b = st.columns(2)
    fig = go.Figure(go.Bar(x=comp["nível"], y=comp["media"],
                           error_y=dict(type="data", array=comp["dp"], visible=True),
                           marker_color=[COR_ALTA if s["z_ajustado"] > 0 else COR_BAIXA] + [COR_NORMAL] * 4,
                           text=[pct(v) for v in comp["media"]], textposition="outside"))
    fig.update_layout(title="Comparação (barra = média, traço = ± 1 desvio padrão)",
                      yaxis_tickformat=".0%", height=360, margin=dict(t=50, b=10))
    a.plotly_chart(fig, width="stretch")

    fig = px.histogram(mun_df, x="taxa_abstencao", nbins=40, color_discrete_sequence=[COR_NORMAL],
                       title="Onde a seção cai entre as seções do município")
    fig.add_vline(x=s["taxa_abstencao"], line_color=COR_ALTA, line_width=3,
                  annotation_text="esta seção")
    fig.update_layout(xaxis_tickformat=".0%", height=360, margin=dict(t=50, b=10),
                      xaxis_title="taxa de abstenção", yaxis_title="seções")
    b.plotly_chart(fig, width="stretch")

    if "local" in s and pd.notna(s.get("local")):
        vizinhas = mun_df[(mun_df["zona"] == s["zona"]) & (mun_df["local"] == s["local"])]
        st.markdown("**Outras seções do mesmo local de votação** (mesma escola, mesmo público — "
                    "se só esta destoa, é um sinal mais forte)")
        st.dataframe(vizinhas[["secao", "aptos", "abstencoes", "taxa_abstencao", "z_ajustado"]]
                     .sort_values("secao"), hide_index=True, width="stretch",
                     column_config={"taxa_abstencao": st.column_config.NumberColumn(format="percent")})


if secao != TODOS:
    detalhe_secao(df[df["secao"] == secao].iloc[0])
    st.stop()

# ---------------------------------------------------------------- abas
aba_comp, aba_dist, aba_funil, aba_alertas = st.tabs(
    ["📊 Comparar", "📈 Distribuição", "🔻 Funil (tamanho × abstenção)", "🚩 Seções sinalizadas"])

with aba_comp:
    if uf == TODOS:
        filho, rotulo = ["uf"], "uf"
    elif mun == TODOS:
        filho, rotulo = ["cd_municipio", "municipio"], "municipio"
    elif zona == TODOS:
        filho, rotulo = ["zona"], "zona"
    else:
        filho, rotulo = (["local"], "local") if "local" in df else (["secao"], "secao")

    tab = resumo(df, filho)
    alertas = df[df["alerta"] != "normal"].groupby(filho, observed=True).size().rename("sinalizadas")
    tab = tab.merge(alertas, left_on=filho, right_index=True, how="left").fillna({"sinalizadas": 0})
    tab[rotulo] = tab[rotulo].astype(str)

    if len(tab) <= 40:
        t = tab.sort_values("media")
        fig = go.Figure(go.Scatter(
            x=t["media"], y=t[rotulo], mode="markers",
            error_x=dict(type="data", array=t["desvio_padrao"].fillna(0), color="#b8c0cc"),
            marker=dict(size=9, color="#33415c"),
            customdata=np.stack([t["secoes"], t["taxa_agregada"]], axis=1),
            hovertemplate="%{y}<br>média %{x:.1%}<br>seções %{customdata[0]}<br>"
                          "agregada %{customdata[1]:.1%}<extra></extra>"))
        fig.add_vline(x=r.media, line_dash="dash", annotation_text="média do nível acima")
        fig.update_layout(title="Média ± 1 desvio padrão da abstenção das seções",
                          xaxis_tickformat=".0%", height=max(350, 22 * len(t) + 80),
                          margin=dict(l=10, r=10, t=50, b=10))
    else:
        fig = px.scatter(tab, x="media", y="desvio_padrao", size="aptos", color="sinalizadas",
                         hover_name=rotulo, color_continuous_scale="OrRd", size_max=40,
                         hover_data={"secoes": True, "taxa_agregada": ":.1%", "aptos": ":,"},
                         title="Cada ponto é uma unidade: média × desvio padrão "
                               "(longe do grupo = comportamento diferente)")
        fig.update_layout(xaxis_tickformat=".0%", yaxis_tickformat=".0%", height=560)
    st.plotly_chart(fig, width="stretch")

    st.dataframe(tab.drop(columns=[c for c in ["cd_municipio"] if c in tab and rotulo != "cd_municipio"])
                 .sort_values("media", ascending=False), hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="percent")
                                for c in ["taxa_agregada", "media", "desvio_padrao", "mediana",
                                          "mad", "p05", "p95", "minimo", "maximo"]})

with aba_dist:
    fig = px.histogram(df, x="taxa_abstencao", nbins=80, color_discrete_sequence=["#33415c"])
    for k, estilo in [(0, "solid"), (1, "dash"), (-1, "dash"), (2, "dot"), (-2, "dot")]:
        x = r.media + k * r.desvio_padrao
        fig.add_vline(x=x, line_dash=estilo, line_color=COR_ALTA if k else "black",
                      annotation_text="média" if k == 0 else f"{k:+d} dp")
    fig.update_layout(title="Distribuição da abstenção por seção", xaxis_tickformat=".0%",
                      xaxis_title="taxa de abstenção", yaxis_title="seções", height=480)
    st.plotly_chart(fig, width="stretch")
    st.caption("A distribuição real tem caudas mais largas que uma normal; por isso, contar "
               "seções além de ±2 dp num nível grande (Brasil, UF) sempre dá milhares de casos. "
               "O z ajustado, comparando cada seção com o próprio município, é mais útil para achar pontos.")

with aba_funil:
    pontos = df
    normais = pontos[pontos["alerta"] == "normal"]
    if len(normais) > 60_000:  # mantém o gráfico leve em nível Brasil
        pontos = pd.concat([normais.sample(60_000, random_state=1), pontos[pontos["alerta"] != "normal"]])
    fig = go.Figure()
    for nome, cor in [("normal", COR_NORMAL), ("alta", COR_ALTA), ("baixa", COR_BAIXA)]:
        d = pontos[pontos["alerta"] == nome]
        fig.add_trace(go.Scattergl(
            x=d["aptos"], y=d["taxa_abstencao"], mode="markers", name=nome,
            marker=dict(size=4 if nome == "normal" else 7, color=cor,
                        opacity=0.35 if nome == "normal" else 0.9),
            text=d["municipio"].astype(str) + " · Z" + d["zona"].astype(str) + " · S" + d["secao"].astype(str),
            hovertemplate="%{text}<br>aptos %{x}<br>abstenção %{y:.1%}<extra></extra>"))
    tau2 = float(df["tau2"].median())
    for k, estilo in [(2, "dash"), (3, "solid")]:
        lim = limites_funil(r.taxa_agregada, tau2, int(df["aptos"].max()), k)
        for lado in ["inf", "sup"]:
            fig.add_trace(go.Scatter(x=lim["aptos"], y=lim[lado], mode="lines", showlegend=False,
                                     line=dict(color="black", dash=estilo, width=1), hoverinfo="skip"))
    fig.update_layout(title="Funil: seções pequenas variam mais por acaso — "
                            "linhas = ±2 e ±3 desvios esperados para cada tamanho",
                      xaxis_title="eleitores aptos na seção", yaxis_title="abstenção",
                      yaxis_tickformat=".0%", height=600)
    st.plotly_chart(fig, width="stretch")
    st.caption("O funil usa a abstenção agregada deste nível como centro. As cores (alta/baixa) "
               "usam a comparação com o próprio município, por isso alguns pontos coloridos "
               "ficam dentro das linhas e vice-versa.")

with aba_alertas:
    sel = df[df["alerta"] != "normal"].copy()
    sel["abs_z"] = sel[medida].abs()
    sel = sel.sort_values("abs_z", ascending=False)
    st.write(f"**{len(sel):,}** seções com |{medida}| ≥ {limite} e ≥ {min_aptos} aptos "
             f"(de {len(df):,}). Selecione uma linha para ver o detalhe.")
    cols = [c for c in ["uf", "municipio", "zona", "secao", "nome_local", "aptos", "abstencoes",
                        "abst_esperadas", "taxa_abstencao", "taxa_esperada", "z_ajustado",
                        "z_binomial", "z_simples", "referencia", "alerta"] if c in sel]
    evento = st.dataframe(
        sel[cols], hide_index=True, width="stretch", height=420,
        on_select="rerun", selection_mode="single-row",
        column_config={"taxa_abstencao": st.column_config.NumberColumn(format="percent"),
                       "taxa_esperada": st.column_config.NumberColumn(format="percent"),
                       "abst_esperadas": st.column_config.NumberColumn(format="%.0f"),
                       "z_ajustado": st.column_config.NumberColumn(format="%.2f"),
                       "z_binomial": st.column_config.NumberColumn(format="%.2f"),
                       "z_simples": st.column_config.NumberColumn(format="%.2f")})
    st.download_button("⬇️ Baixar lista (CSV)", sel[cols].to_csv(index=False, sep=";", decimal=",")
                       .encode("utf-8-sig"), "secoes_sinalizadas.csv", "text/csv")
    linhas = evento.selection.rows if evento and evento.selection else []
    if linhas:
        st.divider()
        detalhe_secao(sel.iloc[linhas[0]])
