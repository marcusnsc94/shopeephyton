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
            if any(kw in line for kw in ['Parada', 'Retenção', 'Acidente', 'Problema', 'Mudança', 'Manutenção', 'Trânsito', 'aderência', 'antecipada', 'documentação']):
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

        # Regra de Distância Corrigida (+30% MA, EXCETO SOC-PE2/SOC-PE4 que são PE portanto +25%)
        dest_upper = str(data["Destino"]).upper()
        if "MA" in dest_upper and "SOC-PE" not in dest_upper:
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
                data["Motivo_Risco"] = f"Déficit matemático de {abs(data['Margem_Minutos'])} min em relação ao ETA (60 km/h)."
            else:
                sinais_deterioracao = False
                motivos = []
                
                if data["Status_Movimento"] == "Parado" and data["Tempo_Horas"] >= 0.5:
                    sinais_deterioracao = True
                    motivos.append(f"Parado há {data['Tempo_Str']} ({data['Motivo_Parada'] or 'Parado'})")
                
                if data["Motivo_Parada"] and any(k in data["Motivo_Parada"] for k in ['Retenção', 'Acidente', 'Problema', 'Manutenção', 'Trânsito', 'Fiscal', 'Restrição', 'documentação']):
                    sinais_deterioracao = True
                    motivos.append(f"Ocorrência ativa: {data['Motivo_Parada']}")
                
                if data["Margem_Minutos"] < 90 and 0 < data["Velocidade"] < 40:
                    sinais_deterioracao = True
                    motivos.append(f"Velocidade reduzida ({data['Velocidade']} km/h) com margem apertada ({data['Margem_Minutos']} min).")
                elif data["Velocidade"] <= 10 and data["Status_Movimento"] == "Em trânsito":
                    sinais_deterioracao = True
                    motivos.append(f"Velocidade extremamente baixa em trânsito ({data['Velocidade']} km/h).")

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
                data["Motivo_Risco"] = f"Sem sinal desde {data['Ultima_Atualizacao_Str']}."

        parsed_data.append(data)
        
    df_result = pd.DataFrame(parsed_data)
    return df_result

def generate_report_text(df):
    agora = datetime.utcnow() - timedelta(hours=3)
    data_hora_str = agora.strftime("%d/%m/%Y · %H:%M")
    
    report = f"# MONITORAMENTO OPERACIONAL — {data_hora_str}\n\n"
    report += f"**Total no recorte:** {len(df)} LTs\n"
    report += "**Referência:** ETA oficial = primeiro horário.\n"
    report += "**Velocidade de cálculo:** 60 km/h ≈ 1 km/min.\n"
    report += "**Distância corrigida:** +25% nas rotas gerais; +30% somente para destinos em MA.\n"
    report += "**Parada programada — intervalo/refeição:** não contabilizada como causa de atraso.\n\n"
    report += "> **Correção importante:** neste recorte, as rotas para **SOC-PE2/SOC-PE4** são tratadas como rotas de PE, portanto a correção é **+25%**, não +30%.\n\n"
    report += "---\n\n"
    
    # DELAY / ATRASO
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

    # PLANO DE AÇÃO IMEDIATO
    report += "# 🎯 PLANO DE AÇÃO IMEDIATO\n\n"
    report += "### 🔴 COBRAR AGORA\n"
    report += "Acionar imediatamente os veículos em Delay e sem sinal.\n\n"
    report += "### 🟠 MONITORAR PRÓXIMOS 30 MIN\n"
    report += "Acompanhar os veículos em tendência de atraso e parados.\n\n"
    report += "### 🟡 ESCALAR SE NÃO HOUVER EVOLUÇÃO\n"
    report += "Escalonar criticidades persistentes.\n\n"
    report += "### 🟢 SEM NECESSIDADE DE AÇÃO IMEDIATA\n"
    report += "Demais LTs com margem compatível.\n\n"

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

col_s1, col_s2 = st.columns([3, 7])
with col_s1:
    data_hoje_str = datetime.utcnow().strftime("%d/%m/%Y")
    data_plantao_str = st.text_input("Data de Início do Plantão (DD/MM/AAAA):", value=data_hoje_str, placeholder="Ex: 27/09/2026")

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

    tab_relatorio, tab_performance, tab_parados, tab_tendencia, tab_top10, tab_tabela = st.tabs([
        "📋 Relatório Formatado", 
        "🌐 Performance por Rota (UF)",
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
        st.markdown("#### 🌐 Performance por Rota (UF) e Distribuição de Status")
        
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.markdown("##### Volume e LTs por UF")
            ufs_disponiveis = df["UF"].unique()
            for uf in sorted(ufs_disponiveis):
                df_uf = df[df["UF"] == uf]
                st.markdown(f"* **{uf}**: {len(df_uf)} LTs | **{df_uf['Pacotes'].sum():,}** pacotes")
                
        with col_p2:
            # Gráfico de Pizza restaurado
            fig_status = px.pie(
                df, 
                names="Status_Operacional", 
                title="Proporção de Status Operacional",
                color="Status_Operacional",
                color_discrete_map={"Normal": "#10b981", "Tendência": "#f59e0b", "Delay": "#dc2626"},
                hole=0.4
            )
            fig_status.update_layout(margin=dict(t=30, b=10, l=10, r=10), height=280)
            st.plotly_chart(fig_status, use_container_width=True)

    with tab_parados:
        st.markdown("#### 🛑 Veículos Parados")
        df_parados = df[df["Status_Movimento"] == "Parado"]
        if not df_parados.empty:
            st.dataframe(df_parados[["LT_Short", "Motorista", "Pacotes", "Tempo_Str", "Destino", "Motivo_Parada"]], use_container_width=True, hide_index=True)
        else:
            st.success("Nenhum veículo parado.")

    with tab_tendencia:
        st.markdown("#### ⚠️ Tendência de Atraso")
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
        st.dataframe(df[["LT_Short", "Motorista", "Pacotes", "UF", "Status_Operacional", "Status_Movimento", "Velocidade", "ETA", "Destino"]], use_container_width=True, hide_index=True)
