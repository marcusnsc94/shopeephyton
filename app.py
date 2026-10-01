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

# Correção de distância
# Regra geral: +25%
# Maranhão: +35%
FATOR_CORRECAO_GERAL = 1.25
FATOR_CORRECAO_MA = 1.35

# Velocidade operacional de referência
VELOCIDADE_REFERENCIA_KMH = 60

# Projeção utilizada para avaliar tendência
JANELA_PROJECAO_1_MIN = 30
JANELA_PROJECAO_2_MIN = 60

# Margens utilizadas apenas para graduar a TENDÊNCIA.
# Não determinam Delay.
MARGEM_CRITICA_MIN = 60
MARGEM_MODERADA_MIN = 120
MARGEM_LEVE_MIN = 240

# Parada considerada prolongada para fins de alerta
PARADA_PROLONGADA_HORAS = 1.0

# Ocorrência neutra
OCORRENCIAS_NEUTRAS = {
    "Parada programada — intervalo/refeição"
}

# Para uma ocorrência já explicada:
# não repetir cobrança operacional, salvo proximidade da base
# ou parada muito longa.
LIMIAR_PARADO_LONGO_HORAS = 2.0

# HUB/XPT:
# avisar quando a projeção não permitir pelo menos 1h
# de antecedência em relação ao ETA.
MINUTOS_ANTECEDENCIA_HUB_XPT = 60

# Endereços conhecidos das bases.
# Preencher quando necessário.
BASE_ENDERECOS = {
    # "SOC-PE2": "Rua Exemplo, 123 - Cabo de Santo Agostinho/PE",
    # "SOC-PE4": "Av. Exemplo, 456 - Jaboatão dos Guararapes/PE",
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

def parse_duration(time_str):
    try:
        parts = time_str.split(':')
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
        if not eta_str or eta_str in ('-', '—'):
            return None

        return datetime.strptime(
            f"{eta_str}/{ano_atual}",
            "%d/%m %H:%M/%Y"
        )

    except Exception:
        return None


def extract_uf(destino):
    """
    Extrai a UF do código do destino.

    Exemplos:
    SOC-PE2 -> PE
    HUB-LAL-01 -> AL
    LPA -> PA
    LMA -> MA
    """

    if not destino:
        return "OUTROS"

    dest_upper = str(destino).upper()

    ufs = [
        "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
        "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
        "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"
    ]

    # Exemplo: LPA / LMA / LAL
    m = re.search(
        r'(?:^|-)L([A-Z]{2})(?=\d|-|$)',
        dest_upper
    )

    if m and m.group(1) in ufs:
        return m.group(1)

    # Exemplo: SOC-PE2 / SOC-SP8
    m = re.search(
        r'(?:^|-)([A-Z]{2})(?=\d|-|$)',
        dest_upper
    )

    if m and m.group(1) in ufs:
        return m.group(1)

    return "OUTROS"


def destino_eh_hub_xpt(destino):
    """
    Identifica nomenclatura HUB ou XPT no destino.
    """

    if not destino:
        return False

    texto = str(destino).upper()

    return bool(
        re.search(r'\bHUB\b', texto)
        or re.search(r'\bXPT\b', texto)
        or "HUB-" in texto
        or "XPT-" in texto
        or texto.startswith("HUB")
        or texto.startswith("XPT")
    )


# ============================================================
# NOVA LÓGICA DE TENDÊNCIA
# ============================================================

def calcular_perda_margem_projetada(data, minutos_projecao):
    """
    Calcula quanto da margem seria consumido caso o comportamento
    atual continue durante a janela analisada.

    Regra:
    - referência = 60 km/h
    - parado = 0 km/h
    - velocidade abaixo de 60 = consumo de margem
    - velocidade >= 60 = não consome margem pela velocidade
    """

    velocidade = float(data.get("Velocidade", 0) or 0)

    parado = (
        data.get("Status_Movimento") == "Parado"
        and float(data.get("Tempo_Horas", 0) or 0) > 0
    )

    if parado:
        velocidade_projetada = 0
    else:
        velocidade_projetada = velocidade

    deficit_velocidade = max(
        0,
        VELOCIDADE_REFERENCIA_KMH - velocidade_projetada
    )

    # Como 60 km/h = 1 km/min,
    # a diferença de velocidade em km/h equivale
    # numericamente à perda de minutos de margem por hora.
    perda_margem = deficit_velocidade * (minutos_projecao / 60)

    return perda_margem


def avaliar_tendencia(data):
    """
    Metodologia oficial:

    1. Delay é decidido matematicamente antes.
    2. Só existe tendência se a margem ainda for positiva.
    3. Ocorrência sozinha não cria tendência.
    4. Parada sozinha, com margem confortável, não cria tendência.
    5. Velocidade baixa sozinha, com margem confortável, não cria tendência.
    6. Tendência aparece quando o comportamento atual está consumindo
       a margem de forma relevante.
    7. A pergunta operacional é:
       "Se continuar exatamente como está por mais 30–60 minutos,
        a margem continuará suficiente?"

    Retorna:
        True/False
        texto explicativo
    """

    margem = float(data.get("Margem_Minutos", 999) or 0)

    # Se a margem já acabou, isso não é tendência.
    # É Delay.
    if margem <= 0:
        return False, ""

    motivo = str(data.get("Motivo_Parada") or "").strip()

    motivo_eh_neutro = (
        not motivo
        or motivo in OCORRENCIAS_NEUTRAS
    )

    sinal_parado = (
        data.get("Status_Movimento") == "Parado"
        and float(data.get("Tempo_Horas", 0) or 0) > 0
    )

    velocidade = float(data.get("Velocidade", 0) or 0)

    # Velocidade abaixo da referência gera consumo de margem.
    sinal_velocidade = (
        not sinal_parado
        and 0 < velocidade < VELOCIDADE_REFERENCIA_KMH
    )

    # Ocorrência é contexto operacional.
    # Ela não cria tendência sozinha.
    sinal_ocorrencia = (
        bool(motivo)
        and not motivo_eh_neutro
    )

    # Não existe comportamento ameaçador.
    if not sinal_parado and not sinal_velocidade:
        return False, ""

    perda_30 = calcular_perda_margem_projetada(
        data,
        JANELA_PROJECAO_1_MIN
    )

    perda_60 = calcular_perda_margem_projetada(
        data,
        JANELA_PROJECAO_2_MIN
    )

    margem_projetada_30 = margem - perda_30
    margem_projetada_60 = margem - perda_60

    # --------------------------------------------------------
    # CRITÉRIO DE TENDÊNCIA
    # --------------------------------------------------------
    #
    # Se o comportamento atual esgota a margem dentro de 30–60 min,
    # existe ameaça direta ao ETA.
    #
    # Mesmo quando ainda sobra margem, uma margem muito pequena
    # combinada com comportamento ativo merece tendência.
    # --------------------------------------------------------

    if margem_projetada_30 <= 0:
        nivel = "CRÍTICA"

    elif margem_projetada_60 <= 0:
        nivel = "CRÍTICA"

    elif margem <= MARGEM_CRITICA_MIN and (
        sinal_parado
        or sinal_velocidade
    ):
        nivel = "CRÍTICA"

    elif margem_projetada_60 <= 60:
        nivel = "MODERADA"

    elif margem <= MARGEM_MODERADA_MIN and (
        sinal_parado
        or sinal_velocidade
    ):
        nivel = "MODERADA"

    elif margem_projetada_60 <= 120:
        nivel = "LEVE"

    elif margem <= MARGEM_LEVE_MIN and sinal_parado:
        # Parada prolongada com margem ainda positiva.
        nivel = "LEVE"

    else:
        return False, ""

    detalhes = [
        f"margem atual de {int(margem)} min"
    ]

    if sinal_parado:
        detalhes.append(
            f"parado há {data['Tempo_Str']}"
        )

    if sinal_velocidade:
        detalhes.append(
            f"velocidade atual de {int(velocidade)} km/h"
        )

    if sinal_ocorrencia:
        detalhes.append(
            f"ocorrência: {motivo}"
        )

    detalhes.append(
        f"margem projetada em 30 min: {int(margem_projetada_30)} min"
    )

    detalhes.append(
        f"em 60 min: {int(margem_projetada_60)} min"
    )

    return (
        True,
        f"[TENDÊNCIA {nivel}] "
        + " | ".join(detalhes)
        + "."
    )


# ============================================================
# PROCESSAMENTO DOS DADOS
# ============================================================

def process_data_local(text, data_trabalho_str):

    blocks = re.split(
        r'\n(?=LT[0-9A-Z]+\b)',
        text.strip()
    )

    parsed_data = []

    agora_br = datetime.utcnow() - timedelta(hours=3)

    try:
        dt_base = datetime.strptime(
            data_trabalho_str,
            "%d/%m/%Y"
        )

        ano_atual = dt_base.year

    except Exception:
        ano_atual = agora_br.year

    for block in blocks:

        if not block.strip().startswith('LT'):
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
            "Sem_Sinal": False,
            "Status_Operacional": "Normal",
            "Classificacao_Desempenho": "No prazo",
            "Motivo_Risco": "",
            "Margem_Minutos": 999,
            "ETA_Dt": None,
            "Chegada_Real_Dt": None,
            "Adiantamento_Minutos": None,

            # Novos indicadores matemáticos
            "Tempo_Necessario_Min": 0,
            "Tempo_Disponivel_Min": 999,
            "Margem_Projetada_30_Min": None,
            "Margem_Projetada_60_Min": None,

            # HUB/XPT
            "Destino_Hub_XPT": False,
            "Antecedencia_Hub_XPT_Min": None,
            "Alerta_Hub_XPT": False
        }

        lines = [
            line.strip()
            for line in block.split('\n')
            if line.strip()
        ]

        if not lines:
            continue

        # ----------------------------------------------------
        # LT + MOTORISTA
        # ----------------------------------------------------

        first_line = lines[0].split('\t')

        data["LT_Full"] = first_line[0]

        # Mantido apenas internamente.
        # Nenhuma interface usa LT_Short.
        data["LT_Short"] = data["LT_Full"][-5:]

        if len(first_line) > 1:
            data["Motorista"] = first_line[1]

        # ----------------------------------------------------
        # PACOTES
        # ----------------------------------------------------

        for line in lines:

            clean_line = (
                line
                .replace('.', '')
                .replace(',', '')
            )

            if clean_line.isdigit():

                val = int(clean_line)

                if 10 <= val <= 99999:
                    data["Pacotes"] = val
                    break

        if data["Pacotes"] == 0:

            nums = re.findall(
                r'\b\d{3,6}\b',
                block
            )

            if nums:
                data["Pacotes"] = int(nums[0])

        # ----------------------------------------------------
        # VELOCIDADE
        # ----------------------------------------------------

        vel_match = re.search(
            r'(\d+)\s*km/h',
            block
        )

        if vel_match:
            data["Velocidade"] = int(
                vel_match.group(1)
            )

        # ----------------------------------------------------
        # DISTÂNCIA
        # ----------------------------------------------------

        dist_match = re.search(
            r'(?m)^(\d+)\s*km$',
            block
        )

        if dist_match:
            data["Distancia_Raw"] = int(
                dist_match.group(1)
            )

        # ----------------------------------------------------
        # STATUS MOVIMENTO
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
            r'(\d{2}:\d{2}:\d{2})',
            block
        )

        if time_match:

            (
                data["Tempo_Str"],
                data["Tempo_Horas"]
            ) = parse_duration(
                time_match.group(1)
            )

        # ----------------------------------------------------
        # ORIGEM / DESTINO
        # ----------------------------------------------------

        idx_dest = None

        for idx_linha, line in enumerate(lines):

            if (
                ('SOC-' in line
                 or 'HUB-' in line
                 or 'LM ' in line)
                and '\t' in line
            ):

                parts = line.split('\t')

                data["Origem"] = parts[0]

                if len(parts) > 1:
                    data["Destino"] = parts[1]

                idx_dest = idx_linha
                break

        # Fallback
        if not data["Destino"]:

            dest_match = re.search(
                r'\b('
                r'SOC-[A-Z0-9\-]+'
                r'|HUB-[A-Z0-9\-]+'
                r'|LM\s+[A-Z0-9\-]+'
                r'|LPA[A-Z0-9\-]*'
                r'|LMA[A-Z0-9\-]*'
                r')\b',
                block
            )

            if dest_match:
                data["Destino"] = dest_match.group(1)

        data["UF"] = extract_uf(
            data["Destino"]
        )

        # ----------------------------------------------------
        # OCORRÊNCIA
        # ----------------------------------------------------

        if (
            idx_dest is not None
            and idx_dest + 1 < len(lines)
        ):

            linha_contagem = lines[
                idx_dest + 1
            ]

            if (
                not linha_contagem.startswith('--')
                and idx_dest + 2 < len(lines)
            ):

                candidata = lines[
                    idx_dest + 2
                ]

                candidata_limpa = (
                    candidata
                    .replace('.', '')
                    .replace(',', '')
                )

                if not candidata_limpa.isdigit():
                    data["Motivo_Parada"] = candidata

        # Fallback por palavras-chave
        if not data["Motivo_Parada"]:

            palavras = [
                'Parada',
                'Retenção',
                'Acidente',
                'Problema',
                'Mudança',
                'Manutenção',
                'Trânsito',
                'aderência',
                'antecipada',
                'documentação',
                'fiscal'
            ]

            for line in lines:

                if any(
                    kw in line
                    for kw in palavras
                ):

                    data["Motivo_Parada"] = line
                    break

        # ----------------------------------------------------
        # TIMESTAMP / SEM SINAL
        # ----------------------------------------------------

        date_pattern = r'\d{2}/\d{2} \d{2}:\d{2}'

        dates_found = re.findall(
            date_pattern,
            block
        )

        if len(dates_found) > 0:

            data["Ultima_Atualizacao_Str"] = dates_found[-1]

            try:

                ts_dt = datetime.strptime(
                    f"{data['Ultima_Atualizacao_Str']}/{ano_atual}",
                    "%d/%m %H:%M/%Y"
                )

                if ts_dt > agora_br + timedelta(days=1):
                    ts_dt = ts_dt.replace(
                        year=ano_atual - 1
                    )

                if (
                    (agora_br - ts_dt).total_seconds() / 3600
                    >= 1.0
                    or "Não monitorado" in block
                ):
                    data["Sem_Sinal"] = True

            except Exception:
                pass

        # ----------------------------------------------------
        # ETA / CHEGADA REAL
        # ----------------------------------------------------

        for i, line in enumerate(lines):

            if (
                'No prazo' in line
                or 'Atrasado' in line
                or 'Risco' in line
            ):

                if i >= 1:

                    linha_chegada = lines[i - 1]

                    if re.match(
                        date_pattern,
                        linha_chegada
                    ):
                        data["Chegada_Real"] = linha_chegada

                    elif linha_chegada in ('-', '—'):
                        data["Chegada_Real"] = linha_chegada

                if (
                    i >= 2
                    and re.match(
                        date_pattern,
                        lines[i - 2]
                    )
                ):

                    data["ETA"] = lines[i - 2]

        # Fallback
        if (
            data["ETA"] == "-"
            and len(dates_found) >= 1
        ):
            data["ETA"] = dates_found[0]

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
        # DISTÂNCIA CORRIGIDA
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

            data["Fator_Correcao"] = "(+25%)"

        # ----------------------------------------------------
        # HUB / XPT
        # ----------------------------------------------------

        data["Destino_Hub_XPT"] = destino_eh_hub_xpt(
            data["Destino"]
        )

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
                        f"Chegou {diff_min} min "
                        "após o ETA programado."
                    )

                elif diff_min < 0:

                    data["Motivo_Risco"] = (
                        f"Chegou {abs(diff_min)} min "
                        "antes do ETA programado."
                    )

                else:

                    data["Motivo_Risco"] = (
                        "Chegou no horário programado."
                    )

        elif eta_dt:

            # ------------------------------------------------
            # TEMPO DISPONÍVEL
            # ------------------------------------------------

            tempo_disp_min = (
                eta_dt - agora_br
            ).total_seconds() / 60

            tempo_necessario_min = (
                data["Distancia_Corrigida"]
            )

            margem = (
                tempo_disp_min
                - tempo_necessario_min
            )

            data["Tempo_Disponivel_Min"] = int(
                tempo_disp_min
            )

            data["Tempo_Necessario_Min"] = int(
                tempo_necessario_min
            )

            data["Margem_Minutos"] = int(
                margem
            )

            # -----------------------------------------------
            # DELAY
            # -----------------------------------------------
            #
            # ETA já passou:
            # tempo disponível <= 0
            #
            # OU
            #
            # matemática não fecha:
            # margem <= 0
            # -----------------------------------------------

            if (
                tempo_disp_min <= 0
                or margem <= 0
            ):

                data["Status_Operacional"] = "Delay"
                data["Classificacao_Desempenho"] = "Delay"

                data["Motivo_Risco"] = (
                    formatar_deficit_tempo(margem)
                )

            else:

                # -------------------------------------------
                # PROJEÇÕES DE MARGEM
                # -------------------------------------------

                perda_30 = calcular_perda_margem_projetada(
                    data,
                    JANELA_PROJECAO_1_MIN
                )

                perda_60 = calcular_perda_margem_projetada(
                    data,
                    JANELA_PROJECAO_2_MIN
                )

                data["Margem_Projetada_30_Min"] = int(
                    margem - perda_30
                )

                data["Margem_Projetada_60_Min"] = int(
                    margem - perda_60
                )

                # -------------------------------------------
                # TENDÊNCIA
                # -------------------------------------------

                tem_tendencia, texto_motivo = avaliar_tendencia(
                    data
                )

                if tem_tendencia:

                    data["Status_Operacional"] = "Tendência"
                    data["Classificacao_Desempenho"] = "No prazo"
                    data["Motivo_Risco"] = texto_motivo

                else:

                    data["Status_Operacional"] = "Normal"
                    data["Classificacao_Desempenho"] = "No prazo"

            # -----------------------------------------------
            # HUB/XPT
            # -----------------------------------------------

            if data["Destino_Hub_XPT"]:

                chegada_estimada = (
                    agora_br
                    + timedelta(
                        minutes=tempo_necessario_min
                    )
                )

                antecedencia = int(
                    (
                        eta_dt
                        - chegada_estimada
                    ).total_seconds() / 60
                )

                data["Antecedencia_Hub_XPT_Min"] = antecedencia

                if (
                    antecedencia
                    < MINUTOS_ANTECEDENCIA_HUB_XPT
                ):
                    data["Alerta_Hub_XPT"] = True

        else:

            if data["Sem_Sinal"]:

                data["Status_Operacional"] = "Tendência"

                data["Motivo_Risco"] = (
                    f"Sem sinal desde "
                    f"{data['Ultima_Atualizacao_Str']}."
                )

    df_result = pd.DataFrame(
        parsed_data
    )

    return df_result


# ============================================================
# FUNÇÕES DE STATUS
# ============================================================

def esta_em_rota(row):
    """
    True quando ainda não existe chegada real registrada.
    """

    return pd.isna(
        row["Chegada_Real_Dt"]
    )


def deve_alertar_tendencia(row):
    """
    Filtro operacional de alerta.

    Uma ocorrência já explicada não precisa ser repetida
    constantemente em Tendência/Plano de Ação.

    Exceções:
    - Parada programada — intervalo/refeição
    - proximidade da base
    - parada muito longa
    """

    motivo = str(
        row["Motivo_Parada"] or ""
    ).strip()

    # Sem ocorrência:
    # acompanhamento normal.
    if not motivo:
        return True

    # Ocorrência neutra:
    # continua sendo acompanhada pela margem.
    if motivo in OCORRENCIAS_NEUTRAS:
        return True

    perto_da_base = (
        row["Distancia_Raw"]
        <= (
            KM_ALERTA_LOCALIZACAO_BASE
            + TOLERANCIA_KM_LOCALIZACAO_BASE
        )
    )

    parado_muito_tempo = (
        row["Status_Movimento"] == "Parado"
        and row["Tempo_Horas"]
        >= LIMIAR_PARADO_LONGO_HORAS
    )

    return (
        perto_da_base
        or parado_muito_tempo
    )


def classificar_performance(row):

    if row["Status_Operacional"] == "Delay":
        return "Delay"

    motivo = str(
        row["Motivo_Parada"] or ""
    ).lower()

    if (
        "aderência" in motivo
        or "antecipada" in motivo
    ):
        return "Early"

    return "No prazo"


def calcular_performance_rota(df_uf):

    total_pacotes = df_uf["Pacotes"].sum()

    if total_pacotes == 0:
        return 0.0, pd.Series(dtype=float)

    impacto = (
        df_uf["Pacotes"]
        / total_pacotes
    )

    ganho = impacto.where(
        df_uf["Classificacao_Performance"] == "No prazo",
        0.0
    )

    performance_pct = (
        ganho.sum()
        * 100
    )

    return performance_pct, ganho


# ============================================================
# RELATÓRIO
# ============================================================

def generate_report_text(df):

    agora = (
        datetime.utcnow()
        - timedelta(hours=3)
    )

    data_hora_str = agora.strftime(
        "%d/%m/%Y · %H:%M"
    )

    df = df.copy()

    df["Em_Rota"] = df.apply(
        esta_em_rota,
        axis=1
    )

    df["Minutos_Ate_ETA"] = df["ETA_Dt"].apply(
        lambda d:
            (d - agora).total_seconds() / 60
            if pd.notna(d)
            else None
    )

    report = (
        f"# MONITORAMENTO OPERACIONAL — "
        f"{data_hora_str}\n\n"
    )

    report += (
        f"**Total no recorte:** {len(df)} LTs\n"
    )

    report += (
        "**Referência:** ETA oficial = primeiro horário.\n"
    )

    report += (
        "**Velocidade de cálculo:** "
        "60 km/h ≈ 1 km/min.\n"
    )

    report += (
        "**Distância corrigida:** "
        "+25% nas rotas gerais; "
        "+35% para destinos em MA.\n"
    )

    report += (
        "**Delay:** ETA vencido ou margem matemática "
        "≤ 0.\n"
    )

    report += (
        "**Tendência:** ETA ainda matematicamente possível, "
        "mas o comportamento atual está consumindo a margem.\n"
    )

    report += (
        "**Parada programada — intervalo/refeição:** "
        "não é causa automática de atraso; seu impacto é "
        "avaliado pela margem disponível.\n"
    )

    report += (
        "**Pacotes:** usados para prioridade/cobrança, "
        "não para cálculo matemático do ETA.\n"
    )

    report += (
        "**LTs que já deram chegada no app não entram "
        "nas listas operacionais de risco.\n\n"
    )

    report += "---\n\n"

    # ========================================================
    # DELAY
    # ========================================================

    report += "# 🚨 DELAY / ATRASO\n\n"

    criticos = df[
        (df["Status_Operacional"] == "Delay")
        & (~df["Sem_Sinal"])
    ].copy()

    if criticos.empty:

        report += (
            "Nenhuma LT em delay neste recorte.\n\n"
        )

    else:

        for _, row in criticos.iterrows():

            report += (
                f"## 🔴 {row['LT_Full']} — "
                f"{row['Motorista']}\n\n"
            )

            report += (
                f"* **ETA:** {row['ETA']}\n"
            )

            report += (
                f"* **Pacotes:** {row['Pacotes']:,}\n"
            )

            report += (
                f"* **Distância:** "
                f"{row['Distancia_Raw']} km → "
                f"**{row['Distancia_Corrigida']:.2f} km corrigidos**\n"
            )

            report += (
                f"* **Velocidade:** "
                f"{row['Velocidade']} km/h\n"
            )

            if row["Status_Movimento"] == "Parado":

                report += (
                    f"* **Parado:** "
                    f"{row['Tempo_Str']}\n"
                )

            if row["Motivo_Parada"]:

                report += (
                    f"* **Ocorrência:** "
                    f"{row['Motivo_Parada']}\n"
                )

            report += (
                f"* **Situação matemática:** "
                f"{row['Motivo_Risco']}\n\n"
            )

            # Aqui NÃO escondemos o Delay.
            # A aba de atrasadas continua mostrando todos.
            # O filtro operacional só é aplicado aos alertas/cobranças.

            if deve_alertar_tendencia(row):

                report += (
                    "**Ação:** Cobrança imediata da situação "
                    "e acompanhamento.\n\n"
                )

            else:

                report += (
                    "**Ação:** Motivo já explicado; "
                    "sem nova cobrança operacional neste momento, "
                    "salvo proximidade da base ou parada prolongada.\n\n"
                )

    # ========================================================
    # TENDÊNCIA
    # ========================================================

    report += (
        "# ⚠️ TENDÊNCIA DE ATRASO / "
        "RISCO OPERACIONAL\n\n"
    )

    riscos_todos = df[
        (df["Status_Operacional"] == "Tendência")
        & (~df["Sem_Sinal"])
        & (df["Em_Rota"])
    ].copy()

    # Filtro operacional
    riscos = riscos_todos[
        riscos_todos.apply(
            deve_alertar_tendencia,
            axis=1
        )
    ].copy()

    if riscos.empty:

        report += (
            "Nenhuma tendência de atraso que exija "
            "alerta operacional neste recorte.\n\n"
        )

        if not riscos_todos.empty:

            report += (
                "_Existem LTs classificadas matematicamente "
                "como tendência, mas com ocorrência já explicada "
                "e sem proximidade da base/parada prolongada. "
                "Por isso não foram repetidas no alerta._\n\n"
            )

    else:

        for _, row in riscos.iterrows():

            report += (
                f"## 🟠 {row['LT_Full']} — "
                f"{row['Motorista']}\n\n"
            )

            report += (
                f"* **Pacotes:** {row['Pacotes']:,}\n"
            )

            report += (
                f"* **ETA:** {row['ETA']}\n"
            )

            report += (
                f"* **Distância:** "
                f"{row['Distancia_Raw']} km → "
                f"**{row['Distancia_Corrigida']:.2f} km corrigidos**\n"
            )

            report += (
                f"* **Velocidade:** "
                f"{row['Velocidade']} km/h\n"
            )

            if row["Status_Movimento"] == "Parado":

                report += (
                    f"* **Parado:** "
                    f"{row['Tempo_Str']}\n"
                )

            if row["Motivo_Parada"]:

                report += (
                    f"* **Ocorrência:** "
                    f"{row['Motivo_Parada']}\n"
                )

            report += (
                f"* **Evidência:** "
                f"{row['Motivo_Risco']}\n\n"
            )

            report += (
                "**Ação:** Monitorar a evolução da margem "
                "e do comportamento atual.\n\n"
            )

    # ========================================================
    # SEM SINAL
    # ========================================================

    report += "# 🚨 SEM SINAL\n\n"

    sem_sinal_df = df[
        (df["Sem_Sinal"] == True)
        & (df["Em_Rota"])
    ].copy()

    if sem_sinal_df.empty:

        report += (
            "Nenhum veículo sem sinal.\n\n"
        )

    else:

        for _, row in sem_sinal_df.iterrows():

            report += (
                f"### 🔴 {row['LT_Full']} — "
                f"{row['Motorista']}\n\n"
            )

            report += (
                f"* ETA {row['ETA']}\n"
            )

            report += (
                "* **Sem sinal**\n"
            )

            report += (
                f"* Última posição: "
                f"{row['Ultima_Atualizacao_Str']}\n\n"
            )

            report += (
                "**Ação:** Escalar imediatamente "
                "para localização/comunicação.\n\n"
            )

    # ========================================================
    # HUB / XPT
    # ========================================================

    report += (
        "# 🏭 ATENÇÃO — HUB/XPT\n\n"
    )

    report += (
        f"_Destinos identificados como HUB/XPT. "
        f"O alerta aparece quando a projeção matemática "
        f"não permite pelo menos "
        f"{MINUTOS_ANTECEDENCIA_HUB_XPT} min "
        f"de antecedência em relação ao ETA._\n\n"
    )

    hub_xpt_df = df[
        (df["Em_Rota"])
        & (df["Destino_Hub_XPT"] == True)
        & (df["Alerta_Hub_XPT"] == True)
    ].copy()

    if hub_xpt_df.empty:

        report += (
            "Nenhuma LT HUB/XPT com risco de perder "
            "a antecedência operacional neste recorte.\n\n"
        )

    else:

        for _, row in hub_xpt_df.iterrows():

            antecedencia = row[
                "Antecedencia_Hub_XPT_Min"
            ]

            if antecedencia is None:
                antecedencia_texto = "não calculada"
            elif antecedencia < 0:
                antecedencia_texto = (
                    f"{abs(int(antecedencia))} min "
                    "além do ETA"
                )
            else:
                antecedencia_texto = (
                    f"{int(antecedencia)} min"
                )

            report += (
                f"* **{row['LT_Full']} — "
                f"{row['Motorista']}**\n"
            )

            report += (
                f"  - Destino: **{row['Destino']}**\n"
            )

            report += (
                f"  - ETA: **{row['ETA']}**\n"
            )

            report += (
                f"  - Distância restante: "
                f"**{row['Distancia_Raw']} km**\n"
            )

            report += (
                f"  - Antecedência projetada: "
                f"**{antecedencia_texto}**\n"
            )

            if row["Status_Operacional"] == "Delay":

                report += (
                    "  - ⚠️ A LT já está matematicamente "
                    "em Delay e também não atende à "
                    "antecedência operacional do HUB/XPT.\n\n"
                )

            else:

                report += (
                    "  - ⚠️ **Atenção:** a projeção atual "
                    "não garante 1 hora de antecedência "
                    "antes do ETA.\n\n"
                )

    report += "---\n\n"

    # ========================================================
    # VEÍCULOS PARADOS
    # ========================================================

    report += (
        "# 🚨 VEÍCULOS PARADOS — RISCO OPERACIONAL\n\n"
    )

    parados_df = df[
        (df["Status_Movimento"] == "Parado")
        & (df["Em_Rota"])
    ].sort_values(
        by="Tempo_Horas",
        ascending=False
    )

    if parados_df.empty:

        report += (
            "Nenhum veículo parado no momento.\n\n"
        )

    else:

        report += (
            "| LT | Pacotes | Parado | Situação | Avaliação |\n"
        )

        report += (
            "| --- | ---: | ---: | --- | --- |\n"
        )

        for _, row in parados_df.iterrows():

            avaliacao = (
                row["Motivo_Parada"]
                if row["Motivo_Parada"]
                else "Parado"
            )

            report += (
                f"| **{row['LT_Full']}** "
                f"| {row['Pacotes']:,} "
                f"| {row['Tempo_Str']} "
                f"| {row['Status_Operacional']} "
                f"| {avaliacao} |\n"
            )

        report += "\n---\n\n"

    # ========================================================
    # TOP 5 VOLUMES
    # ========================================================

    report += (
        "# 📦 TOP 5 — MAIOR VOLUME DE PACOTES\n\n"
    )

    top5 = df.sort_values(
        by="Pacotes",
        ascending=False
    ).head(5)

    report += (
        "| # | LT | Motorista | Pacotes | Situação |\n"
    )

    report += (
        "| -: | --- | --- | ---: | --- |\n"
    )

    for i, (_, row) in enumerate(
        top5.iterrows(),
        1
    ):

        medal = (
            "🥇"
            if i == 1
            else (
                "🥈"
                if i == 2
                else (
                    "🥉"
                    if i == 3
                    else str(i)
                )
            )
        )

        report += (
            f"| {medal} "
            f"| **{row['LT_Full']}** "
            f"| {row['Motorista']} "
            f"| **{row['Pacotes']:,}** "
            f"| {row['Status_Operacional']} |\n"
        )

    report += "\n---\n\n"

    # ========================================================
    # PONTOS DE ATENÇÃO — BASE
    # ========================================================

    report += (
        "# 📍 PONTOS DE ATENÇÃO — "
        "CONFIRMAR LOCALIZAÇÃO DA BASE\n\n"
    )

    report += (
        f"_LTs em rota a até "
        f"{KM_ALERTA_LOCALIZACAO_BASE + TOLERANCIA_KM_LOCALIZACAO_BASE} km "
        f"do destino — envie a localização certa da base "
        f"para não errar o local._\n\n"
    )

    proximos_base = df[
        df["Em_Rota"]
        & (
            df["Distancia_Raw"]
            <= (
                KM_ALERTA_LOCALIZACAO_BASE
                + TOLERANCIA_KM_LOCALIZACAO_BASE
            )
        )
    ].copy()

    if proximos_base.empty:

        report += (
            f"Nenhuma LT a até "
            f"{KM_ALERTA_LOCALIZACAO_BASE + TOLERANCIA_KM_LOCALIZACAO_BASE} km "
            "do destino neste recorte.\n\n"
        )

    else:

        for _, row in proximos_base.iterrows():

            endereco = BASE_ENDERECOS.get(
                row["Destino"]
            )

            report += (
                f"* **{row['LT_Full']} — "
                f"{row['Motorista']}** "
                f"({row['Distancia_Raw']} km "
                f"do destino {row['Destino']})\n"
            )

            if endereco:

                report += (
                    f"  Enviar localização: "
                    f"{endereco}\n\n"
                )

            else:

                report += (
                    f"  Alertar o condutor sobre o "
                    f"local correto da base "
                    f"{row['Destino']}.\n\n"
                )

    report += "---\n\n"

    # ========================================================
    # PLANO DE AÇÃO
    # ========================================================

    report += (
        "# 🎯 PLANO DE AÇÃO IMEDIATO\n\n"
    )

    # --------------------------------------------------------
    # COBRAR AGORA
    # --------------------------------------------------------

    report += (
        "🔴 **COBRAR AGORA**\n\n"
    )

    delays_para_cobrar = df[
        (df["Status_Operacional"] == "Delay")
        & (df["Em_Rota"])
        & (df["Sem_Sinal"] == False)
    ].copy()

    delays_para_cobrar = delays_para_cobrar[
        delays_para_cobrar.apply(
            deve_alertar_tendencia,
            axis=1
        )
    ].copy()

    sem_sinal_para_cobrar = df[
        (df["Sem_Sinal"] == True)
        & (df["Em_Rota"])
    ].copy()

    tendencias_para_cobrar = df[
        (df["Status_Operacional"] == "Tendência")
        & (df["Em_Rota"])
        & (df["Sem_Sinal"] == False)
    ].copy()

    tendencias_para_cobrar = tendencias_para_cobrar[
        tendencias_para_cobrar.apply(
            deve_alertar_tendencia,
            axis=1
        )
    ].copy()

    tendencias_urgentes = tendencias_para_cobrar[
        (
            tendencias_para_cobrar["Margem_Minutos"]
            <= 30
        )
        |
        (
            tendencias_para_cobrar["Tempo_Horas"]
            >= 2.0
        )
    ].copy()

    urgentes = pd.concat(
        [
            delays_para_cobrar,
            sem_sinal_para_cobrar,
            tendencias_urgentes
        ],
        ignore_index=True
    ).drop_duplicates(
        subset=["LT_Full"]
    )

    if urgentes.empty:

        report += (
            "Nenhuma unidade em situação crítica "
            "iminente neste recorte.\n\n"
        )

    else:

        for idx, (_, row) in enumerate(
            urgentes.iterrows(),
            1
        ):

            motorista_nome = (
                row["Motorista"]
                if row["Motorista"]
                and row["Motorista"] != "-"
                else "CONDUTOR NÃO IDENTIFICADO"
            )

            report += (
                f"{idx}. **{row['LT_Full']} — "
                f"{motorista_nome}**\n"
            )

            detalhes = []

            if row["Sem_Sinal"]:

                detalhes.append(
                    "Sem sinal telemétrico desde "
                    f"{row['Ultima_Atualizacao_Str']}."
                )

            if row["Margem_Minutos"] != 999:

                if row["Margem_Minutos"] <= 0:

                    detalhes.append(
                        "Já em DELAY matemático "
                        f"({formatar_deficit_tempo(row['Margem_Minutos'])})"
                    )

                else:

                    detalhes.append(
                        f"Margem de aproximadamente "
                        f"**{row['Margem_Minutos']} min**."
                    )

            if row["Velocidade"] > 0:

                detalhes.append(
                    f"Velocidade atual: "
                    f"{row['Velocidade']} km/h."
                )

            if row["Status_Movimento"] == "Parado":

                detalhes.append(
                    f"Parado há "
                    f"{row['Tempo_Str']}."
                )

            if row["Motivo_Parada"]:

                detalhes.append(
                    f"Ocorrência/Motivo: "
                    f"{row['Motivo_Parada']}."
                )

            if row["Pacotes"] > 0:

                detalhes.append(
                    f"Volume: "
                    f"{row['Pacotes']:,} pacotes."
                )

            report += (
                f"{' '.join(detalhes)}\n\n"
            )

    # --------------------------------------------------------
    # MONITORAR PRÓXIMOS 30 MIN
    # --------------------------------------------------------

    report += (
        "🟠 **MONITORAR NOS PRÓXIMOS 30 MINUTOS**\n\n"
    )

    monitorar_30 = df[
        (df["Status_Operacional"] == "Tendência")
        & (df["Em_Rota"])
        & (df["Sem_Sinal"] == False)
    ].copy()

    monitorar_30 = monitorar_30[
        monitorar_30.apply(
            deve_alertar_tendencia,
            axis=1
        )
    ].copy()

    monitorar_30 = monitorar_30[
        ~monitorar_30["LT_Full"].isin(
            urgentes["LT_Full"]
        )
    ].copy()

    if monitorar_30.empty:

        report += (
            "Nenhuma LT requer monitoramento adicional "
            "nos próximos 30 minutos.\n\n"
        )

    else:

        for _, row in monitorar_30.iterrows():

            report += (
                f"* **{row['LT_Full']} — "
                f"{row['Motorista']}** — "
                f"margem atual: "
                f"{row['Margem_Minutos']} min; "
                f"projeção em 30 min: "
                f"{row['Margem_Projetada_30_Min']} min.\n"
            )

        report += "\n"

    # --------------------------------------------------------
    # ESCALAR SE NÃO HOUVER EVOLUÇÃO
    # --------------------------------------------------------

    report += (
        "🟡 **ESCALAR SE NÃO HOUVER EVOLUÇÃO**\n\n"
    )

    candidatos_escalada = df[
        (
            (
                df["Status_Operacional"] == "Tendência"
            )
            |
            (
                df["Status_Operacional"] == "Delay"
            )
        )
        & df["Em_Rota"]
    ].copy()

    candidatos_escalada = candidatos_escalada[
        candidatos_escalada.apply(
            deve_alertar_tendencia,
            axis=1
        )
    ].copy()

    candidatos_escalada = candidatos_escalada[
        ~candidatos_escalada["LT_Full"].isin(
            urgentes["LT_Full"]
        )
    ].copy()

    candidatos_escalada = candidatos_escalada[
        ~candidatos_escalada["LT_Full"].isin(
            monitorar_30["LT_Full"]
        )
    ].copy()

    if candidatos_escalada.empty:

        report += (
            "Nenhuma unidade adicional para escalada "
            "neste momento.\n\n"
        )

    else:

        for _, row in candidatos_escalada.iterrows():

            report += (
                f"* **{row['LT_Full']} — "
                f"{row['Motorista']}** — "
                f"{row['Status_Operacional']}."
            )

            if row["Motivo_Parada"]:

                report += (
                    f" Motivo: "
                    f"{row['Motivo_Parada']}."
                )

            report += "\n"

        report += "\n"

    # --------------------------------------------------------
    # SEM NECESSIDADE DE AÇÃO
    # --------------------------------------------------------

    report += (
        "🟢 **SEM NECESSIDADE DE AÇÃO**\n\n"
    )

    sem_acao = df[
        (df["Status_Operacional"] == "Normal")
        & (df["Em_Rota"])
        & (df["Sem_Sinal"] == False)
    ].copy()

    if sem_acao.empty:

        report += (
            "Nenhuma LT classificada como normal "
            "sem necessidade de acompanhamento.\n\n"
        )

    else:

        report += (
            f"{len(sem_acao)} LTs permanecem "
            "matematicamente dentro do ETA sem "
            "alerta operacional ativo.\n\n"
        )

    # --------------------------------------------------------
    # PORTARIA
    # --------------------------------------------------------

    report += (
        "🚪 **SOLICITAR LIBERAÇÃO DE PORTARIA "
        "(bases SP/RJ)**\n\n"
    )

    report += (
        "_Confira manualmente antes de acionar: "
        "se o veículo estiver parado e for descarregar "
        "só mais tarde, pule essa LT — o sistema não sabe "
        "o horário de descarga combinado._\n\n"
    )

    portaria_df = df[
        df["Em_Rota"]
        & df["UF"].isin(["SP", "RJ"])
        & (
            df["Distancia_Raw"]
            >= (
                KM_ALERTA_PORTARIA_SP_RJ
                - TOLERANCIA_KM_PORTARIA
            )
        )
        & (
            df["Distancia_Raw"]
            <= (
                KM_ALERTA_PORTARIA_SP_RJ
                + TOLERANCIA_KM_PORTARIA
            )
        )
        & df["Minutos_Ate_ETA"].notnull()
        & (
            df["Minutos_Ate_ETA"]
            <= MINUTOS_PROXIMO_ETA_PORTARIA
        )
    ].copy()

    if portaria_df.empty:

        report += (
            "Nenhuma LT nessas condições neste recorte.\n\n"
        )

    else:

        for _, row in portaria_df.iterrows():

            minutos = int(
                row["Minutos_Ate_ETA"]
            )

            report += (
                f"* **{row['LT_Full']} — "
                f"{row['Motorista']}** — "
                f"{row['Distancia_Raw']} km do destino "
                f"({row['UF']}), ETA em ~"
                f"{minutos} min.\n\n"
            )

    # ========================================================
    # RESUMO SIMPLIFICADO
    # ========================================================

    report += (
        "# RESUMO SIMPLIFICADO\n\n"
    )

    report += "```text\n"

    report += "Delay:\n"

    for _, row in criticos.iterrows():

        report += (
            f"{row['LT_Full']}\n"
        )

    report += "\nTendência de atraso:\n"

    for _, row in riscos.iterrows():

        report += (
            f"{row['LT_Full']}\n"
        )

    report += "\nSem sinal:\n"

    for _, row in sem_sinal_df.iterrows():

        report += (
            f"{row['LT_Full']}\n"
        )

    report += "----------------\n"
    report += "```\n"

    return report


# ============================================================
# INTERFACE PRINCIPAL
# ============================================================

st.markdown(
    """
    <h1 style='text-align: center; color: #ee4d2d;'>
        🚛 Torre de Controle — Gestão Inteligente de Frotas
    </h1>
    """,
    unsafe_allow_html=True
)

st.markdown(
    """
    <p style='text-align: center; color: #64748b;'>
        Monitoramento preditivo, comportamental e logístico avançado em tempo real.
    </p>
    """,
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

    data_hoje_str = datetime.utcnow().strftime(
        "%d/%m/%Y"
    )

    data_plantao_str = st.text_input(
        "Data de Início do Plantão / Turno D (DD/MM/AAAA):",
        value=data_hoje_str,
        placeholder="Ex: 27/09/2026"
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
        height=140,
        placeholder="Ex: LT01234567 ..."
    )

    col_b1, _ = st.columns([2, 8])

    with col_b1:

        gerar_btn = st.button(
            "Gerar Relatório Analítico"
        )

# ============================================================
# GERAR RELATÓRIO
# ============================================================

if gerar_btn:

    if raw_text.strip():

        df_parsed = process_data_local(
            raw_text,
            data_plantao_str
        )

        if df_parsed.empty:

            st.error(
                "⚠️ Nenhum dado válido encontrado "
                "para este texto colado."
            )

            st.session_state[
                "relatorio_gerado"
            ] = ""

            st.session_state[
                "df_parsed"
            ] = None

        else:

            st.session_state[
                "relatorio_gerado"
            ] = generate_report_text(
                df_parsed
            )

            st.session_state[
                "df_parsed"
            ] = df_parsed

    else:

        st.warning(
            "⚠️ Insira os dados na caixa de texto "
            "acima antes de gerar."
        )


# ============================================================
# EXIBIÇÃO
# ============================================================

if st.session_state["relatorio_gerado"]:

    df = st.session_state["df_parsed"]

    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown(
        "### 📊 Indicadores Operacionais (Score Cards)"
    )

    total_lts = len(df)

    qtd_normal = len(
        df[
            df["Status_Operacional"]
            == "Normal"
        ]
    )

    qtd_parados = len(
        df[
            df["Status_Movimento"]
            == "Parado"
        ]
    )

    qtd_tendencia = len(
        df[
            df["Status_Operacional"]
            == "Tendência"
        ]
    )

    qtd_delays = len(
        df[
            df["Status_Operacional"]
            == "Delay"
        ]
    )

    qtd_concluidas = len(
        df[
            df["Status_Operacional"]
            == "Concluído"
        ]
    )

    k1, k2, k3, k4, k5, k6 = st.columns(6)

    with k1:

        st.markdown(
            f"""
            <div class='metric-card'>
                <div class='metric-title'>Total de LTs</div>
                <div class='metric-value'>{total_lts}</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with k2:

        st.markdown(
            f"""
            <div class='metric-card'>
                <div class='metric-title'>No Prazo (em rota)</div>
                <div class='metric-value' style='color: #10b981;'>
                    {qtd_normal}
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with k3:

        st.markdown(
            f"""
            <div class='metric-card'>
                <div class='metric-title'>Veículos Parados</div>
                <div class='metric-value' style='color: #f59e0b;'>
                    {qtd_parados}
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with k4:

        st.markdown(
            f"""
            <div class='metric-card'>
                <div class='metric-title'>Tendência Atraso</div>
                <div class='metric-value' style='color: #d97706;'>
                    {qtd_tendencia}
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with k5:

        st.markdown(
            f"""
            <div class='metric-card'>
                <div class='metric-title'>Delays</div>
                <div class='metric-value' style='color: #dc2626;'>
                    {qtd_delays}
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with k6:

        st.markdown(
            f"""
            <div class='metric-card'>
                <div class='metric-title'>Concluídas</div>
                <div class='metric-value' style='color: #64748b;'>
                    {qtd_concluidas}
                </div>
            </div>
            """,
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
    # ABA RELATÓRIO
    # ========================================================

    with tab_relatorio:

        st.markdown(
            "#### 📋 Pré-visualização do Relatório"
        )

        st.info(
            "O texto abaixo está formatado com o template operacional."
        )

        st.text_area(
            "Texto formatado completo:",
            value=st.session_state[
                "relatorio_gerado"
            ],
            height=500
        )

    # ========================================================
    # PERFORMANCE POR ROTA
    # ========================================================

    with tab_performance:

        st.markdown(
            "#### 🌐 Performance por Rota (UF) — Filtrado pelo Turno D"
        )

        st.info(
            f"ℹ️ Exibindo apenas as LTs **ainda em rota** "
            f"(sem chegada registrada) com ETA dentro do turno "
            f"(19:00 de {data_plantao_str} até 15:00 do dia seguinte)."
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
                &
                (
                    df["ETA_Dt"]
                    >= inicio_turno
                )
                &
                (
                    df["ETA_Dt"]
                    <= fim_turno
                )
                &
                df.apply(
                    esta_em_rota,
                    axis=1
                )
            ].copy()

        except ValueError:

            st.error(
                f"⚠️ Data de plantão inválida: "
                f"'{data_plantao_str}'. "
                "Use o formato DD/MM/AAAA."
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
                    df_perf[
                        "Classificacao_Performance"
                    ]
                    == "No prazo"
                ]
            )

            qtd_delay_total = len(
                df_perf[
                    df_perf[
                        "Classificacao_Performance"
                    ]
                    == "Delay"
                ]
            )

            qtd_early_total = len(
                df_perf[
                    df_perf[
                        "Classificacao_Performance"
                    ]
                    == "Early"
                ]
            )

            st.markdown(
                "##### 📊 Resumo do Turno "
                "(LTs em rota, dentro do range)"
            )

            r1, r2, r3, r4 = st.columns(4)

            with r1:

                st.markdown(
                    f"""
                    <div class='metric-card'>
                        <div class='metric-title'>Total em Rota</div>
                        <div class='metric-value'>{total_perf}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            with r2:

                st.markdown(
                    f"""
                    <div class='metric-card'>
                        <div class='metric-title'>No Prazo</div>
                        <div class='metric-value' style='color:#10b981;'>
                            {qtd_no_prazo_total}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            with r3:

                st.markdown(
                    f"""
                    <div class='metric-card'>
                        <div class='metric-title'>Delay</div>
                        <div class='metric-value' style='color:#dc2626;'>
                            {qtd_delay_total}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            with r4:

                st.markdown(
                    f"""
                    <div class='metric-card'>
                        <div class='metric-title'>Early</div>
                        <div class='metric-value' style='color:#3b82f6;'>
                            {qtd_early_total}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            st.markdown("<br>", unsafe_allow_html=True)

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
                        df_uf[
                            "Classificacao_Performance"
                        ] == "No prazo"
                    ]
                )

                qtd_delay = len(
                    df_uf[
                        df_uf[
                            "Classificacao_Performance"
                        ] == "Delay"
                    ]
                )

                qtd_early = len(
                    df_uf[
                        df_uf[
                            "Classificacao_Performance"
                        ] == "Early"
                    ]
                )

                st.markdown("---")

                st.markdown(
                    f"### 📍 Rota: **{uf}**"
                )

                if len(df_uf) <= 2:

                    st.caption(
                        "⚠️ Amostra pequena "
                        "(poucas LTs) — a % de performance "
                        "pode não ser representativa."
                    )

                col_uf1, col_uf2 = st.columns(
                    [4, 6]
                )

                with col_uf1:

                    st.markdown("<br>", unsafe_allow_html=True)

                    st.markdown(
                        f"* **Total de LTs (Turno D):** "
                        f"`{len(df_uf)}`"
                    )

                    st.markdown(
                        f"* **Volume Total de Pacotes:** "
                        f"`{df_uf['Pacotes'].sum():,}`"
                    )

                    st.markdown(
                        f"* 🟢 **No Prazo:** "
                        f"`{qtd_no_prazo}`"
                    )

                    st.markdown(
                        f"* 🔴 **Delay:** "
                        f"`{qtd_delay}`"
                    )

                    st.markdown(
                        f"* 🔵 **Early:** "
                        f"`{qtd_early}`"
                    )

                    st.markdown(
                        f"""
                        <div class='metric-card' style='margin-top:10px;'>
                            <div class='metric-title'>
                                Performance da Rota
                            </div>
                            <div class='metric-value' style='color:#ee4d2d;'>
                                {performance_pct:.1f}%
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                with col_uf2:

                    fig_uf = px.pie(
                        df_uf,
                        names="Classificacao_Performance",
                        title=(
                            f"Distribuição de LTs — "
                            f"{uf} (Turno D)"
                        ),
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
                        "**🚨 LTs que não vão chegar "
                        "dentro do ETA / impactaram a performance:**"
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

                    st.caption(
                        "Nenhuma LT impactou negativamente "
                        "a performance desta rota."
                    )

        else:

            st.warning(
                f"Nenhuma LT em rota encontrada com ETA "
                f"entre 19:00 de {data_plantao_str} "
                f"e 15:00 do dia seguinte (Turno D)."
            )

    # ========================================================
    # ABA ATRASADAS
    # ========================================================

    with tab_atrasadas:

        st.markdown(
            "#### 🔴 LTs Atrasadas"
        )

        st.caption(
            "Só LTs ainda em rota — quem já chegou não entra aqui."
        )

        df_atrasadas = df[
            (df["Status_Operacional"] == "Delay")
            & (df["Em_Rota"])
        ].copy()

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
            ].replace(
                "",
                "—"
            )

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
    # ABA PARADOS
    # ========================================================

    with tab_parados:

        st.markdown(
            "#### 🛑 Veículos Parados"
        )

        df_parados = df[
            (df["Status_Movimento"] == "Parado")
            & (df["Em_Rota"])
        ].copy()

        if not df_parados.empty:

            tabela_parados = df_parados[
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
            )

            st.dataframe(
                tabela_parados,
                use_container_width=True,
                hide_index=True
            )

        else:

            st.success(
                "Nenhum veículo parado."
            )

    # ========================================================
    # ABA TENDÊNCIA
    # ========================================================

    with tab_tendencia:

        st.markdown(
            "#### ⚠️ Tendência de Atraso"
        )

        st.caption(
            "A classificação considera margem matemática "
            "e projeção do comportamento atual. "
            "Ocorrência isolada não gera tendência."
        )

        df_tendencia = df[
            (df["Status_Operacional"] == "Tendência")
            & (df["Em_Rota"])
        ].copy()

        # Mesmo filtro operacional usado no relatório.
        df_tendencia_alerta = df_tendencia[
            df_tendencia.apply(
                deve_alertar_tendencia,
                axis=1
            )
        ].copy()

        if not df_tendencia_alerta.empty:

            tabela_tendencia = df_tendencia_alerta[
                [
                    "LT_Full",
                    "Motorista",
                    "Pacotes",
                    "ETA",
                    "Margem_Minutos",
                    "Margem_Projetada_30_Min",
                    "Margem_Projetada_60_Min",
                    "Motivo_Risco"
                ]
            ].rename(
                columns={
                    "LT_Full": "LT",
                    "Margem_Minutos": "Margem atual (min)",
                    "Margem_Projetada_30_Min": "Margem em 30 min",
                    "Margem_Projetada_60_Min": "Margem em 60 min"
                }
            )

            st.dataframe(
                tabela_tendencia,
                use_container_width=True,
                hide_index=True
            )

        else:

            if not df_tendencia.empty:

                st.info(
                    "Existem LTs classificadas matematicamente "
                    "como tendência, mas os motivos já estão "
                    "explicados e não há proximidade da base "
                    "ou parada prolongada que justifique "
                    "novo alerta operacional."
                )

            else:

                st.success(
                    "Nenhuma tendência de atraso."
                )

    # ========================================================
    # ABA TOP 10
    # ========================================================

    with tab_top10:

        st.markdown(
            "#### 📦 Top Volumes"
        )

        top10_tabela = df.sort_values(
            by="Pacotes",
            ascending=False
        ).head(10)[
            [
                "LT_Full",
                "Motorista",
                "Pacotes",
                "ETA",
                "Destino",
                "Status_Operacional"
            ]
        ].rename(
            columns={
                "LT_Full": "LT",
                "Status_Operacional": "Situação"
            }
        )

        st.dataframe(
            top10_tabela,
            use_container_width=True,
            hide_index=True
        )

    # ========================================================
    # TABELA ANALÍTICA COMPLETA
    # ========================================================

    with tab_tabela:

        st.markdown(
            "#### 📊 Tabela Analítica Completa"
        )

        tabela_completa = df[
            [
                "LT_Full",
                "Motorista",
                "Pacotes",
                "UF",
                "Status_Operacional",
                "Status_Movimento",
                "Velocidade",
                "Distancia_Raw",
                "Distancia_Corrigida",
                "Tempo_Necessario_Min",
                "Tempo_Disponivel_Min",
                "Margem_Minutos",
                "Margem_Projetada_30_Min",
                "Margem_Projetada_60_Min",
                "ETA",
                "Chegada_Real",
                "Destino",
                "Destino_Hub_XPT",
                "Antecedencia_Hub_XPT_Min",
                "Alerta_Hub_XPT",
                "Motivo_Parada",
                "Motivo_Risco"
            ]
        ].rename(
            columns={
                "LT_Full": "LT",
                "Distancia_Raw": "Distância restante (km)",
                "Distancia_Corrigida": "Distância corrigida (km)",
                "Tempo_Necessario_Min": "Tempo necessário (min)",
                "Tempo_Disponivel_Min": "Tempo disponível (min)",
                "Margem_Minutos": "Margem atual (min)",
                "Margem_Projetada_30_Min": "Margem em 30 min",
                "Margem_Projetada_60_Min": "Margem em 60 min",
                "Destino_Hub_XPT": "Destino HUB/XPT",
                "Antecedencia_Hub_XPT_Min": "Antecedência HUB/XPT (min)",
                "Alerta_Hub_XPT": "Alerta HUB/XPT",
                "Motivo_Parada": "Ocorrência",
                "Motivo_Risco": "Análise"
            }
        )

        st.dataframe(
            tabela_completa,
            use_container_width=True,
            hide_index=True
        )
