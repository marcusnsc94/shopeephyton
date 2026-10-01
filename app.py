import streamlit as st
import pandas as pd
import re
from datetime import datetime, timedelta
import plotly.express as px

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Torre de Controle — Shopee",
    page_icon="🚛",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- PARÂMETROS AJUSTÁVEIS ---
KM_ALERTA_LOCALIZACAO_BASE = 60      # "pontos de atenção": enviar localização da base quando perto disso
TOLERANCIA_KM_LOCALIZACAO_BASE = 10  # +-10km ao redor dos 60km

KM_ALERTA_PORTARIA_SP_RJ = 30        # "plano de ação": pedir liberação de portaria quando perto disso (bases SP/RJ)
TOLERANCIA_KM_PORTARIA = 5           # +-5km ao redor dos 30km
MINUTOS_PROXIMO_ETA_PORTARIA = 60    # só alerta se faltar até esse tanto de minutos pro ETA

# Correção de distância: regra geral +25%; rotas com destino no Maranhão usam +35%
FATOR_CORRECAO_GERAL = 1.25
FATOR_CORRECAO_MA = 1.35

# Metodologia de TENDÊNCIA DE ATRASO: tendência = margem pequena + um comportamento
# que está consumindo essa margem (parado, velocidade baixa, ocorrência ativa).
# Velocidade baixa ou parada isoladas, com margem folgada, NÃO decretam tendência.
MARGEM_CRITICA_MIN = 60     # abaixo disso + algum sinal -> TENDÊNCIA CRÍTICA
MARGEM_MODERADA_MIN = 150   # abaixo disso + algum sinal -> TENDÊNCIA MODERADA
MARGEM_LEVE_MIN = 240       # abaixo disso + ocorrência ativa ou parada prolongada -> TENDÊNCIA LEVE
PARADA_PROLONGADA_HORAS = 1.0

# Ocorrências que não contam, por si só, como "razão de atraso já explicada" --
# ainda precisam do acompanhamento normal de margem (ex.: intervalo/refeição).
OCORRENCIAS_NEUTRAS = {"Parada programada — intervalo/refeição"}

# Para LTs com uma ocorrência JÁ EXPLICADA (motivo fora da lista acima), só
# alertamos em Tendência/Plano de Ação se estiverem perto da base ou paradas
# há muito tempo -- não repetimos o motivo que o operador já conhece.
LIMIAR_PARADO_LONGO_HORAS = 2.0

# LTs com "hub" ou "xpt" no nome do destino: avisar se não vão conseguir chegar
# com pelo menos esse tanto de antecedência em relação ao ETA.
MINUTOS_ANTECEDENCIA_HUB_XPT = 60

# Endereço de cada base/hub — preencha usando o código que aparece no campo Destino (ex.: "SOC-PE2").
# Enquanto não estiver cadastrado, o relatório avisa que falta o endereço em vez de inventar um.
BASE_ENDERECOS = {
    # "SOC-PE2": "Rua Exemplo, 123 - Cabo de Santo Agostinho/PE, CEP 00000-000",
    # "SOC-PE4": "Av. Exemplo, 456 - Jaboatão dos Guararapes/PE, CEP 00000-000",
}

# --- ESTILIZAÇÃO CSS AVANÇADA (UI/UX Corporativa) ---
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

# --- FUNÇÕES DE PROCESSAMENTO ---
def parse_duration(time_str):
    try:
        parts = time_str.split(':')
        if len(parts) >= 2:
            h = int(parts[0])
            m = int(parts[1])
            return f"{h}h{m:02d}", h + (m/60)
    except:
        pass
    return "0h00", 0.0

def formatar_deficit_tempo(minutos_totais):
    """Formata um total de minutos como 'Déficit de 06h 32min.' ou 'Déficit de 01d 5h 30min.'"""
    minutos_totais = int(abs(minutos_totais))
    dias, resto = divmod(minutos_totais, 24 * 60)
    horas, minutos = divmod(resto, 60)
    if dias > 0:
        return f"Déficit de {dias:02d}d {horas}h {minutos:02d}min."
    return f"Déficit de {horas:02d}h {minutos:02d}min."

def parse_eta_to_datetime(eta_str, ano_atual):
    try:
        if not eta_str or eta_str == '-' or eta_str == '—': return None
        return datetime.strptime(f"{eta_str}/{ano_atual}", "%d/%m %H:%M/%Y")
    except:
        return None

def extract_uf(destino):
    """
    Extrai a UF do código do destino (ex.: SOC-PE2 -> PE, HUB-LAL-01 -> AL, LPA -> PA).
    Só reconhece a UF quando ela aparece como um token isolado (logo após "-" ou "L",
    seguida de dígito/hífen/fim de string) -- evita falsos positivos de siglas de UF
    grudadas no meio de códigos maiores (ex.: um hub hipotético "SOC-CPE-04" não vira "PE").
    """
    if not destino:
        return "OUTROS"
    dest_upper = str(destino).upper()

    ufs = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
           "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"]

    # Padrão "L" + UF (hub local dentro do estado, ex.: LPA = Pará, LMA = Maranhão, LAL = Alagoas)
    m = re.search(r'(?:^|-)L([A-Z]{2})(?=\d|-|$)', dest_upper)
    if m and m.group(1) in ufs:
        return m.group(1)

    # UF isolada logo após o prefixo do tipo de local (ex.: SOC-PE2, SOC-SP8) ou como código direto
    m = re.search(r'(?:^|-)([A-Z]{2})(?=\d|-|$)', dest_upper)
    if m and m.group(1) in ufs:
        return m.group(1)

    return "OUTROS"

def avaliar_tendencia(data):
    """
    Decide se uma LT com margem ainda positiva deve ser classificada como
    TENDÊNCIA DE ATRASO, seguindo a metodologia: tendência = margem pequena +
    um comportamento que está consumindo essa margem (parado, velocidade baixa,
    ocorrência ativa). Velocidade baixa ou parada isoladas, com margem folgada,
    NÃO decretam tendência -- só a combinação dos dois.
    Retorna (True/False, texto do motivo já formatado com o nível).
    """
    margem = data["Margem_Minutos"]
    motivo = data["Motivo_Parada"]
    motivo_eh_neutro = (not motivo) or (motivo in OCORRENCIAS_NEUTRAS)

    sinal_parado = data["Status_Movimento"] == "Parado" and data["Tempo_Horas"] > 0
    sinal_ocorrencia = bool(motivo) and not motivo_eh_neutro
    sinal_velocidade_baixa = 0 < data["Velocidade"] < 40
    tem_sinal = sinal_parado or sinal_ocorrencia or sinal_velocidade_baixa

    if margem < MARGEM_CRITICA_MIN and tem_sinal:
        nivel = "CRÍTICA"
    elif margem < MARGEM_MODERADA_MIN and tem_sinal:
        nivel = "MODERADA"
    elif margem < MARGEM_LEVE_MIN and (sinal_ocorrencia or (sinal_parado and data["Tempo_Horas"] >= PARADA_PROLONGADA_HORAS)):
        nivel = "LEVE"
    else:
        return False, ""

    detalhes = [f"margem de {margem} min"]
    if sinal_parado:
        detalhes.append(f"parado há {data['Tempo_Str']}")
    if sinal_ocorrencia:
        detalhes.append(f"ocorrência: {motivo}")
    if sinal_velocidade_baixa:
        detalhes.append(f"velocidade reduzida ({data['Velocidade']} km/h)")

    return True, f"[TENDÊNCIA {nivel}] " + " | ".join(detalhes) + "."

def process_data_local(text, data_trabalho_str):
    blocks = re.split(r'\n(?=LT[0-9A-Z]+\b)', text.strip())
    parsed_data = []
    
    agora_br = datetime.utcnow() - timedelta(hours=3)
    
    try:
        dt_base = datetime.strptime(data_trabalho_str, "%d/%m/%Y")
        ano_atual = dt_base.year
    except:
        ano_atual = agora_br.year

    for block in blocks:
        if not block.strip().startswith('LT'):
            continue
            
        data = {
            "LT_Full": "", "LT_Short": "", "Motorista": "", 
            "Origem": "", "Destino": "", "UF": "OUTROS", "Pacotes": 0,
            "ETA": "-", "Chegada_Real": "-", "Velocidade": 0, "Distancia_Raw": 0,
            "Distancia_Corrigida": 0, "Fator_Correcao": "",
            "Status_Movimento": "", "Tempo_Str": "0h00", "Tempo_Horas": 0.0,
            "Motivo_Parada": "", "Ultima_Atualizacao_Str": "", "Sem_Sinal": False,
            "Status_Operacional": "Normal", "Classificacao_Desempenho": "No prazo",
            "Motivo_Risco": "", "Margem_Minutos": 999, "ETA_Dt": None,
            "Chegada_Real_Dt": None, "Adiantamento_Minutos": None
        }
        
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        
        first_line = lines[0].split('\t')
        data["LT_Full"] = first_line[0]
        data["LT_Short"] = data["LT_Full"][-5:]
        if len(first_line) > 1:
            data["Motorista"] = first_line[1]
            
        for line in lines:
            clean_line = line.replace('.', '').replace(',', '')
            if clean_line.isdigit():
                val = int(clean_line)
                if 10 <= val <= 99999:
                    data["Pacotes"] = val
                    break
        if data["Pacotes"] == 0:
            nums = re.findall(r'\b\d{3,6}\b', block)
            if nums:
                data["Pacotes"] = int(nums[0])
                
        vel_match = re.search(r'(\d+)\s*km/h', block)
        if vel_match:
            data["Velocidade"] = int(vel_match.group(1))
            
        dist_match = re.search(r'(?m)^(\d+)\s*km$', block)
        if dist_match:
            data["Distancia_Raw"] = int(dist_match.group(1))
            
        block_lower = block.lower()
        if "em trânsito há" in block_lower:
            data["Status_Movimento"] = "Em trânsito"
        elif "parado há" in block_lower:
            data["Status_Movimento"] = "Parado"
            
        time_match = re.search(r'(\d{2}:\d{2}:\d{2})', block)
        if time_match:
            data["Tempo_Str"], data["Tempo_Horas"] = parse_duration(time_match.group(1))
            
        idx_dest = None
        for idx_linha, line in enumerate(lines):
            if ('SOC-' in line or 'HUB-' in line or 'LM ' in line) and '\t' in line:
                parts = line.split('\t')
                data["Origem"] = parts[0]
                if len(parts) > 1:
                    data["Destino"] = parts[1]
                idx_dest = idx_linha
                break
                
        if not data["Destino"]:
            dest_match = re.search(r'\b(SOC-[A-Z0-9\-]+|HUB-[A-Z0-9\-]+|LM\s+[A-Z0-9\-]+|LPA[A-Z0-9\-]*|LMA[A-Z0-9\-]*)\b', block)
            if dest_match:
                data["Destino"] = dest_match.group(1)
                
        data["UF"] = extract_uf(data["Destino"])

        # --- MOTIVO DA OCORRÊNCIA ---
        # Método principal: posicional. Logo depois da linha de Origem/Destino vem a
        # linha de contagem (ex.: "1", "7", ou "--" quando não há ocorrência). Quando
        # não é "--", a linha seguinte é o motivo (texto livre, qualquer que seja),
        # e a linha depois disso é o total de pacotes. Isso evita depender de uma
        # lista fixa de palavras-chave que não cobre motivos novos (ex.: "Morosidade
        # no carregamento").
        if idx_dest is not None and idx_dest + 1 < len(lines):
            linha_contagem = lines[idx_dest + 1]
            if not linha_contagem.startswith('--') and idx_dest + 2 < len(lines):
                candidata = lines[idx_dest + 2]
                candidata_limpa = candidata.replace('.', '').replace(',', '')
                if not candidata_limpa.isdigit():
                    data["Motivo_Parada"] = candidata

        # Método de reforço (fallback): lista de palavras-chave conhecidas, caso a
        # posição acima não capture nada (formato de bloco fora do padrão).
        if not data["Motivo_Parada"]:
            for line in lines:
                if any(kw in line for kw in ['Parada', 'Retenção', 'Acidente', 'Problema', 'Mudança', 'Manutenção', 'Trânsito', 'aderência', 'antecipada', 'documentação', 'fiscal']):
                    data["Motivo_Parada"] = line
                    break
                
        date_pattern = r'\d{2}/\d{2} \d{2}:\d{2}'
        dates_found = re.findall(date_pattern, block)
        
        if len(dates_found) > 0:
            data["Ultima_Atualizacao_Str"] = dates_found[-1]
            try:
                ts_dt = datetime.strptime(f"{data['Ultima_Atualizacao_Str']}/{ano_atual}", "%d/%m %H:%M/%Y")
                if ts_dt > agora_br + timedelta(days=1): ts_dt = ts_dt.replace(year=ano_atual-1)
                if (agora_br - ts_dt).total_seconds() / 3600 >= 1.0 or "Não monitorado" in block:
                    data["Sem_Sinal"] = True
            except: pass

        # --- EXTRAÇÃO DE ETA / CHEGADA REAL ---
        # Logo acima da linha de status ("No prazo"/"Atrasado"/"Risco") vem:
        #   [i-2] ETA programado (sempre uma data)
        #   [i-1] chegada real (data) OU "—"/"-" se o condutor ainda não deu chegada
        for i, line in enumerate(lines):
            if 'No prazo' in line or 'Atrasado' in line or 'Risco' in line:
                if i >= 1:
                    linha_chegada = lines[i-1]
                    if re.match(date_pattern, linha_chegada):
                        data["Chegada_Real"] = linha_chegada
                    elif linha_chegada in ('-', '—'):
                        data["Chegada_Real"] = linha_chegada
                if i >= 2 and re.match(date_pattern, lines[i-2]):
                    data["ETA"] = lines[i-2]

        # Fallback robusto: a primeira data que aparece no bloco é sempre o ETA programado
        if data["ETA"] == "-" and len(dates_found) >= 1:
            data["ETA"] = dates_found[0]

        data["ETA_Dt"] = parse_eta_to_datetime(data["ETA"], ano_atual)
        data["Chegada_Real_Dt"] = parse_eta_to_datetime(data["Chegada_Real"], ano_atual)

        if data["ETA_Dt"] and data["Chegada_Real_Dt"]:
            data["Adiantamento_Minutos"] = int((data["ETA_Dt"] - data["Chegada_Real_Dt"]).total_seconds() / 60)

        if data["UF"] == "MA":
            data["Distancia_Corrigida"] = data["Distancia_Raw"] * FATOR_CORRECAO_MA
            data["Fator_Correcao"] = "(MA +35%)"
        else:
            data["Distancia_Corrigida"] = data["Distancia_Raw"] * FATOR_CORRECAO_GERAL
            data["Fator_Correcao"] = ""

        # --- STATUS OPERACIONAL ---
        # Se a LT já tem chegada real registrada, ela está CONCLUÍDA e sai de qualquer
        # lista de risco/atraso/plano de ação — só analisamos quem ainda está em rota.
        ja_chegou = data["Chegada_Real_Dt"] is not None
        eta_dt = data["ETA_Dt"]

        if ja_chegou:
            data["Status_Operacional"] = "Concluído"
            data["Classificacao_Desempenho"] = "Concluído"
            if eta_dt:
                diff_min = int((data["Chegada_Real_Dt"] - eta_dt).total_seconds() / 60)
                if diff_min > 0:
                    data["Motivo_Risco"] = f"Chegou {diff_min} min após o ETA programado."
                elif diff_min < 0:
                    data["Motivo_Risco"] = f"Chegou {abs(diff_min)} min antes do ETA programado."
                else:
                    data["Motivo_Risco"] = "Chegou no horário programado."
        elif eta_dt and data["Distancia_Raw"] > 0:
            tempo_disp_min = (eta_dt - agora_br).total_seconds() / 60
            data["Margem_Minutos"] = int(tempo_disp_min - data["Distancia_Corrigida"])
            
            if data["Margem_Minutos"] < 0:
                data["Status_Operacional"] = "Delay"
                data["Classificacao_Desempenho"] = "Delay"
                data["Motivo_Risco"] = formatar_deficit_tempo(data["Margem_Minutos"])
            else:
                tem_tendencia, texto_motivo = avaliar_tendencia(data)
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
                data["Motivo_Risco"] = f"Sem sinal desde {data['Ultima_Atualizacao_Str']}."

        parsed_data.append(data)
        
    df_result = pd.DataFrame(parsed_data)
    return df_result

def esta_em_rota(row):
    """
    True se a LT ainda não deu chegada no app (só tem ETA programado, sem segundo horário).
    Usa pd.isna() em vez de 'is None': depois que a coluna entra num DataFrame, o pandas
    costuma converter a coluna inteira pra datetime64, e nesse processo o None vira NaT
    (Not a Time) -- e 'NaT is None' dá False, o que fazia TODA LT parecer "já chegada".
    """
    return pd.isna(row["Chegada_Real_Dt"])

def deve_alertar_tendencia(row):
    """
    Filtro aplicado só às LTs em TENDÊNCIA (aba Tendência de Atraso / Plano de Ação):
    LTs com uma ocorrência JÁ EXPLICADA (motivo diferente de "Parada programada —
    intervalo/refeição") não precisam de alerta repetindo essa explicação -- o
    operador já sabe a causa. Só entram no alerta se, além disso, estiverem perto
    da base (prestes a chegar) ou paradas há muito tempo.
    """
    motivo = row["Motivo_Parada"] or ""
    if motivo == "" or motivo in OCORRENCIAS_NEUTRAS:
        return True
    perto_da_base = row["Distancia_Raw"] <= (KM_ALERTA_LOCALIZACAO_BASE + TOLERANCIA_KM_LOCALIZACAO_BASE)
    parado_muito_tempo = row["Status_Movimento"] == "Parado" and row["Tempo_Horas"] >= LIMIAR_PARADO_LONGO_HORAS
    return perto_da_base or parado_muito_tempo

def classificar_performance(row):
    """
    Classifica a LT (já deve estar filtrada para 'em rota' via esta_em_rota) para fins
    de performance por rota (UF):
    - Delay: a projeção matemática aponta que ela vai perder o ETA (Status_Operacional == "Delay")
    - Early: motivo de ocorrência indica saída antecipada / falta de aderência ao transit time
    - No prazo: tudo o mais
    """
    if row["Status_Operacional"] == "Delay":
        return "Delay"
    motivo = str(row["Motivo_Parada"] or "").lower()
    if "aderência" in motivo or "antecipada" in motivo:
        return "Early"
    return "No prazo"

def calcular_performance_rota(df_uf):
    """
    % de impacto de cada LT = Pacotes da LT / total de Pacotes da rota (dentro do range).
    Ganho = % de impacto se a LT está "No prazo"; 0 se está em Delay ou Early.
    Performance da rota = soma dos ganhos (em %).
    """
    total_pacotes = df_uf["Pacotes"].sum()
    if total_pacotes == 0:
        return 0.0, pd.Series(dtype=float)

    impacto = df_uf["Pacotes"] / total_pacotes
    ganho = impacto.where(df_uf["Classificacao_Performance"] == "No prazo", 0.0)
    performance_pct = ganho.sum() * 100
    return performance_pct, ganho

def generate_report_text(df):
    agora = datetime.utcnow() - timedelta(hours=3)
    data_hora_str = agora.strftime("%d/%m/%Y · %H:%M")

    df = df.copy()
    df["Em_Rota"] = df.apply(esta_em_rota, axis=1)
    df["Minutos_Ate_ETA"] = df["ETA_Dt"].apply(lambda d: (d - agora).total_seconds() / 60 if d else None)

    report = f"# MONITORAMENTO OPERACIONAL — {data_hora_str}\n\n"
    report += f"**Total no recorte:** {len(df)} LTs\n"
    report += "**Referência:** ETA oficial = primeiro horário.\n"
    report += "**Velocidade de cálculo:** 60 km/h ≈ 1 km/min.\n"
    report += "**Distância corrigida:** +25% nas rotas gerais; +30% somente para destinos em MA.\n"
    report += "**Parada programada — intervalo/refeição:** não contabilizada como causa de atraso.\n"
    report += "**LTs que já deram chegada no app não entram em nenhuma lista de risco/atraso abaixo.**\n\n"
    report += "> **Correção importante:** neste recorte, as rotas para **SOC-PE2/SOC-PE4** são tratadas como rotas de PE, portanto a correção é **+25%**, não +30%.\n\n"
    report += "---\n\n"
    
    # DELAY / ATRASO (Status_Operacional == "Delay" já exclui quem chegou, pois esses viram "Concluído")
    report += "# 🚨 DELAY / ATRASO\n\n"
    criticos = df[(df["Status_Operacional"] == "Delay") & (~df["Sem_Sinal"])].copy()
    if criticos.empty:
        report += "Nenhuma LT em delay neste recorte.\n\n"
    else:
        for _, row in criticos.iterrows():
            report += f"## 🔴 {row['LT_Full']} — {row['Motorista']}\n\n"
            report += f"* **ETA:** {row['ETA']}\n"
            report += f"* **Pacotes:** {row['Pacotes']:,}\n"
            report += f"* **Distância:** {row['Distancia_Raw']} km → **{row['Distancia_Corrigida']:.2f} km corrigidos**\n"
            report += f"* **Velocidade:** {row['Velocidade']} km/h\n"
            if row['Status_Movimento'] == 'Parado':
                report += f"* **Parado:** {row['Tempo_Str']}\n"
            if row['Motivo_Parada']:
                report += f"* **Ocorrência:** {row['Motivo_Parada']}\n"
            report += f"* {row['Motivo_Risco']}\n\n"
            report += "**Ação:** Cobrança imediata da situação e acompanhamento.\n\n"

    # TENDÊNCIA DE ATRASO
    report += "# ⚠️ TENDÊNCIA DE ATRASO / RISCO OPERACIONAL\n\n"
    riscos = df[(df["Status_Operacional"] == "Tendência") & (~df["Sem_Sinal"])].copy()
    if riscos.empty:
        report += "Nenhuma tendência de atraso identificada.\n\n"
    else:
        for _, row in riscos.iterrows():
            report += f"## 🟠 {row['LT_Full']} — {row['Motorista']}\n\n"
            report += f"* **Pacotes:** {row['Pacotes']:,}\n"
            report += f"* **ETA:** {row['ETA']}\n"
            report += f"* **Distância:** {row['Distancia_Raw']} km → **{row['Distancia_Corrigida']:.2f} km corrigidos**\n"
            report += f"* **Velocidade:** {row['Velocidade']} km/h\n"
            if row['Motivo_Parada']:
                report += f"* **Ocorrência/Parada:** {row['Motivo_Parada']}\n"
            if row['Motivo_Risco']:
                report += f"* **Evidência:** {row['Motivo_Risco']}\n\n"
            report += "**Ação:** Monitorar e acompanhar recuperação de velocidade.\n\n"

    # SEM SINAL
    report += "# 🚨 SEM SINAL\n\n"
    sem_sinal_df = df[df["Sem_Sinal"] == True].copy()
    if sem_sinal_df.empty:
        report += "Nenhum veículo sem sinal.\n\n"
    else:
        for _, row in sem_sinal_df.iterrows():
            report += f"### 🔴 {row['LT_Full']} — {row['Motorista']}\n\n"
            report += f"* ETA {row['ETA']}\n"
            report += f"* **Sem sinal**\n"
            report += f"* Última posição: {row['Ultima_Atualizacao_Str']}\n\n"
            report += "**Ação:** Escalar imediatamente para localização/comunicação.\n\n"

    # VEÍCULOS PARADOS
    report += "# 🚨 VEÍCULOS PARADOS — RISCO OPERACIONAL\n\n"
    parados_df = df[df["Status_Movimento"] == "Parado"].sort_values(by="Tempo_Horas", ascending=False)
    if parados_df.empty:
        report += "Nenhum veículo parado no momento.\n\n"
    else:
        report += "| LT        | Pacotes | Parado | Avaliação |\n"
        report += "| --------- | ------: | -----: | --------------------------------------- |\n"
        for _, row in parados_df.iterrows():
            report += f"| **{row['LT_Short']}** | {row['Pacotes']:,} | {row['Tempo_Str']} | {row['Status_Operacional']} - {row['Motivo_Parada'] or 'Parado'} |\n"
        report += "\n---\n\n"

    # TOP 5 VOLUMES
    report += "# 📦 TOP 5 — MAIOR VOLUME DE PACOTES\n\n"
    top5 = df.sort_values(by="Pacotes", ascending=False).head(5)
    report += "|  # | LT        | Motorista                    |    Pacotes | Situação |\n"
    report += "| -: | --------- | ---------------------------- | ---------: | --------------------- |\n"
    for i, (_, row) in enumerate(top5.iterrows(), 1):
        medal = "🥇" if i == 1 else ("🥈" if i == 2 else ("🥉" if i == 3 else str(i)))
        report += f"| {medal} | **{row['LT_Short']}** | {row['Motorista']} | **{row['Pacotes']:,}** | {row['Status_Operacional']} |\n"
    report += "\n---\n\n"

    # PONTOS DE ATENÇÃO — CONFIRMAR LOCALIZAÇÃO DA BASE (~60km do destino)
    report += "# 📍 PONTOS DE ATENÇÃO — CONFIRMAR LOCALIZAÇÃO DA BASE\n\n"
    report += f"_LTs em rota a até {KM_ALERTA_LOCALIZACAO_BASE + TOLERANCIA_KM_LOCALIZACAO_BASE} km do destino (mesmo paradas) — envie a localização certa da base pra não errar o local._\n\n"
    proximos_base = df[
        df["Em_Rota"] &
        (df["Distancia_Raw"] <= KM_ALERTA_LOCALIZACAO_BASE + TOLERANCIA_KM_LOCALIZACAO_BASE)
    ].copy()
    if proximos_base.empty:
        report += f"Nenhuma LT a até {KM_ALERTA_LOCALIZACAO_BASE + TOLERANCIA_KM_LOCALIZACAO_BASE} km do destino neste recorte.\n\n"
    else:
        for _, row in proximos_base.iterrows():
            endereco = BASE_ENDERECOS.get(row["Destino"])
            report += f"* **{row['LT_Full']} — {row['Motorista']}** ({row['Distancia_Raw']} km do destino {row['Destino']})\n"
            if endereco:
                report += f"  Enviar localização: {endereco}\n\n"
            else:
                report += f"  Alertar o condutor sobre o local correto da base {row['Destino']}.\n\n"
    report += "---\n\n"

    # PLANO DE AÇÃO IMEDIATO (DINÂMICO E RIGOROSO, BASEADO NO PADRÃO EXIGIDO)
    report += "# 🎯 PLANO DE AÇÃO IMEDIATO\n\n"
    report += "🔴 **COBRAR AGORA**\n\n"
    
    # Filtrar itens críticos para o Cobrar Agora (Delays, Sem Sinal e Riscos com margem <= 30 min ou paradas longas)
    urgentes = pd.concat([
        df[df["Status_Operacional"] == "Delay"],
        df[df["Sem_Sinal"] == True],
        df[(df["Status_Operacional"] == "Tendência") & ((df["Margem_Minutos"] <= 30) | (df["Tempo_Horas"] >= 2.0))]
    ]).drop_duplicates(subset=["LT_Full"])
    
    if urgentes.empty:
        report += "Nenhuma unidade em situação crítica iminente neste recorte.\n\n"
    else:
        for idx, (_, row) in enumerate(urgentes.iterrows(), 1):
            motorista_nome = row['Motorista'] if row['Motorista'] and row['Motorista'] != '-' else 'CONDUTOR NÃO IDENTIFICADO'
            report += f"{idx}. **{row['LT_Full']} — {motorista_nome}**\n"
            
            detalhes = []
            if row['Sem_Sinal']:
                detalhes.append(f"Sem sinal telemétrico desde {row['Ultima_Atualizacao_Str']}.")
            if row['Margem_Minutos'] != 999:
                if row['Margem_Minutos'] < 0:
                    detalhes.append(f"Já em DELAY matemático ({formatar_deficit_tempo(row['Margem_Minutos'])})")
                else:
                    detalhes.append(f"Margem de aproximadamente **{row['Margem_Minutos']} min**.")
            if row['Velocidade'] > 0:
                detalhes.append(f"Velocidade atual: {row['Velocidade']} km/h.")
            if row['Status_Movimento'] == 'Parado':
                detalhes.append(f"Parado há {row['Tempo_Str']}.")
            if row['Motivo_Parada']:
                detalhes.append(f"Ocorrência/Motivo: {row['Motivo_Parada']}.")
            if row['Pacotes'] > 0:
                detalhes.append(f"Volume: {row['Pacotes']:,} pacotes.")
                
            report += f"{' '.join(detalhes)}\n\n"

    # SOLICITAR LIBERAÇÃO DE PORTARIA (bases SP/RJ, ~30km do destino, perto do ETA)
    report += "🚪 **SOLICITAR LIBERAÇÃO DE PORTARIA (bases SP/RJ)**\n\n"
    report += ("_Confira manualmente antes de acionar: se o veículo estiver parado e for descarregar só mais "
               "tarde, pule essa LT — o sistema não sabe o horário de descarga combinado._\n\n")
    portaria_df = df[
        df["Em_Rota"] &
        (df["UF"].isin(["SP", "RJ"])) &
        (df["Distancia_Raw"] >= KM_ALERTA_PORTARIA_SP_RJ - TOLERANCIA_KM_PORTARIA) &
        (df["Distancia_Raw"] <= KM_ALERTA_PORTARIA_SP_RJ + TOLERANCIA_KM_PORTARIA) &
        df["Minutos_Ate_ETA"].notnull() &
        (df["Minutos_Ate_ETA"] <= MINUTOS_PROXIMO_ETA_PORTARIA)
    ].copy()
    if portaria_df.empty:
        report += "Nenhuma LT nessas condições neste recorte.\n\n"
    else:
        for _, row in portaria_df.iterrows():
            minutos = int(row["Minutos_Ate_ETA"])
            report += f"* **{row['LT_Full']} — {row['Motorista']}** — {row['Distancia_Raw']} km do destino ({row['UF']}), ETA em ~{minutos} min.\n\n"

    # RESUMO SIMPLIFICADO
    report += "# RESUMO SIMPLIFICADO\n\n"
    report += "```text\n"
    report += "Delay:\n"
    for _, row in criticos.iterrows():
        report += f"{row['LT_Full']}\n"
    report += "\nTendência de atraso:\n"
    for _, row in riscos.iterrows():
        report += f"{row['LT_Full']}\n"
    report += "\nSem sinal:\n"
    for _, row in sem_sinal_df.iterrows():
        report += f"{row['LT_Full']}\n"
    report += "----------------\n"
    report += "```\n"

    return report

# --- INTERFACE PRINCIPAL ---
st.markdown("<h1 style='text-align: center; color: #ee4d2d;'>🚛 Torre de Controle — Gestão Inteligente de Frotas</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #64748b;'>Monitoramento preditivo, comportamental e logístico avançado em tempo real.</p>", unsafe_allow_html=True)
st.markdown("<br>", unsafe_allow_html=True)

# CAMPO DE DATA DO PLANTÃO POSICIONADO DE FORMA DESTACADA
st.markdown("### 📅 Configuração do Turno")
col_s1, col_s2 = st.columns([3, 7])
with col_s1:
    data_hoje_str = datetime.utcnow().strftime("%d/%m/%Y")
    data_plantao_str = st.text_input("Data de Início do Plantão / Turno D (DD/MM/AAAA):", value=data_hoje_str, placeholder="Ex: 27/09/2026")

if "relatorio_gerado" not in st.session_state:
    st.session_state["relatorio_gerado"] = ""
if "df_parsed" not in st.session_state:
    st.session_state["df_parsed"] = None

with st.container():
    st.markdown("### 📥 Entrada de Dados Operacionais")
    raw_text = st.text_area("Cole abaixo o texto extraído do Losung Web:", height=140, placeholder="Ex: LT01234567 ...")
    col_b1, _ = st.columns([2, 8])
    with col_b1:
        gerar_btn = st.button("Gerar Relatório Analítico")

if gerar_btn:
    if raw_text.strip():
        df_parsed = process_data_local(raw_text, data_plantao_str)
        if df_parsed.empty:
            st.error("⚠️ Nenhum dado válido encontrado para este texto colado.")
            st.session_state["relatorio_gerado"] = ""
            st.session_state["df_parsed"] = None
        else:
            st.session_state["relatorio_gerado"] = generate_report_text(df_parsed)
            st.session_state["df_parsed"] = df_parsed
    else:
        st.warning("⚠️ Insira os dados na caixa de texto acima antes de gerar.")

if st.session_state["relatorio_gerado"]:
    df = st.session_state["df_parsed"]
    
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 📊 Indicadores Operacionais (Score Cards)")
    
    total_lts = len(df)
    qtd_normal = len(df[df["Status_Operacional"] == "Normal"])
    qtd_parados = len(df[df["Status_Movimento"] == "Parado"])
    qtd_tendencia = len(df[df["Status_Operacional"] == "Tendência"])
    qtd_delays = len(df[df["Status_Operacional"] == "Delay"])
    qtd_concluidas = len(df[df["Status_Operacional"] == "Concluído"])

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    with k1:
        st.markdown(f"<div class='metric-card'><div class='metric-title'>Total de LTs</div><div class='metric-value'>{total_lts}</div></div>", unsafe_allow_html=True)
    with k2:
        st.markdown(f"<div class='metric-card'><div class='metric-title'>No Prazo (em rota)</div><div class='metric-value' style='color: #10b981;'>{qtd_normal}</div></div>", unsafe_allow_html=True)
    with k3:
        st.markdown(f"<div class='metric-card'><div class='metric-title'>Veículos Parados</div><div class='metric-value' style='color: #f59e0b;'>{qtd_parados}</div></div>", unsafe_allow_html=True)
    with k4:
        st.markdown(f"<div class='metric-card'><div class='metric-title'>Tendência Atraso</div><div class='metric-value' style='color: #d97706;'>{qtd_tendencia}</div></div>", unsafe_allow_html=True)
    with k5:
        st.markdown(f"<div class='metric-card'><div class='metric-title'>Delays</div><div class='metric-value' style='color: #dc2626;'>{qtd_delays}</div></div>", unsafe_allow_html=True)
    with k6:
        st.markdown(f"<div class='metric-card'><div class='metric-title'>Concluídas</div><div class='metric-value' style='color: #64748b;'>{qtd_concluidas}</div></div>", unsafe_allow_html=True)

    st.markdown("<br><br>", unsafe_allow_html=True)

    tab_relatorio, tab_performance, tab_atrasadas, tab_parados, tab_tendencia, tab_top10, tab_tabela = st.tabs([
        "📋 Relatório Formatado", 
        "🌐 Performance por Rota (UF)",
        "🔴 LTs Atrasadas",
        "🛑 Veículos Parados", 
        "⚠️ Tendência de Atraso", 
        "📦 Top 10 Volumes", 
        "📊 Tabela Analítica Completa"
    ])

    with tab_relatorio:
        st.markdown("#### 📋 Pré-visualização do Relatório no Formato Solicitado")
        st.info("O texto abaixo está formatado exatamente com o template operacional exigido:")
        st.text_area("Texto formatado completo:", value=st.session_state["relatorio_gerado"], height=400)

    with tab_performance:
        st.markdown("#### 🌐 Performance por Rota (UF) — Filtrado pelo Turno D")
        st.info(
            f"ℹ️ Exibindo apenas as LTs **ainda em rota** (sem chegada registrada) com ETA dentro do turno (12x36): "
            f"**19:00 de {data_plantao_str} até 15:00 do dia seguinte**. LTs que já deram chegada no app não entram nesta análise."
        )

        # --- FILTRO: janela do turno (19:00 -> 15:00 do dia seguinte) + só quem está em rota ---
        try:
            dt_base = datetime.strptime(data_plantao_str, "%d/%m/%Y")
            inicio_turno = dt_base.replace(hour=19, minute=0, second=0, microsecond=0)
            fim_turno = inicio_turno + timedelta(hours=20)  # 19:00 -> 15:00 do dia seguinte

            df_perf = df[
                df["ETA_Dt"].notnull() &
                (df["ETA_Dt"] >= inicio_turno) &
                (df["ETA_Dt"] <= fim_turno) &
                df.apply(esta_em_rota, axis=1)
            ].copy()
        except ValueError:
            st.error(f"⚠️ Data de plantão inválida: '{data_plantao_str}'. Use o formato DD/MM/AAAA.")
            df_perf = df.iloc[0:0].copy()  # vazio — nunca cai para "mostrar tudo"

        if not df_perf.empty:
            df_perf["Classificacao_Performance"] = df_perf.apply(classificar_performance, axis=1)

            total_perf = len(df_perf)
            qtd_no_prazo_total = len(df_perf[df_perf["Classificacao_Performance"] == "No prazo"])
            qtd_delay_total = len(df_perf[df_perf["Classificacao_Performance"] == "Delay"])
            qtd_early_total = len(df_perf[df_perf["Classificacao_Performance"] == "Early"])

            st.markdown("##### 📊 Resumo do Turno (LTs em rota, dentro do range)")
            r1, r2, r3, r4 = st.columns(4)
            with r1:
                st.markdown(f"<div class='metric-card'><div class='metric-title'>Total em Rota</div><div class='metric-value'>{total_perf}</div></div>", unsafe_allow_html=True)
            with r2:
                st.markdown(f"<div class='metric-card'><div class='metric-title'>No Prazo</div><div class='metric-value' style='color:#10b981;'>{qtd_no_prazo_total}</div></div>", unsafe_allow_html=True)
            with r3:
                st.markdown(f"<div class='metric-card'><div class='metric-title'>Delay</div><div class='metric-value' style='color:#dc2626;'>{qtd_delay_total}</div></div>", unsafe_allow_html=True)
            with r4:
                st.markdown(f"<div class='metric-card'><div class='metric-title'>Early</div><div class='metric-value' style='color:#3b82f6;'>{qtd_early_total}</div></div>", unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            ufs_disponiveis = sorted(df_perf["UF"].unique())

            for uf in ufs_disponiveis:
                df_uf = df_perf[df_perf["UF"] == uf]
                performance_pct, _ = calcular_performance_rota(df_uf)

                qtd_no_prazo = len(df_uf[df_uf["Classificacao_Performance"] == "No prazo"])
                qtd_delay = len(df_uf[df_uf["Classificacao_Performance"] == "Delay"])
                qtd_early = len(df_uf[df_uf["Classificacao_Performance"] == "Early"])

                st.markdown("---")
                st.markdown(f"### 📍 Rota: **{uf}**")
                if len(df_uf) <= 2:
                    st.caption("⚠️ Amostra pequena (poucas LTs) — a % de performance pode não ser representativa.")

                col_uf1, col_uf2 = st.columns([4, 6])
                with col_uf1:
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown(f"* **Total de LTs (Turno D):** `{len(df_uf)}`")
                    st.markdown(f"* **Volume Total de Pacotes:** `{df_uf['Pacotes'].sum():,}`")
                    st.markdown(f"* 🟢 **No Prazo:** `{qtd_no_prazo}`")
                    st.markdown(f"* 🔴 **Delay:** `{qtd_delay}`")
                    st.markdown(f"* 🔵 **Early:** `{qtd_early}`")
                    st.markdown(
                        f"<div class='metric-card' style='margin-top:10px;'>"
                        f"<div class='metric-title'>Performance da Rota</div>"
                        f"<div class='metric-value' style='color:#ee4d2d;'>{performance_pct:.1f}%</div>"
                        f"</div>",
                        unsafe_allow_html=True
                    )

                with col_uf2:
                    fig_uf = px.pie(
                        df_uf,
                        names="Classificacao_Performance",
                        title=f"Distribuição de LTs — {uf} (Turno D)",
                        color="Classificacao_Performance",
                        color_discrete_map={"No prazo": "#10b981", "Delay": "#dc2626", "Early": "#3b82f6"},
                        hole=0.4
                    )
                    fig_uf.update_layout(margin=dict(t=30, b=10, l=10, r=10), height=240)
                    st.plotly_chart(fig_uf, use_container_width=True, key=f"pie_{uf}")

                # LTs que não vão chegar dentro do ETA (Delay) e as em Early, com a ocorrência
                impactantes = df_uf[df_uf["Classificacao_Performance"].isin(["Delay", "Early"])].copy()
                if not impactantes.empty:
                    st.markdown("**🚨 LTs que não vão chegar dentro do ETA / impactaram a performance:**")
                    tabela_impacto = impactantes[
                        ["LT_Short", "Motorista", "Classificacao_Performance", "Motivo_Parada", "ETA", "Distancia_Raw", "Velocidade"]
                    ].rename(columns={
                        "LT_Short": "LT",
                        "Classificacao_Performance": "Situação",
                        "Motivo_Parada": "Ocorrência",
                        "Distancia_Raw": "Distância (km)"
                    })
                    tabela_impacto["Ocorrência"] = tabela_impacto["Ocorrência"].replace("", "—")
                    st.dataframe(tabela_impacto, use_container_width=True, hide_index=True)
                else:
                    st.caption("Nenhuma LT impactou negativamente a performance desta rota.")
        else:
            st.warning(
                f"Nenhuma LT em rota encontrada com ETA entre 19:00 de {data_plantao_str} "
                f"e 15:00 do dia seguinte (Turno D)."
            )

    with tab_atrasadas:
        st.markdown("#### 🔴 LTs Atrasadas")
        st.caption("Só LTs ainda em rota (sem chegada registrada) — quem já chegou não entra aqui.")
        df_atrasadas = df[df["Status_Operacional"] == "Delay"]
        if not df_atrasadas.empty:
            tabela_atraso = df_atrasadas[
                ["LT_Short", "Motorista", "UF", "ETA", "Motivo_Parada", "Motivo_Risco", "Pacotes", "Velocidade", "Distancia_Raw"]
            ].rename(columns={
                "LT_Short": "LT",
                "ETA": "ETA Destino",
                "Motivo_Parada": "Motivo da Ocorrência",
                "Motivo_Risco": "Detalhe do Atraso",
                "Distancia_Raw": "Distância (km)"
            })
            tabela_atraso["Motivo da Ocorrência"] = tabela_atraso["Motivo da Ocorrência"].replace("", "—")
            st.dataframe(tabela_atraso, use_container_width=True, hide_index=True)
        else:
            st.success("Nenhuma LT atrasada neste recorte.")

    with tab_parados:
        st.markdown("#### 🛑 Veículos Parados")
        df_parados = df[df["Status_Movimento"] == "Parado"]
        if not df_parados.empty:
            st.dataframe(df_parados[["LT_Short", "Motorista", "Pacotes", "Tempo_Str", "Destino", "Motivo_Parada"]], use_container_width=True, hide_index=True)
        else:
            st.success("Nenhum veículo parado.")

    with tab_tendencia:
        st.markdown("#### ⚠️ Tendência de Atraso")
        st.caption("Só LTs ainda em rota — quem já chegou não entra aqui.")
        df_tendencia = df[df["Status_Operacional"] == "Tendência"]
        if not df_tendencia.empty:
            st.dataframe(df_tendencia[["LT_Short", "Motorista", "Pacotes", "ETA", "Motivo_Risco"]], use_container_width=True, hide_index=True)
        else:
            st.success("Nenhuma tendência de atraso.")

    with tab_top10:
        st.markdown("#### 📦 Top Volumes")
        st.dataframe(df.sort_values(by="Pacotes", ascending=False).head(10)[["LT_Short", "Motorista", "Pacotes", "ETA", "Destino"]], use_container_width=True, hide_index=True)

    with tab_tabela:
        st.markdown("#### 📊 Tabela Analítica Completa")
        st.dataframe(df[["LT_Short", "Motorista", "Pacotes", "UF", "Status_Operacional", "Status_Movimento", "Velocidade", "ETA", "Chegada_Real", "Destino"]], use_container_width=True, hide_index=True)
