# Abstenção por seção eleitoral — Eleições 2026

Baixa os dados oficiais do TSE de comparecimento/abstenção de **todas as seções
eleitorais** e abre um painel interativo (estilo BI) com média e desvio padrão
por Brasil → estado → município → zona → seção, sinalizando seções com
abstenção fora do padrão.

## Como usar

Requer Python 3.10+.

```bash
pip install -r requirements.txt

python baixar_dados.py            # baixa ~centenas de MB do TSE e gera dados/secoes_2026_t1.parquet
streamlit run painel.py           # abre o painel no navegador (http://localhost:8501)
```

Outras opções:

```bash
python baixar_dados.py --turno 2                     # 2º turno (25/10), quando o TSE publicar
python baixar_dados.py --ano 2022                    # eleição anterior, para comparar
python baixar_dados.py --zip caminho/do/arquivo.zip  # se baixou o zip pelo navegador
```

Se o download falhar, baixe manualmente o arquivo **"Detalhe da apuração por
seção eleitoral"** em <https://dadosabertos.tse.jus.br/dataset/resultados-2026>
e use `--zip`.

Para testar sem baixar nada: `python gerar_dados_teste.py` e depois
`python baixar_dados.py --ano 1999 --zip dados/teste_detalhe_votacao_secao.zip`
(dados inventados com 12 anomalias plantadas).

## O painel

- **Barra lateral**: escolhe eleição/turno, desce de nível (UF → município → zona → seção) e ajusta o critério de alerta.
- **Comparar**: média ± desvio padrão de cada subunidade (UFs, municípios, zonas ou locais de votação). Com muitos municípios, vira um gráfico média × desvio padrão onde quem destoa do grupo aparece isolado.
- **Distribuição**: histograma das seções com linhas de média, ±1 e ±2 desvios.
- **Funil**: abstenção × tamanho da seção, com limites de ±2 e ±3 desvios esperados para cada tamanho.
- **Seções sinalizadas**: lista ordenada, exportável em CSV; clicar numa linha abre o detalhe.
- **Detalhe da seção**: seção vs zona, município, UF e Brasil; percentis; abstenções esperadas; e as outras seções do **mesmo local de votação**.

## Como uma seção é sinalizada

Cada seção é comparada com **o próprio município** (sem contar ela mesma). Se o
município tem menos de 5 seções, a comparação é com a UF.

| Medida | Fórmula | Observação |
|---|---|---|
| z simples | (taxa − média) / desvio padrão | O que se pede intuitivamente, mas seções pequenas variam muito por acaso e dominam a lista. |
| z binomial | (faltaram − esperado) / √(aptos·p·(1−p)) | Considera o tamanho da seção, mas supõe que só o acaso separa as seções — sinaliza milhares. |
| **z ajustado** (padrão) | (taxa − esperada) / √(p(1−p)/aptos + τ²) | τ² é a variação natural entre seções (perfil etário, renda, cadastro desatualizado), estimada por UF de forma robusta. É o modelo de efeitos aleatórios usado em *funnel plots*. Com \|z\| ≥ 3, sinaliza poucas seções de verdade. |

## Como interpretar (importante)

Uma seção com abstenção atípica **não é indício de fraude por si só**, e a
grande maioria tem explicação comum:

- **Alta**: seção com muitos idosos (voto facultativo após 70 anos), eleitores
  que se mudaram e não transferiram o título, óbitos ainda não baixados,
  zona rural ou ribeirinha distante, presídios/unidades especiais,
  seções que receberam muitos eleitores transferidos (voto em trânsito).
- **Baixa**: seções novas ou recém-agregadas, cadastro biométrico recente
  (revisão eleitoral limpa o cadastro), comunidades pequenas e coesas.

Abstenção é o número de eleitores que **não** foram votar; ela é registrada
pela urna a partir dos eleitores habilitados pelos mesários. Por isso, um caminho
mais informativo para investigar um ponto sinalizado é:

1. Ver as **outras seções do mesmo local de votação** (aba de detalhe) — se a
   escola inteira destoa, é perfil da região; se só uma seção destoa, vale olhar mais.
2. Comparar com **2022** (`--ano 2022`): uma seção que é atípica em todas as
   eleições quase sempre tem causa estrutural.
3. Conferir o **boletim de urna** e o **log da urna** daquela seção no site de
   resultados do TSE e, se for o caso, encaminhar a dúvida ao TRE do estado.

Com cerca de 470 mil seções, mesmo uma regra muito rigorosa vai listar
dezenas a centenas de seções só por acaso estatístico.
