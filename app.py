import streamlit as st
import pandas as pd
import re
from datetime import datetime

st.set_page_config(page_title="Torre de Controle", layout="wide")

st.title("🚛 Torre de Controle - Análise Rápida de LTs")
st.markdown("Cole os dados do Losung Web (modo texto) para gerar o relatório operacional.")

raw_text = st.text_area("Cole os dados do Dashboard aqui (Ctrl+A no site -> Ctrl+C -> Ctrl+V aqui):", height=200)

def is_early(sla_str, eta_str):
    try:
        if not sla_str or not eta_str or eta_str == '-': return False
        sla_dt = datetime.strptime(f"{sla_str}/2024", "%d/%m %H:%M/%Y")
        eta_dt = datetime.strptime(f"{eta_str}/2024", "%d/%m %H:%M/%Y")
        return eta_dt < sla_dt
    except:
        return False

def parse_data(text):
    blocks = re.split(r'\n(?=LT[0-9A-Z]+\b)', text.strip())
    parsed_data = []
    
    for block in blocks:
        if not block.strip().startswith('LT'):
            continue
            
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        
        data = {
            "LT": "", "Motorista": "", "Origem": "", "Destino": "",
            "Previsão (SLA)": "", "ETA": "", "Status": "",
            "Ignição/Sinal": "", "Motivo da Parada": "", "Early?": "Não"
        }
        
        first_line = lines[0].split('\t')
        data["LT"] = first_line[0]
        if len(first_line) > 1:
            data["Motorista"] = first_line[1]
            
        date_pattern = r'\d{2}/\d{2} \d{2}:\d{2}'
        
        for i, line in enumerate(lines):
            if ('SOC-' in line or 'HUB-' in line or 'LM ' in line) and '\t' in line:
                parts = line.split('\t')
                data["Origem"] = parts[0]
                if len(parts) > 1:
                    data["Destino"] = parts[1]
                    
            if any(kw in line for kw in ['Parada', 'Retenção', 'Acidente', 'Problema', 'Mudança', 'Manutenção', 'Trânsito']):
                data["Motivo da Parada"] = line

            if 'No prazo' in line or 'Atrasado' in line or 'Risco' in line:
                parts = line.split('\t')
                data["Status"] = parts[0]
                if len(parts) > 1:
                    data["Ignição/Sinal"] = parts[1]
                
                if i >= 1:
                    eta_line = lines[i-1]
                    if re.match(date_pattern, eta_line):
                        data["ETA"] = eta_line
                    elif eta_line == '—':
                        data["ETA"] = "-"
                if i >= 2:
                    sla_line = lines[i-2]
                    if re.match(date_pattern, sla_line):
                        data["Previsão (SLA)"] = sla_line

        if "Não monitorado" in block or "Sem viagem ativa" in block:
            data["Ignição/Sinal"] = "Sem Sinal"

        if is_early(data["Previsão (SLA)"], data["ETA"]):
            data["Early?"] = "Sim 🟢"

        parsed_data.append(data)
        
    return pd.DataFrame(parsed_data)

if raw_text:
    df = parse_data(raw_text)
    
    if df.empty:
        st.error("Nenhum dado válido encontrado. Certifique-se de que copiou as LTs corretamente.")
    else:
        st.success(f"{len(df)} veículos processados com sucesso!")
        
        # --- DASHBOARD DE AÇÃO ---
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total de LTs Lidas", len(df))
        with col2:
            st.metric("Veículos Sem Sinal/Desligados", len(df[df["Ignição/Sinal"].isin(["Desligada", "--", "Sem Sinal"])]))
        with col3:
            st.metric("Veículos Adiantados (Early)", len(df[df["Early?"] == "Sim 🟢"]))

        st.divider()

        # 1. Alertas de Early
        st.subheader("🟢 Alertas de Early (Chegada Antecipada)")
        df_early = df[df["Early?"] == "Sim 🟢"]
        if not df_early.empty:
            st.dataframe(df_early[["LT", "Motorista", "Origem", "Destino", "Previsão (SLA)", "ETA"]], use_container_width=True)
        else:
            st.info("Nenhum veículo adiantado no momento.")

        # 2. Sem Sinal ou Desligados
        st.subheader("📡 Veículos Sem Sinal ou Ignição Desligada")
        df_sinal = df[df["Ignição/Sinal"].isin(["Desligada", "--", "Sem Sinal"])]
        if not df_sinal.empty:
            st.dataframe(df_sinal[["LT", "Motorista", "Ignição/Sinal", "Motivo da Parada", "Status"]], use_container_width=True)
        else:
            st.info("Todos os veículos estão a transmitir corretamente.")
            
        # 3. Tendência de Atraso (Ocorrências)
        st.subheader("⚠️ Ocorrências (Paradas Indevidas/Retenções)")
        df_atraso = df[(df["Status"] != "No prazo") | (df["Motivo da Parada"] != "")]
        if not df_atraso.empty:
            st.dataframe(df_atraso[["LT", "Motorista", "Status", "Motivo da Parada", "Previsão (SLA)"]], use_container_width=True)
        else:
            st.info("Nenhuma ocorrência grave registada.")
            
        # 4. Tabela Completa
        with st.expander("Ver Tabela Completa Extraída"):
            st.dataframe(df, use_container_width=True)
