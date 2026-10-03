import streamlit as st
import pandas as pd
import re
from datetime import datetime, timedelta
import plotly.express as px


# ============================================================
# CONFIGURAÇÃO DA PÁGINA
# ============================================================

st.set_page_config(
    page_title="Torre de Controle — Shopee",
    page_icon="🚛",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# PARÂMETROS OPERACIONAIS
# ============================================================

KM_ALERTA_LOCALIZACAO_BASE = 60
TOLERANCIA_KM_LOCALIZACAO_BASE = 10

KM_ALERTA_PORTARIA_SP_RJ = 30
TOLERANCIA_KM_PORTARIA = 5
MINUTOS_PROXIMO_ETA_PORTARIA = 60

# Correção da distância
FATOR_CORRECAO_GERAL = 1.25
FATOR_CORRECAO_MA = 1.35

# Velocidade de referência operacional
VELOCIDADE_REFERENCIA_KMH = 60

# Tendência
HORIZONTE_TENDENCIA_MIN = 60
HORIZONTE_TENDENCIA_CURTO_MIN = 30

# Parada considerada longa para alerta operacional
LIMIAR_PARADO_LONGO_HORAS = 2.0

# Ocorrência que não é considerada causa de atraso por si só
OCORRENCIAS_NEUTRAS = {
    "Parada programada — intervalo/refeição"
}

# HUB/XPT
MINUTOS_ANTECEDENCIA_HUB_XPT = 60

# Endereços opcionais das bases
BASE_ENDERECOS = {
    # "SOC-PE2": "Rua Exemplo, 123 - Cabo de Santo Agostinho/PE",
}


# ============================================================
# CSS
# ============================================================

st.markdown(
    """
    <style>
    .main {
        background-color: #f4f6f9;
    }

    .metric-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 18px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
        text-align: center;
        transition: all 0.3s ease;
    }

    .metric-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 6px 12px rgba(238, 77, 45, 0.12);
        border-color: #ee4d2d;
    }

    .metric-title {
        font-size: 13px;
        color: #64748b;
        font-weight: 600;
        text-transform: uppercase;
        margin-bottom: 6px;
    }

    .metric-value {
        font-size: 24px;
        font-weight: 700;
        color: #1e293b;
    }

    div.stButton > button {
        background-color: #ee4d2d !important;
        color: white !important;
        font-weight: 600 !important;
        border: none !important;
        border-radius: 8px !important;
        width: 100%;
        padding: 0.7rem 1rem;
        font-size: 15px;
        box-shadow: 0 4px 10px rgba(238, 77, 45, 0.25);
        transition: all 0.3s ease;
    }

    div.stButton > button:hover {
        background-color: #d73a1d !important;
        box-shadow: 0 6px 15px rgba(238, 77, 45, 0.35);
        color: white !important;
    }

    h1, h2, h3 {
        color: #1e293b;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    </style>
    """,
    unsafe_allow_html=True
)


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def agora_brasilia():
    return datetime.utcnow() - timedelta(hours=3)


def parse_duration(time_str):
    try:
        parts = str(time_str).split(":")
        if len(parts) >= 2:
            h = int(parts[0])
            m = int(parts[1])
            return f"{h}h{m:02d}", h + (m / 60)
    except Exception:
        pass

    return "0h00", 0.0


def formatar_deficit_tempo(minutos_totais):
    minutos_totais = int(abs(minutos_totais))

    dias, resto = divmod(minutos_totais, 24 * 60)
    horas, minutos = divmod(resto, 60)

    if dias > 0:
        return f"Déficit de {dias:02d}d {horas}h {minutos:02d}min."

    return f"Déficit de {horas:02d}h {minutos:02d}min."


def parse_eta_to_datetime(eta_str, ano_atual):
    try:
        if not eta_str or eta_str in ("-", "—"):
            return None

        return datetime.strptime(
            f"{eta_str}/{ano_atual}",
            "%d/%m %H:%M/%Y"
        )

    except Exception:
        return None


def extract_uf(destino):
    """
    Identifica a UF em códigos como:
    SOC-PE2
    SOC-SP8
    HUB-LMA-01
    HUB-LPB-03
    XPT-LSE-90
    LM Hub_MA_FX_São Luís_01
    SoC_RJ_Queimados
    """

    if not destino:
        return "OUTROS"

    dest = str(destino).upper()

    ufs = [
        "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
        "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
        "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"
    ]

    # L + UF
    match = re.search(r"\bL([A-Z]{2})(?:[-_\d]|$)", dest)
    if match and match.group(1) in ufs:
        return match.group(1)

    # SoC_RJ, SOC_RJ, HUB_MA etc.
    match = re.search(r"(?:SOC|SOC_RJ|SOC_SP|HUB|XPT)[-_]([A-Z]{2})(?:[-_\d]|$)", dest)
    if match and match.group(1) in ufs:
        return match.group(1)

    # Código tradicional SOC-SP8 / HUB-LMA-02 / XPT-LSE-90
    match = re.search(r"(?:^|-)([A-Z]{2})(?:\d|-|_|$)", dest)
    if match and match.group(1) in ufs:
        return match.group(1)

    # LMA / LPA / LPB etc.
    match = re.search(r"\bL([A-Z]{2})(?:[-_\d]|$)", dest)
    if match and match.group(1) in ufs:
        return match.group(1)

    # Último recurso: procurar UF delimitada por separadores
    for uf in ufs:
        if re.search(rf"(?<![A-Z]){uf}(?![A-Z])", dest):
            return uf

    return "OUTROS"


def destino_eh_hub_xpt(destino):
    """
    Detecta HUB ou XPT em qualquer parte do nome do destino.
    """

    if not destino:
        return False

    texto = str(destino).upper()

    return bool(
        re.search(r"\bHUB\b", texto)
        or re.search(r"\bXPT\b", texto)
        or "HUB-" in texto
        or "XPT-" in texto
        or "HUB_" in texto
        or "XPT_" in texto
    )


def motivo_eh_neutro(motivo):
    if not motivo:
        return True

    return str(motivo).strip() in OCORRENCIAS_NEUTRAS


def ocorrencia_explicada(motivo):
    """
    Verdadeiro quando existe uma ocorrência diferente da parada
    programada de intervalo/refeição.
    """

    if not motivo:
        return False

    return not motivo_eh_neutro(motivo)


def esta_em_rota(row):
    return pd.isna(row["Chegada_Real_Dt"])


def esta_no_range_turno(eta_dt, data_trabalho_str):
    """Retorna True quando o ETA está no range operacional do turno.

    Range: 19:00 do dia do plantão até 15:00 do dia seguinte.
    """

    if not eta_dt:
        return False

    try:
        dt_base = datetime.strptime(
            data_trabalho_str,
            "%d/%m/%Y"
        )
    except Exception:
        return False

    inicio = dt_base.replace(
        hour=19, minute=0, second=0, microsecond=0
    )
    fim = inicio + timedelta(hours=20)

    return inicio <= eta_dt <= fim


# ============================================================
# PROJEÇÃO DA MARGEM
# ============================================================

def calcular_margem_projetada(row, horizonte_min):
    """
    Projeta a margem se a LT continuar exatamente no comportamento atual
    durante o horizonte informado.

    Se estiver parada:
        não há avanço.

    Se estiver em movimento:
        usa a velocidade atual.

    A distância restante continua recebendo o mesmo fator de correção.
    """

    if not row["ETA_Dt"]:
        return None

    if row["Distancia_Raw"] <= 0:
        return None

    velocidade = float(row["Velocidade"] or 0)

    distancia_percorrida_raw = 0

    if row["Status_Movimento"] == "Em trânsito" and velocidade > 0:
        distancia_percorrida_raw = velocidade * (horizonte_min / 60)

    distancia_restante_raw = max(
        float(row["Distancia_Raw"]) - distancia_percorrida_raw,
        0
    )

    fator = (
        FATOR_CORRECAO_MA
        if row["UF"] == "MA"
        else FATOR_CORRECAO_GERAL
    )

    distancia_restante_corrigida = distancia_restante_raw * fator

    tempo_disponivel_futuro = (
        row["ETA_Dt"] - (
            agora_brasilia() + timedelta(minutes=horizonte_min)
        )
    ).total_seconds() / 60

    margem_projetada = (
        tempo_disponivel_futuro
        - distancia_restante_corrigida
    )

    return margem_projetada


def avaliar_tendencia(data):
    """
    Classifica somente tendências realmente relevantes.

    Regra operacional:
    - a LT precisa estar matematicamente no prazo agora;
    - a projeção de 60 minutos é calculada mantendo o comportamento atual;
    - só existe tendência quando, ao chegar 60 minutos à frente, a margem
      ficar apertada (até 30 minutos) ou negativa.

    Assim, velocidade baixa, parada ou ocorrência isoladamente não criam
    tendência quando ainda existe folga confortável na projeção.
    """

    margem_atual = float(data["Margem_Minutos"] or 0)

    if margem_atual <= 0:
        return False, ""

    margem_60 = calcular_margem_projetada(
        data,
        HORIZONTE_TENDENCIA_MIN
    )

    if margem_60 is None:
        return False, ""

    # Regra única e objetiva: daqui a 60 min a margem precisa estar
    # apertada. Se ainda houver mais de 30 min de folga, não alertar.
    if margem_60 > 30:
        return False, ""

    nivel = "CRÍTICA" if margem_60 <= 0 else "MODERADA"

    detalhes = [
        f"margem atual de {int(margem_atual)} min",
        f"projeção em 60 min: {int(margem_60)} min"
    ]

    if data["Status_Movimento"] == "Parado" and data["Tempo_Horas"] > 0:
        detalhes.append(f"parado há {data['Tempo_Str']}")

    velocidade = float(data["Velocidade"] or 0)
    if velocidade > 0:
        detalhes.append(f"velocidade atual de {int(velocidade)} km/h")

    return (
        True,
        f"[TENDÊNCIA {nivel}] " + " | ".join(detalhes) + "."
    )


def motivo_para_exibicao(motivo):
    """Texto usado nas áreas de atraso/relatório.

    A parada programada de intervalo/refeição não é apresentada como
    justificativa final de atraso: ela passa a exigir investigação da causa.
    """

    motivo = str(motivo or "").strip()

    if motivo_eh_neutro(motivo):
        return "PROCURAR RAZÃO DO ATRASO"

    return motivo or "—"


# ============================================================
# FILTRO DE ALERTA
# ============================================================

def deve_alertar_tendencia(row):
    """
    Controle de visibilidade operacional.

    IMPORTANTE:
    isso NÃO muda a classificação matemática.

    Um Delay com ocorrência explicada continua sendo Delay.

    Porém, ele não precisa ficar repetindo no Plano de Ação/Tendência
    se a causa já está conhecida.

    Exceções:
    - parada programada/refeição;
    - perto da base;
    - parada muito longa.
    """

    motivo = str(row["Motivo_Parada"] or "").strip()

    # Sem ocorrência: alerta normal
    if not motivo:
        return True

    # Intervalo/refeição continua sendo acompanhado normalmente
    if motivo_eh_neutro(motivo):
        return True

    perto_da_base = (
        row["Distancia_Raw"]
        <= KM_ALERTA_LOCALIZACAO_BASE + TOLERANCIA_KM_LOCALIZACAO_BASE
    )

    parado_muito_tempo = (
        row["Status_Movimento"] == "Parado"
        and row["Tempo_Horas"] >= LIMIAR_PARADO_LONGO_HORAS
    )

    return perto_da_base or parado_muito_tempo


# ============================================================
# CLASSIFICAÇÃO DE PERFORMANCE
# ============================================================

def classificar_performance(row):

    if row["Status_Operacional"] == "Delay":
        return "Delay"

    motivo = str(row["Motivo_Parada"] or "").lower()

    if "aderência" in motivo or "antecipada" in motivo:
        return "Early"

    return "No prazo"


def calcular_performance_rota(df_uf):

    total_pacotes = df_uf["Pacotes"].sum()

    if total_pacotes == 0:
        return 0.0, pd.Series(dtype=float)

    impacto = df_uf["Pacotes"] / total_pacotes

    ganho = impacto.where(
        df_uf["Classificacao_Performance"] == "No prazo",
        0.0
    )

    performance_pct = ganho.sum() * 100

    return performance_pct, ganho


# ============================================================
# PROCESSAMENTO DOS DADOS
# ============================================================

def process_data_local(text, data_trabalho_str):

    # Normalização do texto colado
    text = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()

    # Remove espaços invisíveis/BOM
    text = text.replace("\ufeff", "")

    parsed_data = []

    agora_br = agora_brasilia()

    try:
        dt_base = datetime.strptime(
            data_trabalho_str,
            "%d/%m/%Y"
        )

        ano_atual = dt_base.year

    except Exception:
        ano_atual = agora_br.year

    # --------------------------------------------------------
    # NOVO PARSER DE BLOCOS
    #
    # Procura cada LT diretamente no começo de uma linha.
    # Isso é mais resistente ao conteúdo copiado do dashboard.
    # --------------------------------------------------------

    matches = list(
        re.finditer(
            r"(?m)^LT[0-9A-Z]+\b",
            text
        )
    )

    if not matches:
        return pd.DataFrame()

    blocks = []

    for i, match in enumerate(matches):

        inicio = match.start()

        if i + 1 < len(matches):
            fim = matches[i + 1].start()
        else:
            fim = len(text)

        blocks.append(text[inicio:fim].strip())

    # --------------------------------------------------------
    # PROCESSA CADA LT
    # --------------------------------------------------------

    for block in blocks:

        if not block.startswith("LT"):
            continue

        lines = [
            line.strip()
            for line in block.split("\n")
            if line.strip()
        ]

        if not lines:
            continue

        data = {
            "LT_Full": "",
            "LT_Short": "",
            "Motorista": "",
            "Origem": "",
            "Destino": "",
            "UF": "OUTROS",
            "Pacotes": 0,
            "ETA": "-",
            "Chegada_Real": "-",
            "Velocidade": 0,
            "Distancia_Raw": 0,
            "Distancia_Corrigida": 0,
            "Fator_Correcao": "",
            "Status_Movimento": "",
            "Tempo_Str": "0h00",
            "Tempo_Horas": 0.0,
            "Motivo_Parada": "",
            "Ultima_Atualizacao_Str": "",
            "Marcador_Early": "",
            "Andamento_Dashboard": "",
            "Ignicao": "",
            "Progressao": "",
            "Proximidade": 0,
            "Early_Pendente": False,
            "Em_Range_Turno": False,
            "Sem_Sinal": False,
            "Status_Operacional": "Normal",
            "Classificacao_Desempenho": "No prazo",
            "Motivo_Risco": "",
            "Margem_Minutos": 999,
            "ETA_Dt": None,
            "Chegada_Real_Dt": None,
            "Adiantamento_Minutos": None
        }

        # ----------------------------------------------------
        # LT + MOTORISTA
        # ----------------------------------------------------

        first_line = lines[0].split("\t")

        data["LT_Full"] = first_line[0].strip()
        data["LT_Short"] = data["LT_Full"][-5:]

        if len(first_line) > 1:
            data["Motorista"] = first_line[1].strip()

        # ----------------------------------------------------
        # MOVIMENTO
        # ----------------------------------------------------

        block_lower = block.lower()

        if "em trânsito há" in block_lower:
            data["Status_Movimento"] = "Em trânsito"

        elif "parado há" in block_lower:
            data["Status_Movimento"] = "Parado"

        # ----------------------------------------------------
        # TEMPO PARADO / EM TRÂNSITO
        # ----------------------------------------------------

        time_match = re.search(
            r"(\d{2}:\d{2}:\d{2})",
            block
        )

        if time_match:
            (
                data["Tempo_Str"],
                data["Tempo_Horas"]
            ) = parse_duration(time_match.group(1))

        # ----------------------------------------------------
        # VELOCIDADE
        # ----------------------------------------------------

        vel_match = re.search(
            r"(\d+)\s*km/h",
            block,
            re.IGNORECASE
        )

        if vel_match:
            data["Velocidade"] = int(
                vel_match.group(1)
            )

        # ----------------------------------------------------
        # DISTÂNCIA
        # ----------------------------------------------------

        dist_matches = re.findall(
            r"(?m)^(\d+)\s*km$",
            block
        )

        if dist_matches:
            # O último "X km" do bloco é a distância restante
            data["Distancia_Raw"] = int(
                dist_matches[-1]
            )

        # ----------------------------------------------------
        # ORIGEM / DESTINO
        #
        # Aceita:
        # SOC-BA2 -> SOC-GO1
        # FMH-3PL-17 -> SoC_RJ_Queimados
        # SOC-GO1 -> LM Hub_MA_FX_São Luís_01
        # ----------------------------------------------------

        idx_dest = None

        for idx_linha, line in enumerate(lines):

            if "\t" not in line:
                continue

            parts = [
                p.strip()
                for p in line.split("\t")
            ]

            if len(parts) < 2:
                continue

            origem_candidata = parts[0]
            destino_candidato = parts[1]

            if idx_linha == 0:
                continue

            origem_upper = origem_candidata.upper()

            origem_valida = (
                origem_upper.startswith("SOC-")
                or origem_upper.startswith("FMH-")
                or origem_upper.startswith("HUB-")
                or origem_upper.startswith("XPT-")
                or origem_upper.startswith("LM ")
                or origem_upper.startswith("LM_")
            )

            if origem_valida and destino_candidato:

                data["Origem"] = origem_candidata
                data["Destino"] = destino_candidato

                idx_dest = idx_linha
                break

        # ----------------------------------------------------
        # FALLBACK PARA DESTINO
        # ----------------------------------------------------

        if not data["Destino"]:

            destino_patterns = [
                r"(SOC-[A-Z0-9_-]+)",
                r"(HUB-[A-Z0-9_-]+)",
                r"(XPT-[A-Z0-9_-]+)",
                r"(SoC_[A-Z0-9_-]+)",
                r"(LM\s+[A-Z0-9_ÁÉÍÓÚÀÂÊÔÃÕÇ-]+)",
                r"(LPA[A-Z0-9_-]*)",
                r"(LMA[A-Z0-9_-]*)"
            ]

            for pattern in destino_patterns:

                match_dest = re.search(
                    pattern,
                    block,
                    re.IGNORECASE
                )

                if match_dest:
                    data["Destino"] = match_dest.group(1)
                    break

        data["UF"] = extract_uf(
            data["Destino"]
        )

        # ----------------------------------------------------
        # OCORRÊNCIA
        #
        # Estrutura normal:
        #
        # origem/destino
        # 4
        # Parada programada...
        # 8265
        #
        # Portanto, o número 4 NÃO é pacote.
        # ----------------------------------------------------

        if idx_dest is not None:

            pos = idx_dest + 1

            if pos < len(lines):

                linha_contagem = lines[pos]

                # Exemplo:
                # 4
                # Parada programada
                # 8265

                if (
                    not linha_contagem.startswith("--")
                    and pos + 1 < len(lines)
                ):

                    candidata_motivo = lines[pos + 1]

                    candidata_limpa = (
                        candidata_motivo
                        .replace(".", "")
                        .replace(",", "")
                    )

                    if not candidata_limpa.isdigit():
                        data["Motivo_Parada"] = (
                            candidata_motivo
                        )

                        # Pacotes normalmente estão logo depois
                        if pos + 2 < len(lines):

                            pacote_candidato = (
                                lines[pos + 2]
                                .replace(".", "")
                                .replace(",", "")
                            )

                            if pacote_candidato.isdigit():
                                data["Pacotes"] = int(
                                    pacote_candidato
                                )

                # Exemplo:
                # --
                # 3200

                elif linha_contagem.startswith("--"):

                    if pos + 1 < len(lines):

                        pacote_candidato = (
                            lines[pos + 1]
                            .replace(".", "")
                            .replace(",", "")
                        )

                        if pacote_candidato.isdigit():
                            data["Pacotes"] = int(
                                pacote_candidato
                            )

        # ----------------------------------------------------
        # FALLBACK DE PACOTES
        # ----------------------------------------------------

        if data["Pacotes"] == 0:

            # Procura números grandes, ignorando contagens pequenas
            # e horários.
            candidatos_pacotes = []

            for line in lines:

                valor = (
                    line
                    .replace(".", "")
                    .replace(",", "")
                    .strip()
                )

                if valor.isdigit():

                    numero = int(valor)

                    if 100 <= numero <= 999999:
                        candidatos_pacotes.append(numero)

            if candidatos_pacotes:
                data["Pacotes"] = candidatos_pacotes[0]

        # ----------------------------------------------------
        # FALLBACK DE OCORRÊNCIA
        # ----------------------------------------------------

        if not data["Motivo_Parada"]:

            palavras_ocorrencia = [
                "Parada",
                "Retenção",
                "Acidente",
                "Problema",
                "Mudança",
                "Manutenção",
                "Trânsito",
                "aderência",
                "antecipada",
                "documentação",
                "fiscal",
                "Solicitação"
            ]

            for line in lines:

                if any(
                    kw.lower() in line.lower()
                    for kw in palavras_ocorrencia
                ):
                    data["Motivo_Parada"] = line
                    break

        # ----------------------------------------------------
        # COLUNAS DO NOVO DASHBOARD
        #
        # Ordem nova:
        # ETA -> REALIZADO -> PRAZO MÁXIMO EARLY ->
        # MARCADOR EARLY -> ANDAMENTO -> IGNIÇÃO -> VELOCIDADE ->
        # PROGRESSÃO -> PROXIMIDADE -> ÚLTIMO POSICIONAMENTO
        #
        # O prazo máximo para Early é deliberadamente ignorado.
        # ----------------------------------------------------

        date_pattern = r"^\d{2}/\d{2} \d{2}:\d{2}$"

        # Último posicionamento: último horário isolado do bloco.
        date_only_lines = [
            line for line in lines
            if re.match(date_pattern, line)
        ]

        if date_only_lines:
            data["Ultima_Atualizacao_Str"] = date_only_lines[-1]

            try:
                ts_dt = datetime.strptime(
                    f"{data['Ultima_Atualizacao_Str']}/{ano_atual}",
                    "%d/%m %H:%M/%Y"
                )

                if ts_dt > agora_br + timedelta(days=1):
                    ts_dt = ts_dt.replace(year=ano_atual - 1)

                horas_sem_atualizacao = (
                    agora_br - ts_dt
                ).total_seconds() / 3600

                if (
                    horas_sem_atualizacao >= 1.0
                    or "Não monitorado" in block
                ):
                    data["Sem_Sinal"] = True

            except Exception:
                pass

        # Algumas colunas são entregues na mesma linha, separadas por TAB,
        # por isso não podemos tratar cada linha física como uma coluna.

        # Localiza a linha física que contém o campo Andamento.
        andamento_line_idx = None
        for i, line in enumerate(lines):
            tokens_line = [p.strip() for p in line.split("\t") if p.strip()]
            if any(t in ("No prazo", "Atrasado", "Risco") for t in tokens_line):
                andamento_line_idx = i
                break

        # Antes do Andamento ficam ETA, realizado (ou —) e o prazo máximo
        # de Early. O prazo máximo é deliberadamente ignorado.
        if andamento_line_idx is not None:
            datas_antes_andamento = [
                line for line in lines[:andamento_line_idx]
                if re.match(date_pattern, line)
            ]

            if datas_antes_andamento:
                data["ETA"] = datas_antes_andamento[0]

                if len(datas_antes_andamento) >= 3:
                    data["Chegada_Real"] = datas_antes_andamento[1]
                else:
                    data["Chegada_Real"] = "—"

        field_tokens = []
        for line in lines:
            field_tokens.extend(
                [p.strip() for p in line.split("\t") if p.strip()]
            )

        andamento_idx = None
        for i, token in enumerate(field_tokens):
            if token in ("No prazo", "Atrasado", "Risco"):
                andamento_idx = i
                data["Andamento_Dashboard"] = token
                break

        # MARCADOR DE CONTATO DE EARLY
        for token in field_tokens:
            if token.lower() == "marcar contato":
                data["Marcador_Early"] = "Marcar contato"
                break
            if token.lower() == "contatado":
                data["Marcador_Early"] = "Contatado"
                break

        # IGNIÇÃO e VELOCIDADE pertencem à linha da coluna Andamento.
        # Isso evita confundir o "--" da ocorrência/pacotes com a ignição.
        if andamento_line_idx is not None:
            andamento_tokens = [
                p.strip()
                for p in lines[andamento_line_idx].split("\t")
                if p.strip()
            ]

            try:
                pos_status = next(
                    i for i, token in enumerate(andamento_tokens)
                    if token in ("No prazo", "Atrasado", "Risco")
                )

                if pos_status + 1 < len(andamento_tokens):
                    candidato_ignicao = andamento_tokens[pos_status + 1]
                    if candidato_ignicao in ("Ligada", "Desligada", "--"):
                        data["Ignicao"] = candidato_ignicao

                for token in andamento_tokens[pos_status + 1:]:
                    vel_token = re.search(
                        r"(\d+)\s*km/h",
                        token,
                        re.IGNORECASE
                    )
                    if vel_token:
                        data["Velocidade"] = int(vel_token.group(1))
                        break
            except StopIteration:
                pass

        # Fallback de velocidade para blocos incompletos.
        if data["Velocidade"] == 0:
            for token in field_tokens:
                vel_token = re.search(r"(\d+)\s*km/h", token, re.IGNORECASE)
                if vel_token:
                    data["Velocidade"] = int(vel_token.group(1))
                    break

        # PROGRESSÃO
        for token in field_tokens:
            if re.match(r"^\d+(?:[.,]\d+)?%$", token):
                data["Progressao"] = token
                break

        # PROXIMIDADE
        for token in field_tokens:
            prox_match = re.match(r"^(\d+)\s*km$", token, re.IGNORECASE)
            if prox_match:
                data["Proximidade"] = int(prox_match.group(1))
                break

        # A proximidade é a distância oficial para os cálculos.
        if data["Proximidade"] > 0:
            data["Distancia_Raw"] = data["Proximidade"]

        # Early pendente só é relevante dentro do range do turno.
        # A coluna 'prazo máximo para Early' é ignorada.
        data["Em_Range_Turno"] = esta_no_range_turno(
            parse_eta_to_datetime(data["ETA"], ano_atual),
            data_trabalho_str
        )
        data["Early_Pendente"] = (
            data["Em_Range_Turno"]
            and data["Marcador_Early"].lower() == "marcar contato"
        )

        # ----------------------------------------------------
        # DATETIME
        # ----------------------------------------------------

        data["ETA_Dt"] = parse_eta_to_datetime(
            data["ETA"],
            ano_atual
        )

        data["Chegada_Real_Dt"] = parse_eta_to_datetime(
            data["Chegada_Real"],
            ano_atual
        )

        # ----------------------------------------------------
        # ADIANTAMENTO
        # ----------------------------------------------------

        if (
            data["ETA_Dt"]
            and data["Chegada_Real_Dt"]
        ):

            data["Adiantamento_Minutos"] = int(
                (
                    data["ETA_Dt"]
                    - data["Chegada_Real_Dt"]
                ).total_seconds() / 60
            )

        # ----------------------------------------------------
        # CORREÇÃO DE DISTÂNCIA
        # ----------------------------------------------------

        if data["UF"] == "MA":

            data["Distancia_Corrigida"] = (
                data["Distancia_Raw"]
                * FATOR_CORRECAO_MA
            )

            data["Fator_Correcao"] = "(MA +35%)"

        else:

            data["Distancia_Corrigida"] = (
                data["Distancia_Raw"]
                * FATOR_CORRECAO_GERAL
            )

            data["Fator_Correcao"] = "(geral +25%)"

        # ----------------------------------------------------
        # STATUS OPERACIONAL
        # ----------------------------------------------------

        ja_chegou = (
            data["Chegada_Real_Dt"] is not None
        )

        eta_dt = data["ETA_Dt"]

        if ja_chegou:

            data["Status_Operacional"] = "Concluído"
            data["Classificacao_Desempenho"] = "Concluído"

            if eta_dt:

                diff_min = int(
                    (
                        data["Chegada_Real_Dt"]
                        - eta_dt
                    ).total_seconds() / 60
                )

                if diff_min > 0:

                    data["Motivo_Risco"] = (
                        f"Chegou {diff_min} min após "
                        f"o ETA programado."
                    )

                elif diff_min < 0:

                    data["Motivo_Risco"] = (
                        f"Chegou {abs(diff_min)} min antes "
                        f"do ETA programado."
                    )

                else:

                    data["Motivo_Risco"] = (
                        "Chegou no horário programado."
                    )

        elif (
            eta_dt
            and data["Distancia_Raw"] > 0
        ):

            # =================================================
            # REGRA MATEMÁTICA OFICIAL
            #
            # tempo disponível = ETA - agora
            # tempo necessário = distância corrigida / 60
            # margem = disponível - necessário
            # =================================================

            tempo_disp_min = (
                eta_dt - agora_br
            ).total_seconds() / 60

            tempo_necessario_min = (
                data["Distancia_Corrigida"]
            )

            data["Margem_Minutos"] = int(
                tempo_disp_min
                - tempo_necessario_min
            )

            # =================================================
            # DELAY
            #
            # ETA passou OU margem <= 0
            # =================================================

            if (
                tempo_disp_min <= 0
                or data["Margem_Minutos"] <= 0
            ):

                data["Status_Operacional"] = "Delay"
                data["Classificacao_Desempenho"] = "Delay"

                data["Motivo_Risco"] = (
                    formatar_deficit_tempo(
                        data["Margem_Minutos"]
                    )
                )

            else:

                # =============================================
                # TENDÊNCIA
                # =============================================

                (
                    tem_tendencia,
                    texto_motivo
                ) = avaliar_tendencia(data)

                if tem_tendencia:

                    data["Status_Operacional"] = "Tendência"
                    data["Classificacao_Desempenho"] = "No prazo"
                    data["Motivo_Risco"] = texto_motivo

                else:

                    data["Status_Operacional"] = "Normal"
                    data["Classificacao_Desempenho"] = "No prazo"

        else:

            if data["Sem_Sinal"]:

                data["Status_Operacional"] = "Tendência"

                data["Motivo_Risco"] = (
                    f"Sem sinal desde "
                    f"{data['Ultima_Atualizacao_Str']}."
                )

        parsed_data.append(data)

    df_result = pd.DataFrame(parsed_data)

    return df_result


# ============================================================
# RELATÓRIO
# ============================================================

def generate_report_text(df):
    """Gera o relatório operacional em linguagem direta e organizada."""

    agora = agora_brasilia()
    data_hora_str = agora.strftime("%d/%m/%Y · %H:%M")

    df = df.copy()

    df["Em_Rota"] = df.apply(esta_em_rota, axis=1)
    df["Minutos_Ate_ETA"] = df["ETA_Dt"].apply(
        lambda d: (d - agora).total_seconds() / 60 if pd.notna(d) else None
    )

    report = f"# Monitoramento Operacional — {data_hora_str}\n\n"
    report += f"Total no recorte: {len(df)} LTs.\n\n"

    report += "## Como o sistema está avaliando as LTs\n\n"
    report += "• ETA oficial: considerado somente o primeiro horário informado.\n"
    report += "• Cálculo de deslocamento: 60 km/h, aproximadamente 1 km por minuto.\n"
    report += "• Distância corrigida: +25% nas rotas gerais e +35% nas rotas para MA.\n"
    report += "• Delay: ETA já vencido ou margem matemática igual/menor que zero.\n"
    report += "• Tendência: somente quando a projeção de 60 minutos deixa a margem em até 30 minutos ou negativa.\n"
    report += "• Parada programada de intervalo/refeição não é aceita como justificativa final de atraso; nesses casos, o relatório pede investigação da razão real.\n\n"

    # --------------------------------------------------------
    # EARLY PENDENTE
    # --------------------------------------------------------
    report += "## 📞 EARLY — marcar contato\n\n"

    early_pendente = df[
        (df["Em_Range_Turno"] == True)
        & (df["Early_Pendente"] == True)
        & df["Em_Rota"]
    ].copy()

    if early_pendente.empty:
        report += "Todos os veículos do range já foram contatados para Early, ou não há Early pendente neste recorte.\n\n"
    else:
        report += "Estas LTs estão no range do turno e ainda aparecem como \"Marcar contato\":\n\n"
        for _, row in early_pendente.iterrows():
            report += (
                f"• {row['LT_Full']} — {row['Motorista']} | "
                f"ETA: {row['ETA']} | Destino: {row['Destino']} | "
                f"Distância: {row['Distancia_Raw']} km.\n"
            )
        report += "Ação: realizar o contato de Early e registrar o aviso no dashboard.\n\n"

    # --------------------------------------------------------
    # DELAY
    # --------------------------------------------------------
    report += "## 🚨 LTs em Delay\n\n"

    criticos = df[
        (df["Status_Operacional"] == "Delay") &
        (~df["Sem_Sinal"])
    ].copy()

    if criticos.empty:
        report += "Nenhuma LT está em Delay neste recorte.\n\n"
    else:
        for _, row in criticos.iterrows():
            report += f"### 🔴 {row['LT_Full']} — {row['Motorista']}\n"
            report += f"ETA: {row['ETA']} | Pacotes: {row['Pacotes']:,} | Distância: {row['Distancia_Raw']} km\n"
            report += f"Velocidade atual: {row['Velocidade']} km/h.\n"

            if row["Status_Movimento"] == "Parado":
                report += f"Está parado há {row['Tempo_Str']}.\n"

            if row["Motivo_Parada"]:
                report += f"Ocorrência: {motivo_para_exibicao(row['Motivo_Parada'])}.\n"

            report += f"Situação matemática: {row['Motivo_Risco']}\n\n"

    # --------------------------------------------------------
    # TENDÊNCIA
    # --------------------------------------------------------
    report += "## ⚠️ Tendência de atraso\n\n"

    riscos_todos = df[
        (df["Status_Operacional"] == "Tendência") &
        (~df["Sem_Sinal"])
    ].copy()

    riscos = riscos_todos[
        riscos_todos.apply(deve_alertar_tendencia, axis=1)
    ].copy()

    if riscos.empty:
        report += "Nenhuma LT apresenta tendência de atraso relevante neste recorte.\n\n"
    else:
        for _, row in riscos.iterrows():
            report += f"### 🟠 {row['LT_Full']} — {row['Motorista']}\n"
            report += f"ETA: {row['ETA']} | Pacotes: {row['Pacotes']:,} | Distância: {row['Distancia_Raw']} km\n"
            report += f"{row['Motivo_Risco']}\n"
            if row["Motivo_Parada"]:
                report += f"Ocorrência registrada: {motivo_para_exibicao(row['Motivo_Parada'])}.\n"
            report += "Ação: acompanhar a evolução da margem na próxima atualização.\n\n"

    # --------------------------------------------------------
    # HUB / XPT
    # --------------------------------------------------------
    report += "## 🏭 Atenção para HUB / XPT\n\n"
    report += f"Para destinos com HUB ou XPT no nome, a referência é chegar com pelo menos {MINUTOS_ANTECEDENCIA_HUB_XPT} minutos de antecedência em relação ao ETA.\n\n"

    hub_xpt_df = df[
        df["Em_Rota"] &
        df["ETA_Dt"].notna() &
        (df["Distancia_Raw"] > 0) &
        df["Destino"].apply(destino_eh_hub_xpt) &
        (df["Margem_Minutos"] < MINUTOS_ANTECEDENCIA_HUB_XPT)
    ].copy()

    if hub_xpt_df.empty:
        report += "Nenhuma LT para HUB/XPT está abaixo da antecedência operacional de 1 hora.\n\n"
    else:
        for _, row in hub_xpt_df.iterrows():
            margem = int(row["Margem_Minutos"])
            if margem < 0:
                situacao = f"já sem margem matemática ({formatar_deficit_tempo(margem)})"
            else:
                situacao = f"margem atual de aproximadamente {margem} minutos"
            report += f"• {row['LT_Full']} — {row['Motorista']} | Destino: {row['Destino']} | {situacao}.\n"
        report += "\n"

    # --------------------------------------------------------
    # SEM SINAL
    # --------------------------------------------------------
    report += "## 🚨 Sem sinal\n\n"
    sem_sinal_df = df[df["Sem_Sinal"] == True].copy()

    if sem_sinal_df.empty:
        report += "Nenhum veículo está sem sinal.\n\n"
    else:
        for _, row in sem_sinal_df.iterrows():
            report += f"• {row['LT_Full']} — {row['Motorista']} | última atualização: {row['Ultima_Atualizacao_Str']}.\n"
        report += "Ação: localizar o veículo e restabelecer a comunicação.\n\n"

    # --------------------------------------------------------
    # PARADOS
    # --------------------------------------------------------
    report += "## 🛑 Veículos parados\n\n"
    parados_df = df[df["Status_Movimento"] == "Parado"].sort_values(
        by="Tempo_Horas", ascending=False
    )

    if parados_df.empty:
        report += "Nenhum veículo está parado no momento.\n\n"
    else:
        report += "| LT | Pacotes | Tempo parado | Situação |\n| --- | ---: | ---: | --- |\n"
        for _, row in parados_df.iterrows():
            motivo = motivo_para_exibicao(row["Motivo_Parada"]) if row["Motivo_Parada"] else "Parado"
            report += f"| {row['LT_Full']} | {row['Pacotes']:,} | {row['Tempo_Str']} | {row['Status_Operacional']} — {motivo} |\n"
        report += "\n"

    # --------------------------------------------------------
    # TOP 5
    # --------------------------------------------------------
    report += "## 📦 Top 5 em volume de pacotes\n\n"
    top5 = df.sort_values(by="Pacotes", ascending=False).head(5)
    report += "| # | LT | Motorista | Pacotes | Situação |\n| -: | --- | --- | ---: | --- |\n"
    for i, (_, row) in enumerate(top5.iterrows(), 1):
        report += f"| {i} | {row['LT_Full']} | {row['Motorista']} | {row['Pacotes']:,} | {row['Status_Operacional']} |\n"
    report += "\n"

    # --------------------------------------------------------
    # PONTOS PRÓXIMOS DA BASE
    # --------------------------------------------------------
    report += "## 📍 LTs próximas do destino / base\n\n"
    proximos_base = df[
        df["Em_Rota"] &
        (df["Distancia_Raw"] <= KM_ALERTA_LOCALIZACAO_BASE + TOLERANCIA_KM_LOCALIZACAO_BASE)
    ].copy()

    if proximos_base.empty:
        report += "Nenhuma LT está dentro do raio de atenção da base neste recorte.\n\n"
    else:
        for _, row in proximos_base.iterrows():
            endereco = BASE_ENDERECOS.get(row["Destino"])
            texto = f"• {row['LT_Full']} — {row['Motorista']} | {row['Distancia_Raw']} km do destino {row['Destino']}."
            if endereco:
                texto += f" Local da base: {endereco}."
            else:
                texto += " Confirmar com o condutor o local correto da base."
            report += texto + "\n"
        report += "\n"

    # --------------------------------------------------------
    # PLANO DE AÇÃO
    # --------------------------------------------------------
    report += "## 🎯 Plano de ação imediato\n\n"

    delays_alertaveis = criticos[
        criticos.apply(deve_alertar_tendencia, axis=1)
    ].copy()

    tendencias_alertaveis = riscos_todos[
        riscos_todos.apply(deve_alertar_tendencia, axis=1)
    ].copy()

    # A lista de tendências pode ficar vazia em alguns recortes.
    # Não acessar colunas diretamente nesse caso evita KeyError e mantém
    # o Plano de Ação funcionando mesmo sem nenhuma tendência alertável.
    tendencias_urgentes = tendencias_alertaveis.iloc[0:0].copy()

    if not tendencias_alertaveis.empty:
        mascara_tendencia_urgente = pd.Series(
            False,
            index=tendencias_alertaveis.index
        )

        if "Margem_Minutos" in tendencias_alertaveis.columns:
            mascara_tendencia_urgente = (
                pd.to_numeric(
                    tendencias_alertaveis["Margem_Minutos"],
                    errors="coerce"
                ).fillna(999999) <= 30
            )

        if "Tempo_Horas" in tendencias_alertaveis.columns:
            mascara_tendencia_urgente = (
                mascara_tendencia_urgente |
                (
                    pd.to_numeric(
                        tendencias_alertaveis["Tempo_Horas"],
                        errors="coerce"
                    ).fillna(0) >= LIMIAR_PARADO_LONGO_HORAS
                )
            )

        tendencias_urgentes = tendencias_alertaveis[
            mascara_tendencia_urgente
        ].copy()

    urgentes = pd.concat(
        [delays_alertaveis, sem_sinal_df, tendencias_urgentes],
        ignore_index=True
    ).drop_duplicates(subset=["LT_Full"])

    report += "### 🔴 Cobrar agora\n\n"
    if urgentes.empty:
        report += "Nenhuma unidade exige cobrança imediata.\n\n"
    else:
        for _, row in urgentes.iterrows():
            detalhes = []
            if row["Sem_Sinal"]:
                detalhes.append(f"sem sinal desde {row['Ultima_Atualizacao_Str']}")
            elif row["Status_Operacional"] == "Delay":
                detalhes.append(row["Motivo_Risco"] or "em Delay")
            else:
                detalhes.append(row["Motivo_Risco"] or "margem apertada na projeção de 60 minutos")
            if row["Motivo_Parada"]:
                detalhes.append(f"ocorrência: {motivo_para_exibicao(row['Motivo_Parada'])}")
            report += f"• {row['LT_Full']} — {row['Motorista']}: " + "; ".join(detalhes) + ".\n"
        report += "\n"

    report += "### 🟠 Monitorar nos próximos 30 minutos\n\n"
    monitorar = tendencias_alertaveis[
        ~tendencias_alertaveis["LT_Full"].isin(urgentes["LT_Full"])
    ].copy()
    if monitorar.empty:
        report += "Nenhuma LT adicional exige acompanhamento intensivo nos próximos 30 minutos.\n\n"
    else:
        for _, row in monitorar.iterrows():
            report += f"• {row['LT_Full']} — {row['Motorista']} | projeção de margem em 60 minutos: {int(calcular_margem_projetada(row, 60) or 0)} min.\n"
        report += "\n"

    report += "### 🟡 Escalar se não houver evolução\n\n"
    escalar = df[
        df["Em_Rota"] &
        (df["Status_Movimento"] == "Parado") &
        (df["Tempo_Horas"] >= 1)
    ].copy()
    escalar = escalar[
        ~escalar["LT_Full"].isin(urgentes["LT_Full"])
    ]
    if escalar.empty:
        report += "Nenhuma unidade adicional está nesta condição.\n\n"
    else:
        for _, row in escalar.iterrows():
            report += f"• {row['LT_Full']} — {row['Motorista']} | parado há {row['Tempo_Str']}.\n"
        report += "\n"

    report += "### 🟢 Sem necessidade de ação\n\n"
    normais = df[
        df["Em_Rota"] &
        (df["Status_Operacional"] == "Normal") &
        (~df["Sem_Sinal"])
    ]
    report += f"{len(normais)} LT(s) estão em condição normal no momento.\n\n"

    # --------------------------------------------------------
    # PORTARIA SP/RJ
    # --------------------------------------------------------
    report += "### 🚪 Solicitar liberação de portaria — SP/RJ\n\n"
    report += "Acionar somente quando o veículo estiver próximo do destino e realmente precisar da liberação.\n\n"

    portaria_df = df[
        df["Em_Rota"] &
        df["UF"].isin(["SP", "RJ"]) &
        (df["Distancia_Raw"] >= KM_ALERTA_PORTARIA_SP_RJ - TOLERANCIA_KM_PORTARIA) &
        (df["Distancia_Raw"] <= KM_ALERTA_PORTARIA_SP_RJ + TOLERANCIA_KM_PORTARIA) &
        df["Minutos_Ate_ETA"].notnull() &
        (df["Minutos_Ate_ETA"] <= MINUTOS_PROXIMO_ETA_PORTARIA)
    ].copy()

    if portaria_df.empty:
        report += "Nenhuma LT está neste intervalo neste recorte.\n\n"
    else:
        for _, row in portaria_df.iterrows():
            report += f"• {row['LT_Full']} — {row['Motorista']} | {row['Distancia_Raw']} km do destino | ETA em aproximadamente {int(row['Minutos_Ate_ETA'])} min.\n"
        report += "\n"

    # --------------------------------------------------------
    # RESUMO
    # --------------------------------------------------------
    report += "## Resumo simplificado\n\n"
    report += "Delay:\n"
    if criticos.empty:
        report += "Nenhuma LT.\n"
    else:
        for _, row in criticos.iterrows():
            report += f"{row['LT_Full']}\n"

    report += "\nTendência de atraso:\n"
    if riscos.empty:
        report += "Nenhuma LT.\n"
    else:
        for _, row in riscos.iterrows():
            report += f"{row['LT_Full']}\n"

    report += "\nSem sinal:\n"
    if sem_sinal_df.empty:
        report += "Nenhuma LT.\n"
    else:
        for _, row in sem_sinal_df.iterrows():
            report += f"{row['LT_Full']}\n"

    return report


# ============================================================
# INTERFACE
# ============================================================

st.markdown(
    "<h1 style='text-align: center; color: #ee4d2d;'>"
    "🚛 Torre de Controle — Gestão Inteligente de Frotas"
    "</h1>",
    unsafe_allow_html=True
)

st.markdown(
    "<p style='text-align: center; color: #64748b;'>"
    "Monitoramento preditivo, comportamental e logístico avançado em tempo real."
    "</p>",
    unsafe_allow_html=True
)

st.markdown("<br>", unsafe_allow_html=True)


# ============================================================
# DATA DO PLANTÃO
# ============================================================

st.markdown(
    "### 📅 Configuração do Turno"
)

col_s1, col_s2 = st.columns([3, 7])

with col_s1:

    data_hoje_str = (
        datetime.utcnow()
        .strftime("%d/%m/%Y")
    )

    data_plantao_str = st.text_input(
        "Data de Início do Plantão / Turno D (DD/MM/AAAA):",
        value=data_hoje_str,
        placeholder="Ex: 30/09/2026"
    )


# ============================================================
# SESSION STATE
# ============================================================

if "relatorio_gerado" not in st.session_state:
    st.session_state["relatorio_gerado"] = ""

if "df_parsed" not in st.session_state:
    st.session_state["df_parsed"] = None


# ============================================================
# ENTRADA
# ============================================================

with st.container():

    st.markdown(
        "### 📥 Entrada de Dados Operacionais"
    )

    raw_text = st.text_area(
        "Cole abaixo o texto extraído do Losung Web:",
        height=300,
        placeholder="Cole o resumo completo do dashboard aqui."
    )

    col_b1, _ = st.columns([2, 8])

    with col_b1:

        gerar_btn = st.button(
            "Gerar Relatório Analítico"
        )


# ============================================================
# GERAÇÃO
# ============================================================

if gerar_btn:

    if raw_text.strip():

        df_parsed = process_data_local(
            raw_text,
            data_plantao_str
        )

        if df_parsed.empty:

            st.error(
                "⚠️ Nenhum dado válido encontrado para este texto colado."
            )

            st.info(
                "O parser espera que cada LT apareça em uma nova linha "
                "começando com 'LT'."
            )

            st.session_state["relatorio_gerado"] = ""
            st.session_state["df_parsed"] = None

        else:

            st.session_state["relatorio_gerado"] = (
                generate_report_text(
                    df_parsed
                )
            )

            st.session_state["df_parsed"] = (
                df_parsed
            )

    else:

        st.warning(
            "⚠️ Insira os dados na caixa de texto acima antes de gerar."
        )


# ============================================================
# DASHBOARD RESULTADO
# ============================================================

if st.session_state["relatorio_gerado"]:

    df = st.session_state["df_parsed"]

    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown(
        "### 📊 Indicadores Operacionais"
    )

    total_lts = len(df)

    qtd_early_pendente = len(
        df[
            (df["Em_Range_Turno"] == True)
            & (df["Early_Pendente"] == True)
            & df.apply(esta_em_rota, axis=1)
        ]
    )

    qtd_normal = len(
        df[
            df["Status_Operacional"].isin(
                ["Normal", "Tendência"]
            )
        ]
    )

    qtd_parados = len(
        df[
            df["Status_Movimento"] == "Parado"
        ]
    )

    qtd_tendencia = len(
        df[
            df["Status_Operacional"] == "Tendência"
        ]
    )

    qtd_delays = len(
        df[
            df["Status_Operacional"] == "Delay"
        ]
    )

    qtd_concluidas = len(
        df[
            df["Status_Operacional"] == "Concluído"
        ]
    )

    k1, k2, k3, k4, k5, k6 = st.columns(6)

    with k1:

        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='metric-title'>Total de LTs</div>"
            f"<div class='metric-value'>{total_lts}</div>"
            f"</div>",
            unsafe_allow_html=True
        )

    with k2:

        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='metric-title'>No Prazo</div>"
            f"<div class='metric-value' style='color: #10b981;'>"
            f"{qtd_normal}"
            f"</div></div>",
            unsafe_allow_html=True
        )

    with k3:

        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='metric-title'>Veículos Parados</div>"
            f"<div class='metric-value' style='color: #f59e0b;'>"
            f"{qtd_parados}"
            f"</div></div>",
            unsafe_allow_html=True
        )

    with k4:

        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='metric-title'>Tendência</div>"
            f"<div class='metric-value' style='color: #d97706;'>"
            f"{qtd_tendencia}"
            f"</div></div>",
            unsafe_allow_html=True
        )

    with k5:

        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='metric-title'>Delays</div>"
            f"<div class='metric-value' style='color: #dc2626;'>"
            f"{qtd_delays}"
            f"</div></div>",
            unsafe_allow_html=True
        )

    with k6:

        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='metric-title'>Concluídas</div>"
            f"<div class='metric-value' style='color: #64748b;'>"
            f"{qtd_concluidas}"
            f"</div></div>",
            unsafe_allow_html=True
        )

    st.markdown("<br><br>", unsafe_allow_html=True)


    # ========================================================
    # ABAS
    # ========================================================

    (
        tab_relatorio,
        tab_performance,
        tab_atrasadas,
        tab_parados,
        tab_tendencia,
        tab_top10,
        tab_tabela
    ) = st.tabs(
        [
            "📋 Relatório Formatado",
            "🌐 Performance por Rota (UF)",
            "🔴 LTs Atrasadas",
            "🛑 Veículos Parados",
            "⚠️ Tendência de Atraso",
            "📦 Top 10 Volumes",
            "📊 Tabela Analítica Completa"
        ]
    )


    # ========================================================
    # RELATÓRIO
    # ========================================================

    with tab_relatorio:

        st.markdown(
            "#### 📋 Pré-visualização do Relatório"
        )

        st.text_area(
            "Texto formatado completo:",
            value=st.session_state["relatorio_gerado"],
            height=600
        )


    # ========================================================
    # PERFORMANCE
    # ========================================================

    with tab_performance:

        st.markdown(
            "#### 🌐 Performance por Rota (UF)"
        )

        st.info(
            f"Exibindo LTs ainda em rota com ETA dentro do "
            f"turno: **19:00 de {data_plantao_str} até "
            f"15:00 do dia seguinte**."
        )

        try:

            dt_base = datetime.strptime(
                data_plantao_str,
                "%d/%m/%Y"
            )

            inicio_turno = dt_base.replace(
                hour=19,
                minute=0,
                second=0,
                microsecond=0
            )

            fim_turno = (
                inicio_turno
                + timedelta(hours=20)
            )

            df_perf = df[
                df["ETA_Dt"].notnull()
                & (
                    df["ETA_Dt"]
                    >= inicio_turno
                )
                & (
                    df["ETA_Dt"]
                    <= fim_turno
                )
                & df.apply(
                    esta_em_rota,
                    axis=1
                )
            ].copy()

        except ValueError:

            st.error(
                f"⚠️ Data inválida: "
                f"'{data_plantao_str}'."
            )

            df_perf = df.iloc[0:0].copy()


        if not df_perf.empty:

            df_perf[
                "Classificacao_Performance"
            ] = df_perf.apply(
                classificar_performance,
                axis=1
            )

            total_perf = len(df_perf)

            qtd_no_prazo_total = len(
                df_perf[
                    df_perf["Classificacao_Performance"]
                    == "No prazo"
                ]
            )

            qtd_delay_total = len(
                df_perf[
                    df_perf["Classificacao_Performance"]
                    == "Delay"
                ]
            )

            qtd_early_total = len(
                df_perf[
                    df_perf["Classificacao_Performance"]
                    == "Early"
                ]
            )

            st.markdown(
                "##### 📊 Resumo do Turno"
            )

            r1, r2, r3, r4 = st.columns(4)

            with r1:

                st.markdown(
                    f"<div class='metric-card'>"
                    f"<div class='metric-title'>Total em Rota</div>"
                    f"<div class='metric-value'>{total_perf}</div>"
                    f"</div>",
                    unsafe_allow_html=True
                )

            with r2:

                st.markdown(
                    f"<div class='metric-card'>"
                    f"<div class='metric-title'>No Prazo</div>"
                    f"<div class='metric-value'>{qtd_no_prazo_total}</div>"
                    f"</div>",
                    unsafe_allow_html=True
                )

            with r3:

                st.markdown(
                    f"<div class='metric-card'>"
                    f"<div class='metric-title'>Delay</div>"
                    f"<div class='metric-value'>{qtd_delay_total}</div>"
                    f"</div>",
                    unsafe_allow_html=True
                )

            with r4:

                st.markdown(
                    f"<div class='metric-card'>"
                    f"<div class='metric-title'>Early</div>"
                    f"<div class='metric-value'>{qtd_early_total}</div>"
                    f"</div>",
                    unsafe_allow_html=True
                )

            ufs_disponiveis = sorted(
                df_perf["UF"].unique()
            )

            for uf in ufs_disponiveis:

                df_uf = df_perf[
                    df_perf["UF"] == uf
                ]

                performance_pct, _ = (
                    calcular_performance_rota(
                        df_uf
                    )
                )

                qtd_no_prazo = len(
                    df_uf[
                        df_uf["Classificacao_Performance"]
                        == "No prazo"
                    ]
                )

                qtd_delay = len(
                    df_uf[
                        df_uf["Classificacao_Performance"]
                        == "Delay"
                    ]
                )

                qtd_early = len(
                    df_uf[
                        df_uf["Classificacao_Performance"]
                        == "Early"
                    ]
                )

                st.markdown("---")

                st.markdown(
                    f"### 📍 Rota: **{uf}**"
                )

                col_uf1, col_uf2 = st.columns(
                    [4, 6]
                )

                with col_uf1:

                    st.markdown(
                        f"* **Total de LTs:** `{len(df_uf)}`"
                    )

                    st.markdown(
                        f"* **Volume:** "
                        f"`{df_uf['Pacotes'].sum():,}`"
                    )

                    st.markdown(
                        f"* 🟢 **No Prazo:** `{qtd_no_prazo}`"
                    )

                    st.markdown(
                        f"* 🔴 **Delay:** `{qtd_delay}`"
                    )

                    st.markdown(
                        f"* 🔵 **Early:** `{qtd_early}`"
                    )

                    st.markdown(
                        f"<div class='metric-card'>"
                        f"<div class='metric-title'>Performance da Rota</div>"
                        f"<div class='metric-value'>"
                        f"{performance_pct:.1f}%"
                        f"</div></div>",
                        unsafe_allow_html=True
                    )

                with col_uf2:

                    fig_uf = px.pie(
                        df_uf,
                        names="Classificacao_Performance",
                        title=f"Distribuição — {uf}",
                        color="Classificacao_Performance",
                        color_discrete_map={
                            "No prazo": "#10b981",
                            "Delay": "#dc2626",
                            "Early": "#3b82f6"
                        },
                        hole=0.4
                    )

                    fig_uf.update_layout(
                        margin=dict(
                            t=30,
                            b=10,
                            l=10,
                            r=10
                        ),
                        height=240
                    )

                    st.plotly_chart(
                        fig_uf,
                        use_container_width=True,
                        key=f"pie_{uf}"
                    )

                impactantes = df_uf[
                    df_uf[
                        "Classificacao_Performance"
                    ].isin(
                        ["Delay", "Early"]
                    )
                ].copy()

                if not impactantes.empty:

                    st.markdown(
                        "**🚨 LTs que impactaram a performance:**"
                    )

                    tabela_impacto = impactantes[
                        [
                            "LT_Full",
                            "Motorista",
                            "Classificacao_Performance",
                            "Motivo_Parada",
                            "ETA",
                            "Distancia_Raw",
                            "Velocidade"
                        ]
                    ].rename(
                        columns={
                            "LT_Full": "LT",
                            "Classificacao_Performance": "Situação",
                            "Motivo_Parada": "Ocorrência",
                            "Distancia_Raw": "Distância (km)"
                        }
                    )

                    tabela_impacto[
                        "Ocorrência"
                    ] = tabela_impacto[
                        "Ocorrência"
                    ].replace(
                        "",
                        "—"
                    )

                    st.dataframe(
                        tabela_impacto,
                        use_container_width=True,
                        hide_index=True
                    )

        else:

            st.warning(
                "Nenhuma LT em rota dentro "
                "do range do Turno D."
            )


    # ========================================================
    # ATRASADAS
    # ========================================================

    with tab_atrasadas:

        st.markdown(
            "#### 🔴 LTs Atrasadas"
        )

        df_atrasadas = df[
            df["Status_Operacional"] == "Delay"
        ]

        if not df_atrasadas.empty:

            tabela_atraso = df_atrasadas[
                [
                    "LT_Full",
                    "Motorista",
                    "UF",
                    "ETA",
                    "Motivo_Parada",
                    "Motivo_Risco",
                    "Pacotes",
                    "Velocidade",
                    "Distancia_Raw"
                ]
            ].rename(
                columns={
                    "LT_Full": "LT",
                    "ETA": "ETA Destino",
                    "Motivo_Parada": "Motivo da Ocorrência",
                    "Motivo_Risco": "Detalhe do Atraso",
                    "Distancia_Raw": "Distância (km)"
                }
            )

            tabela_atraso[
                "Motivo da Ocorrência"
            ] = tabela_atraso[
                "Motivo da Ocorrência"
            ].apply(motivo_para_exibicao)

            st.dataframe(
                tabela_atraso,
                use_container_width=True,
                hide_index=True
            )

        else:

            st.success(
                "Nenhuma LT atrasada neste recorte."
            )


    # ========================================================
    # PARADOS
    # ========================================================

    with tab_parados:

        st.markdown(
            "#### 🛑 Veículos Parados"
        )

        df_parados = df[
            df["Status_Movimento"] == "Parado"
        ]

        if not df_parados.empty:

            st.dataframe(
                df_parados[
                    [
                        "LT_Full",
                        "Motorista",
                        "Pacotes",
                        "Tempo_Str",
                        "Destino",
                        "Motivo_Parada"
                    ]
                ].rename(
                    columns={
                        "LT_Full": "LT"
                    }
                ),
                use_container_width=True,
                hide_index=True
            )

        else:

            st.success(
                "Nenhum veículo parado."
            )


    # ========================================================
    # TENDÊNCIA
    # ========================================================

    with tab_tendencia:

        st.markdown(
            "#### ⚠️ Tendência de Atraso"
        )

        df_tendencia = df[
            df["Status_Operacional"] == "Tendência"
        ].copy()

        df_tendencia = df_tendencia[
            df_tendencia.apply(
                deve_alertar_tendencia,
                axis=1
            )
        ].copy()

        if not df_tendencia.empty:

            st.dataframe(
                df_tendencia[
                    [
                        "LT_Full",
                        "Motorista",
                        "Pacotes",
                        "ETA",
                        "Margem_Minutos",
                        "Motivo_Risco"
                    ]
                ].rename(
                    columns={
                        "LT_Full": "LT"
                    }
                ),
                use_container_width=True,
                hide_index=True
            )

        else:

            st.success(
                "Nenhuma tendência de atraso."
            )


    # ========================================================
    # TOP 10
    # ========================================================

    with tab_top10:

        st.markdown(
            "#### 📦 Top Volumes"
        )

        st.dataframe(
            df.sort_values(
                by="Pacotes",
                ascending=False
            ).head(10)[
                [
                    "LT_Full",
                    "Motorista",
                    "Pacotes",
                    "ETA",
                    "Destino"
                ]
            ].rename(
                columns={
                    "LT_Full": "LT"
                }
            ),
            use_container_width=True,
            hide_index=True
        )


    # ========================================================
    # TABELA COMPLETA
    # ========================================================

    with tab_tabela:

        st.markdown(
            "#### 📊 Tabela Analítica Completa"
        )

        st.dataframe(
            df[
                [
                    "LT_Full",
                    "Motorista",
                    "Pacotes",
                    "UF",
                    "Status_Operacional",
                    "Status_Movimento",
                    "Velocidade",
                    "ETA",
                    "Chegada_Real",
                    "Margem_Minutos",
                    "Destino"
                ]
            ].rename(
                columns={
                    "LT_Full": "LT"
                }
            ),
            use_container_width=True,
            hide_index=True
        )
