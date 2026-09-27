import streamlit as st
import pandas as pd
import re
from datetime import datetime, timedelta

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Torre de Controle — Shopee",
    page_icon="🚛",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- ESTILIZAÇÃO CSS AVANÇADA (UI/UX Corporativa) ---
st.markdown(
    """
    <style>
    .main {
        background-color: #f4f6f9;
    }
    
    /* Cartões de Métricas Modernos */
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

    /* Botão Principal Shopee */
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

def parse_eta_to_datetime(eta_str, ano_atual):
    try:
        if not eta_str or eta_str == '-' or eta_str == '—': return None
        return datetime.strptime(f"{eta_str}/{ano_atual}", "%d/%m %H:%M/%Y")
    except:
        return None

def process_data_local(text):
    blocks = re.split(r'\n(?=LT[0-9A-Z]+\b)', text.strip())
    parsed_data = []
    
    agora_br = datetime.utcnow() - timedelta(hours=3)
    ano_atual = agora_br.year
    
    for block in blocks:
        if not block.strip().startswith('LT'):
            continue
            
        data = {
            "LT_Full": "", "LT_Short": "", "Motorista": "", 
            "Origem": "", "Destino": "", "Pacotes": 0,
            "SLA": "", "ETA": "-", "Velocidade": 0, "Distancia_Raw": 0,
            "Distancia_Corrigida": 0, "Fator_Correcao": "",
            "Status_Movimento": "", "Tempo_Str": "0h00", "Tempo_Horas": 0.0,
            "Motivo_Parada": "", "Ultima_Atualizacao_Str": "", "Sem_Sinal": False,
            "Status_Operacional": "Normal", "Motivo_Risco": "",
            "Margem_Minutos": 999, "Tempo_Disponivel_Min": 0, "Tempo_Necessario_Min": 0
        }
        
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        
        first_line = lines[0].split('\t')
        data["LT_Full"] = first_line[0]
        data["LT_Short"] = data["LT_Full"][-5:]
        if len(first_line) > 1:
            data["Motorista"] = first_line[1]
            
        # Extração robusta de pacotes
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
            
        if "em trânsito há" in block:
            data["Status_Movimento"] = "Em trânsito"
        elif "parado há" in block:
            data["Status_Movimento"] = "Parado"
            
        time_match = re.search(r'(\d{2}:\d{2}:\d{2})', block)
        if time_match:
            data["Tempo_Str"], data["Tempo_Horas"] = parse_duration(time_match.group(1))
            
        for line in lines:
            if ('SOC-' in line or 'HUB-' in line or 'LM ' in line) and '\t' in line:
                parts = line.split('\t')
                data["Origem"] = parts[0]
                if len(parts) > 1:
                    data["Destino"] = parts[1]
                break
                
        if not data["Destino"]:
            dest_match = re.search(r'\b(SOC-[A-Z0-9\-]+|HUB-[A-Z0-9\-]+|LM\s+[A-Z0-9\-]+)\b', block)
            if dest_match:
                data["Destino"] = dest_match.group(1)
                
        for line in lines:
            if any(kw in line for kw in ['Parada', 'Retenção', 'Acidente', 'Problema', 'Mudança', 'Manutenção', 'Trânsito']):
                data["Motivo_Parada"] = line
                break
                
        date_pattern = r'\d{2}/\d{2} \d{2}:\d{2}'
        dates_found = re.findall(date_pattern, block)
        
        if len(dates_found) > 0:
            data["Ultima_Atualizacao_Str"] = dates_found[-1]
            try:
                ts_dt = datetime.strptime(f"{data['Ultima_Atualizacao_Str']}/{ano_atual}", "%d/%m %H:%M/%Y")
                if ts_dt > agora_br + timedelta(days=1): ts_dt = ts_dt.replace(year=ano_atual-1)
                diff_horas = (agora_br - ts_dt).total_seconds() / 3600
                if diff_horas >= 1.0 or "Não monitorado" in block:
                    data["Sem_Sinal"] = True
            except: pass

        for i, line in enumerate(lines):
            if 'No prazo' in line or 'Atrasado' in line or 'Risco' in line:
                if i >= 1 and (re.match(date_pattern, lines[i-1]) or lines[i-1] != ''):
                    data["ETA"] = lines[i-1]
                if i >= 2 and re.match(date_pattern, lines[i-2]):
                    data["SLA"] = lines[i-2]
                    
        if data["ETA"] == "-" and len(dates_found) >= 1:
            data["ETA"] = dates_found[0]

        if "MA" in data["Destino"]:
            data["Distancia_Corrigida"] = data["Distancia_Raw"] * 1.30
            data["Fator_Correcao"] = "(MA)"
        else:
            data["Distancia_Corrigida"] = data["Distancia_Raw"] * 1.25
            data["Fator_Correcao"] = ""
            
        eta_dt = parse_eta_to_datetime(data["ETA"], ano_atual)
        if eta_dt and data["Distancia_Raw"] > 0:
            tempo_disp_min = (eta_dt - agora_br).total_seconds() / 60
            data["Tempo_Disponivel_Min"] = int(tempo_disp_min)
            
            tempo_nec_min = data["Distancia_Corrigida"]
            data["Tempo_Necessario_Min"] = int(tempo_nec_min)
            
            margem = tempo_disp_min - tempo_nec_min
            data["Margem_Minutos"] = int(margem)
            
            if margem < 0:
                data["Status_Operacional"] = "Delay"
                data["Motivo_Risco"] = f"Déficit matemático de {abs(int(margem))} min em relação ao ETA oficial."
            else:
                sinais_deterioracao = False
                motivos = []
                
                is_parada_programada = "programada" in data["Motivo_Parada"].lower() or "intervalo" in data["Motivo_Parada"].lower()
                
                if data["Status_Movimento"] == "Parado" and data["Tempo_Horas"] >= 0.5:
                    if not (is_parada_programada and margem > 180):
                        sinais_deterioracao = True
                        motivos.append(f"Parado há {data['Tempo_Str']} ({data['Motivo_Parada'] or 'Sem motivo especificado'})")
                
                if any(k in data["Motivo_Parada"] for k in ['Retenção', 'Acidente', 'Problema', 'Manutenção', 'Trânsito']):
                    if not is_parada_programada:
                        sinais_deterioracao = True
                        motivos.append(f"Ocorrência ativa: {data['Motivo_Parada']}")

                if data["Status_Movimento"] == "Em trânsito" and 0 < data["Velocidade"] < 35 and margem < 90:
                    sinais_deterioracao = True
                    motivos.append(f"Velocidade reduzida ({data['Velocidade']} km/h) com margem restrita de {int(margem)} min.")

                if margem < 30 and data["Velocidade"] < 50:
                    sinais_deterioracao = True
                    motivos.append(f"Margem de ETA extremamente baixa ({int(margem)} min) com velocidade de {data['Velocidade']} km/h.")

                if sinais_deterioracao:
                    data["Status_Operacional"] = "Tendência"
                    data["Motivo_Risco"] = " | ".join(motivos)
                else:
                    data["Status_Operacional"] = "Normal"
        else:
            if data["Sem_Sinal"]:
                data["Status_Operacional"] = "Tendência"
                data["Motivo_Risco"] = f"Veículo sem atualização recente desde {data['Ultima_Atualizacao_Str']}."
            else:
                data["Status_Operacional"] = "Normal"

        parsed_data.append(data)
        
    return pd.DataFrame(parsed_data)

def generate_report_text(df):
    agora = datetime.utcnow() - timedelta(hours=3)
    data_hora_str = agora.strftime("%d/%m/%Y · %H:%M")
    
    report = f"**MONITORAMENTO OPERACIONAL — {data_hora_str}**\n"
    report += f"Total no recorte: {len(df)} LTs\n"
    report += "Referência: ETA oficial = primeiro horário informado.\n"
    report += "Cálculo: 60 km/h ≈ 1 km/min, com distância corrigida em +25% (ou +30% para o Maranhão).\n"
    report += "Critério de Tendência: ETA ainda viável matematicamente, mas com evidências operacionais de consumo de margem.\n\n"
    
    criticos = df[df["Status_Operacional"] == "Delay"].copy()
    
    report += "🚨 **DELAY / ATRASO MATEMÁTICO**\n"
    if criticos.empty:
        report += "Neste recorte, nenhuma LT está matematicamente em DELAY pelo ETA.\n"
        report += "Os ETAs viáveis estão sendo monitorados preventivamente.\n\n"
    else:
        for _, row in criticos.iterrows():
            report += f"⚠️ **{row['LT_Short']} — {row['Motorista']}**\n"
            report += f"ETA: {row['ETA']} | Pacotes: {row['Pacotes']:,}\n"
            report += f"Distância: {row['Distancia_Raw']} km → ~{row['Distancia_Corrigida']:.1f} km corrigido {row['Fator_Correcao']}\n"
            report += f"Análise: {row['Motivo_Risco']}\n"
            report += "Ação: cobrar tratativa imediata de atraso/estouro de ETA.\n\n"

    report += "⚠️ **TENDÊNCIA DE ATRASO (Preventivo)**\n"
    riscos = df[df["Status_Operacional"] == "Tendência"].copy()
    
    if riscos.empty:
        report += "Nenhuma LT apresenta tendência de atraso com base na análise combinada de margem, velocidade e comportamento.\n\n"
    else:
        count_risco = 1
        for _, row in riscos.iterrows():
            report += f"{count_risco}. **{row['LT_Short']} — {row['Motorista']}**\n"
            report += f"📦 {row['Pacotes']:,} pacotes | ETA: {row['ETA']}\n"
            report += f"Distância: {row['Distancia_Raw']} km → {row['Distancia_Corrigida']:.1f} km corrigidos {row['Fator_Correcao']} | Margem atual: ~{row['Margem_Minutos']} min\n"
            report += f"Status: {row['Status_Movimento']} ({row['Velocidade']} km/h)"
            if row['Tempo_Horas'] > 0: report += f", há {row['Tempo_Str']}"
            report += "\n"
            report += f"Evidência / Motivo: {row['Motivo_Risco']}\n"
            
            if row['Sem_Sinal']:
                report += f"Comunicação: Última atualização em {row['Ultima_Atualizacao_Str']} (Sem sinal recente).\n"
                
            report += "Ação: "
            if row['Sem_Sinal']: report += "verificar posicionamento/comunicação imediatamente.\n\n"
            elif "Retenção" in row['Motivo_Parada']: report += "acompanhar liberação no posto fiscal e retomada.\n\n"
            elif row['Status_Movimento'] == 'Parado': report += "confirmar se a parada é válida e cobrar retomada imediata.\n\n"
            else: report += "cobrar aceleração e monitorar os próximos 30 minutos.\n\n"
            count_risco += 1

    report += "🚨 **VEÍCULOS PARADOS — ANÁLISE OPERACIONAL**\n"
    parados = df[(df["Status_Movimento"] == "Parado") & (df["Tempo_Horas"] >= 1.0)].copy()
    if not parados.empty:
        report += "| LT | Pacotes | Parado | Margem ETA | Situação | Ação |\n"
        report += "|---|---|---|---|---|---|\n"
        for _, row in parados.iterrows():
            sit = "Parada programada" if "programada" in row['Motivo_Parada'].lower() else "Posto fiscal" if "fiscal" in row['Motivo_Parada'].lower() else "Manutenção/Outros"
            acao = "Cobrar retomada" if row['Margem_Minutos'] < 60 else "Monitorar"
            report += f"| {row['LT_Short']} | {row['Pacotes']:,} | {row['Tempo_Str']} | {row['Margem_Minutos']} min | {sit} | {acao} |\n"
    else:
        report += "Nenhum veículo parado há mais de 1 hora.\n"
    report += "\n"

    report += "📦 **TOP 10 — MAIOR VOLUME DE PACOTES**\n"
    top10 = df.sort_values(by="Pacotes", ascending=False).head(10)
    report += "| Rank | LT | Motorista | Pacotes | Status | ETA Destino |\n"
    report += "|---|---|---|---|---|---|\n"
    medalhas = ["🥇", "🥈", "🥉", "4º", "5º", "6º", "7º", "8º", "9º", "10º"]
    for i, (_, row) in enumerate(top10.iterrows()):
        report += f"| {medalhas[i]} | {row['LT_Short']} | {row['Motorista']} | {row['Pacotes']:,} | {row['Status_Operacional']} | {row['ETA']} |\n"
    report += "\n"

    report += "🎯 **PLANO DE AÇÃO IMEDIATO**\n"
    report += "🔴 **Cobrar agora (Tendências Críticas / Sem Sinal)**\n"
    for _, row in df[(df["Status_Operacional"] == "Tendência") & ((df["Sem_Sinal"] == True) | (df["Margem_Minutos"] < 30))].iterrows():
        report += f"- {row['LT_Short']} ({row['Pacotes']:,} pcts) → Margem de {row['Margem_Minutos']} min. {row['Motivo_Risco']}\n"
    
    report += "\n🟠 **Monitorar próximos 30-60 min**\n"
    for _, row in df[(df["Status_Operacional"] == "Tendência") & (df["Sem_Sinal"] == False) & (df["Margem_Minutos"] >= 30)].iterrows():
        report += f"- {row['LT_Short']} ({row['Pacotes']:,} pcts) — Margem de {row['Margem_Minutos']} min. {row['Motivo_Risco']}\n"

    report += "\n🟢 **Normal / Dentro do Prazo**\n"
    report += "As demais LTs apresentam margem de ETA saudável e sem comportamentos de risco no momento.\n\n"

    # --- RESUMO SIMPLIFICADO ---
    report += "**RESUMO SIMPLIFICADO**\n"
    
    report += "Delay:\n"
    if not criticos.empty:
        for _, row in criticos.iterrows():
            report += f"{row['LT_Full']}\n"
    else:
        report += "Nenhum\n"
        
    report += "\nTendência de atraso:\n"
    if not riscos.empty:
        for _, row in riscos.iterrows():
            report += f"{row['LT_Full']} (Margem: {row['Margem_Minutos']} min)\n"
    else:
        report += "Nenhuma\n"
        
    report += "\nSem sinal:\n"
    sem_sinal_df = df[df["Sem_Sinal"] == True]
    if not sem_sinal_df.empty:
        for _, row in sem_sinal_df.iterrows():
            report += f"{row['LT_Full']}\n"
    else:
        report += "Nenhum\n"
        
    report += "\nVerificar parada indevida:\n"
    paradas_indevidas = df[(df["Status_Movimento"] == "Parado") & (df["Tempo_Horas"] > 1.5) & (df["Margem_Minutos"] >= 0)].copy()
    if not paradas_indevidas.empty:
        for _, row in paradas_indevidas.iterrows():
            report += f"{row['LT_Full']} (Parado há {row['Tempo_Str']}, Distância: {row['Distancia_Raw']} km, ETA: {row['ETA']})\n"
    else:
        report += "Nenhum\n"
        
    report += "----------------\n"
    
    return report

# --- INTERFACE PRINCIPAL ---
st.markdown("<h1 style='text-align: center; color: #ee4d2d;'>🚛 Torre de Controle — Gestão Inteligente de Frotas</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #64748b;'>Monitoramento preditivo, comportamental e logístico avançado em tempo real.</p>", unsafe_allow_html=True)
st.markdown("<br>", unsafe_allow_html=True)

if "relatorio_gerado" not in st.session_state:
    st.session_state["relatorio_gerado"] = ""
if "df_parsed" not in st.session_state:
    st.session_state["df_parsed"] = None

# Área de Entrada de Dados
with st.container():
    st.markdown("### 📥 Entrada de Dados Operacionais")
    raw_text = st.text_area("Cole abaixo o texto extraído do Losung Web:", height=140, placeholder="Ex: LT01234567 ...")
    
    col_b1, _ = st.columns([2, 8])
    with col_b1:
        gerar_btn = st.button("Gerar Relatório Analítico")

if gerar_btn:
    if raw_text.strip():
        df_parsed = process_data_local(raw_text)
        if df_parsed.empty:
            st.error("⚠️ Nenhum dado válido encontrado. Certifique-se de copiar corretamente do dashboard.")
            st.session_state["relatorio_gerado"] = ""
            st.session_state["df_parsed"] = None
        else:
            st.session_state["relatorio_gerado"] = generate_report_text(df_parsed)
            st.session_state["df_parsed"] = df_parsed
    else:
        st.warning("⚠️ Insira os dados na caixa de texto acima antes de gerar.")

# Se houver dados processados, exibe os score cards na ordem exata solicitada e as abas
if st.session_state["relatorio_gerado"]:
    df = st.session_state["df_parsed"]
    
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 📊 Indicadores Operacionais (Score Cards)")
    
    # Cálculos dos KPIs
    total_lts = len(df)
    qtd_normal = len(df[df["Status_Operacional"] == "Normal"])
    qtd_parados = len(df[df["Status_Movimento"] == "Parado"])
    qtd_tendencia = len(df[df["Status_Operacional"] == "Tendência"])
    qtd_delays = len(df[df["Status_Operacional"] == "Delay"])

    # Ordem rigorosa dos score cards:
    # 1. Total de LTs | 2. Veículos no prazo | 3. Veículos parados | 4. Veículos com tendência de atraso | 5. Delays
    k1, k2, k3, k4, k5 = st.columns(5)
    
    with k1:
        st.markdown(f"<div class='metric-card'><div class='metric-title'>Total de LTs</div><div class='metric-value'>{total_lts}</div></div>", unsafe_allow_html=True)
    with k2:
        st.markdown(f"<div class='metric-card'><div class='metric-title'>Veículos no Prazo</div><div class='metric-value' style='color: #10b981;'>{qtd_normal}</div></div>", unsafe_allow_html=True)
    with k3:
        st.markdown(f"<div class='metric-card'><div class='metric-title'>Veículos Parados</div><div class='metric-value' style='color: #f59e0b;'>{qtd_parados}</div></div>", unsafe_allow_html=True)
    with k4:
        st.markdown(f"<div class='metric-card'><div class='metric-title'>Tendência Atraso</div><div class='metric-value' style='color: #d97706;'>{qtd_tendencia}</div></div>", unsafe_allow_html=True)
    with k5:
        st.markdown(f"<div class='metric-card'><div class='metric-title'>Delays</div><div class='metric-value' style='color: #dc2626;'>{qtd_delays}</div></div>", unsafe_allow_html=True)

    st.markdown("<br><br>", unsafe_allow_html=True)

    # --- ABAS ORGANIZADAS ---
    tab_relatorio, tab_parados, tab_tendencia, tab_top10, tab_tabela = st.tabs([
        "📋 Relatório Formatado", 
        "🛑 Veículos Parados", 
        "⚠️ Tendência de Atraso", 
        "📦 Top 10 Volumes", 
        "📊 Tabela Analítica Completa"
    ])

    with tab_relatorio:
        st.markdown("#### 📋 Pré-visualização do Relatório")
        st.markdown("O texto abaixo está formatado de forma limpa e profissional. Utilize o botão no canto superior direito do bloco para copiar instantaneamente:")
        st.code(st.session_state["relatorio_gerado"], language="markdown")
        
    with tab_parados:
        st.markdown("#### 🛑 Veículos Parados (Ordenados por Maior Tempo Parado)")
        df_parados = df[df["Status_Movimento"] == "Parado"].sort_values(by="Tempo_Horas", ascending=False)
        if not df_parados.empty:
            view_parados = df_parados[["LT_Short", "Motorista", "Pacotes", "Tempo_Str", "ETA", "Destino", "Motivo_Parada"]].copy()
            view_parados.columns = ["LT", "Motorista", "Pacotes", "Tempo Parado", "ETA Destino", "Destino", "Motivo da Parada"]
            st.dataframe(view_parados, use_container_width=True, hide_index=True)
        else:
            st.success("Nenhum veículo parado no momento neste recorte.")

    with tab_tendencia:
        st.markdown("#### ⚠️ Veículos em Tendência de Atraso (Ordenados por Menor Gordura / Margem)")
        df_tendencia = df[df["Status_Operacional"] == "Tendência"].sort_values(by="Margem_Minutos", ascending=True)
        if not df_tendencia.empty:
            view_tendencia = df_tendencia[["LT_Short", "Motorista", "Pacotes", "Margem_Minutos", "ETA", "Velocidade", "Motivo_Risco", "Destino"]].copy()
            view_tendencia.columns = ["LT", "Motorista", "Pacotes", "Margem (min)", "ETA Destino", "Vel. (km/h)", "Evidência / Motivo", "Destino"]
            st.dataframe(view_tendencia, use_container_width=True, hide_index=True)
        else:
            st.success("Nenhum veículo com tendência de atraso identificada.")

    with tab_top10:
        st.markdown("#### 📦 Top 10 Maiores Volumes de Carga")
        df_top10 = df.sort_values(by="Pacotes", ascending=False).head(10)
        view_top10 = df_top10[["LT_Short", "Motorista", "Pacotes", "Status_Operacional", "ETA", "Destino"]].copy()
        view_top10.columns = ["LT", "Motorista", "Pacotes", "Status Operacional", "ETA Destino", "Destino"]
        st.dataframe(view_top10, use_container_width=True, hide_index=True)

    with tab_tabela:
        st.markdown("#### 📊 Detalhamento Geral da Frota (Tabela Analítica)")
        view_geral = df[["LT_Short", "Motorista", "Pacotes", "Status_Operacional", "Status_Movimento", "Velocidade", "Margem_Minutos", "ETA", "Destino"]].copy()
        view_geral.columns = ["LT", "Motorista", "Pacotes", "Status Op.", "Movimento", "Vel. (km/h)", "Margem (min)", "ETA Destino", "Destino"]
        st.dataframe(view_geral, use_container_width=True, hide_index=True)
