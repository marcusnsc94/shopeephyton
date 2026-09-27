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

def extract_uf(destino):
    if not destino: return "OUTROS"
    dest_upper = str(destino).upper()
    if "LPA" in dest_upper: return "PA"
    if "LMA" in dest_upper: return "MA"
    
    ufs = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"]
    for uf in ufs:
        if uf in dest_upper:
            return uf
    return "OUTROS"

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
            "Origem": "", "Destino": "", "UF": "OUTROS", "Pacotes": 0,
            "SLA": "", "ETA": "-", "Velocidade": 0, "Distancia_Raw": 0,
            "Distancia_Corrigida": 0, "Fator_Correcao": "",
            "Status_Movimento": "", "Tempo_Str": "0h00", "Tempo_Horas": 0.0,
            "Motivo_Parada": "", "Ultima_Atualizacao_Str": "", "Sem_Sinal": False,
            "Status_Operacional": "Normal", "Classificacao_Desempenho": "No prazo",
            "Motivo_Risco": "", "Margem_Minutos": 999, "ETA_Dt": None
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
            dest_match = re.search(r'\b(SOC-[A-Z0-9\-]+|HUB-[A-Z0-9\-]+|LM\s+[A-Z0-9\-]+|LPA[A-Z0-9\-]*|LMA[A-Z0-9\-]*)\b', block)
            if dest_match:
                data["Destino"] = dest_match.group(1)
                
        data["UF"] = extract_uf(data["Destino"])
                
        for line in lines:
            if any(kw in line for kw in ['Parada', 'Retenção', 'Acidente', 'Problema', 'Mudança', 'Manutenção', 'Trânsito', 'aderência', 'antecipada']):
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

        for i, line in enumerate(lines):
            if 'No prazo' in line or 'Atrasado' in line or 'Risco' in line:
                if i >= 1 and (re.match(date_pattern, lines[i-1]) or lines[i-1] != ''):
                    data["ETA"] = lines[i-1]
                if i >= 2 and re.match(date_pattern, lines[i-2]):
                    data["SLA"] = lines[i-2]
                    
        if data["ETA"] == "-" and len(dates_found) >= 1:
            data["ETA"] = dates_found[0]

        data["ETA_Dt"] = parse_eta_to_datetime(data["ETA"], ano_atual)

        if "MA" in data["Destino"] or data["UF"] == "MA":
            data["Distancia_Corrigida"] = data["Distancia_Raw"] * 1.30
            data["Fator_Correcao"] = "(MA)"
        else:
            data["Distancia_Corrigida"] = data["Distancia_Raw"] * 1.25
            data["Fator_Correcao"] = ""
            
        eta_dt = data["ETA_Dt"]
        if eta_dt and data["Distancia_Raw"] > 0:
            tempo_disp_min = (eta_dt - agora_br).total_seconds() / 60
            data["Margem_Minutos"] = int(tempo_disp_min - data["Distancia_Corrigida"])
            
            if data["Margem_Minutos"] < 0:
                data["Status_Operacional"] = "Delay"
                data["Classificacao_Desempenho"] = "Delay"
                data["Motivo_Risco"] = f"Déficit matemático de {abs(data['Margem_Minutos'])} min em relação ao ETA."
            else:
                sinais_deterioracao = False
                motivos = []
                if data["Status_Movimento"] == "Parado" and data["Tempo_Horas"] >= 0.5:
                    sinais_deterioracao = True
                    motivos.append(f"Parado há {data['Tempo_Str']} ({data['Motivo_Parada'] or 'Sem motivo'})")
                
                if any(k in data["Motivo_Parada"] for k in ['Retenção', 'Acidente', 'Problema', 'Manutenção', 'Trânsito']):
                    sinais_deterioracao = True
                    motivos.append(f"Ocorrência: {data['Motivo_Parada']}")

                if sinais_deterioracao:
                    data["Status_Operacional"] = "Tendência"
                    data["Classificacao_Desempenho"] = "No prazo"
                    data["Motivo_Risco"] = " | ".join(motivos)
                else:
                    data["Status_Operacional"] = "Normal"
                    data["Classificacao_Desempenho"] = "No prazo"
        else:
            if data["Sem_Sinal"]:
                data["Status_Operacional"] = "Tendência"
                data["Motivo_Risco"] = f"Sem atualização desde {data['Ultima_Atualizacao_Str']}."

        motivo_lower = data["Motivo_Parada"].lower()
        if "aderência ao transit time" in motivo_lower or "saída antecipada" in motivo_lower or "early" in motivo_lower:
            data["Classificacao_Desempenho"] = "Early"
        elif data["Status_Operacional"] == "Delay" or "atrasado" in motivo_lower:
            data["Classificacao_Desempenho"] = "Delay"

        parsed_data.append(data)
        
    return pd.DataFrame(parsed_data)

def generate_report_text(df):
    agora = datetime.utcnow() - timedelta(hours=3)
    data_hora_str = agora.strftime("%d/%m/%Y · %H:%M")
    
    report = f"**MONITORAMENTO OPERACIONAL — {data_hora_str}**\n"
    report += f"Total no recorte: {len(df)} LTs\n\n"
    
    criticos = df[df["Status_Operacional"] == "Delay"].copy()
    report += "🚨 **DELAY / ATRASO MATEMÁTICO**\n"
    if criticos.empty:
        report += "Nenhuma LT em delay neste recorte.\n\n"
    else:
        for _, row in criticos.iterrows():
            report += f"⚠️ **{row['LT_Short']} — {row['Motorista']}** (ETA: {row['ETA']} | Pcts: {row['Pacotes']:,})\n\n"

    report += "⚠️ **TENDÊNCIA DE ATRASO**\n"
    riscos = df[df["Status_Operacional"] == "Tendência"].copy()
    if riscos.empty:
        report += "Nenhuma tendência de atraso.\n\n"
    else:
        for _, row in riscos.iterrows():
            report += f"- **{row['LT_Short']}** (ETA: {row['ETA']} | Pcts: {row['Pacotes']:,}) - {row['Motivo_Risco']}\n"
    
    report += "\n----------------\n"
    return report

# --- INTERFACE PRINCIPAL ---
st.markdown("<h1 style='text-align: center; color: #ee4d2d;'>🚛 Torre de Controle — Gestão Inteligente de Frotas</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #64748b;'>Monitoramento preditivo, comportamental e logístico avançado em tempo real.</p>", unsafe_allow_html=True)
st.markdown("<br>", unsafe_allow_html=True)

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
        df_parsed = process_data_local(raw_text)
        if df_parsed.empty:
            st.error("⚠️ Nenhum dado válido encontrado.")
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
    tab_relatorio, tab_performance, tab_parados, tab_tendencia, tab_top10, tab_tabela = st.tabs([
        "📋 Relatório Formatado", 
        "🌐 Performance por Rota (UF)",
        "🛑 Veículos Parados", 
        "⚠️ Tendência de Atraso", 
        "📦 Top 10 Volumes", 
        "📊 Tabela Analítica Completa"
    ])

    with tab_relatorio:
        st.markdown("#### 📋 Pré-visualização do Relatório")
        st.code(st.session_state["relatorio_gerado"], language="markdown")

    with tab_performance:
        st.markdown("#### 🌐 Performance por Rota (UF) — Turno Operacional")
        st.info("📅 **Range do Turno (Shift D):** ETA de 19:00 do dia atual até 15:00 do dia seguinte.")
        
        ufs_disponiveis = df["UF"].unique()
        
        for uf in sorted(ufs_disponiveis):
            df_uf = df[df["UF"] == uf].copy()
            total_pcts_uf = df_uf["Pacotes"].sum()
            
            if total_pcts_uf == 0: continue
            
            ganho_total = 0.0
            for _, row in df_uf.iterrows():
                impacto = row["Pacotes"] / total_pcts_uf
                status_perf = row["Classificacao_Desempenho"]
                ganho = impacto if status_perf == "No prazo" else 0.0
                ganho_total += ganho
            
            performance_rota = ganho_total * 100.0
            
            st.markdown(f"### 📍 Rota / UF: **{uf}** | Performance: **{performance_rota:.2f}%**")
            st.markdown(f"*Total de Pacotes na Rota: **{total_pcts_uf:,}** | LTs Analisadas: **{len(df_uf)}***")
            
            col_chart, col_motivos = st.columns([6, 4])
            
            with col_chart:
                contagem_status = df_uf["Classificacao_Desempenho"].value_counts().reset_index()
                contagem_status.columns = ["Status", "Quantidade"]
                
                fig = px.pie(
                    contagem_status, 
                    names="Status", 
                    values="Quantidade", 
                    title=f"Distribuição de LTs - Rota {uf}",
                    hole=0.4,
                    color="Status",
                    color_discrete_map={"No prazo": "#10b981", "Delay": "#dc2626", "Early": "#3b82f6"}
                )
                fig.update_layout(margin=dict(t=30, b=10, l=10, r=10), height=280)
                st.plotly_chart(fig, use_container_width=True)
                
            with col_motivos:
                st.markdown("##### 🔍 Motivos de Impacto / Ocorrências")
                df_motivos = df_uf[df_uf["Motivo_Parada"] != ""]["Motivo_Parada"].value_counts().reset_index()
                if not df_motivos.empty:
                    df_motivos.columns = ["Motivo", "Ocorrências"]
                    st.dataframe(df_motivos, use_container_width=True, hide_index=True)
                else:
                    st.success("Nenhuma ocorrência registrada para esta rota.")
                    
            st.markdown("---")

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
        view_geral = df[["LT_Short", "Motorista", "Pacotes", "UF", "Status_Operacional", "Status_Movimento", "Velocidade", "Margem_Minutos", "ETA", "Destino"]].copy()
        view_geral.columns = ["LT", "Motorista", "Pacotes", "UF", "Status Op.", "Movimento", "Vel. (km/h)", "Margem (min)", "ETA Destino", "Destino"]
        st.dataframe(view_geral, use_container_width=True, hide_index=True)
