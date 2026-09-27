import streamlit as st
import pandas as pd
import re
from datetime import datetime, timedelta

st.set_page_config(page_title="Torre de Controle", layout="wide")

st.title("🚛 Torre de Controle - Análise Rápida de LTs")
st.markdown("Cole os dados do Losung Web (modo texto) para gerar o relatório operacional.")

raw_text = st.text_area("Cole os dados do Dashboard aqui (Ctrl+A no site -> Ctrl+C -> Ctrl+V aqui):", height=200)

def is_early_alert(sla_str, eta_str, status_ignicao, distancia_km):
    # 1. Regra: Estar em movimento (Ignição Ligada)
    if status_ignicao != 'Ligada':
        return False
        
    # 2. Regra: Menos de 60 km do destino
    if distancia_km is None or distancia_km >= 60:
        return False
        
    # 3. Regra: Risco de chegar 30 min (ou mais) antes do horário programado
    try:
        if not sla_str or not eta_str or eta_str == '-': return False
        
        ano_atual = datetime.now().year
        sla_dt = datetime.strptime(f"{sla_str}/{ano_atual}", "%d/%m %H:%M/%Y")
        eta_dt = datetime.strptime(f"{eta_str}/{ano_atual}", "%d/%m %H:%M/%Y")
        
        # Calcula diferença
        diferenca_segundos = (sla_dt - eta_dt).total_seconds()
        
        # Se for maior ou igual a 30 minutos (1800 segundos)
        if diferenca_segundos >= 1800:
            return True
        return False
    except:
        return False

def check_sem_sinal(block_text, last_update_str):
    # Regra: Veículos explicitamente sem rastreador na matriz
    if "Não monitorado" in block_text or "Sem viagem ativa" in block_text:
        return True
    
    # Regra: Mais de 1 hora sem comunicação (baseado na última data do cartão)
    if last_update_str:
        try:
            ano_atual = datetime.now().year
            last_update_dt = datetime.strptime(f"{last_update_str}/{ano_atual}", "%d/%m %H:%M/%Y")
            
            # Horário atual em Brasília (UTC-3)
            agora = datetime.utcnow() - timedelta(hours=3)
            
            # Tratamento caso o ano vire e o log seja de dezembro
            if last_update_dt > agora + timedelta(days=1):
                last_update_dt = last_update_dt.replace(year=ano_atual - 1)
                
            diferenca_horas = (agora - last_update_dt).total_seconds() / 3600
            
            if diferenca_horas >= 1.0: # 1 Hora exata
                return True
        except:
            pass
            
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
            "Ignição/Sinal": "", "Motivo da Parada": "", 
            "Distância (km)": None, "Última Comunicação": "",
            "Alerta Early?": "Não", "Sem Sinal?": "Não"
        }
        
        first_line = lines[0].split('\t')
        data["LT"] = first_line[0]
        if len(first_line) > 1:
            data["Motorista"] = first_line[1]
            
        date_pattern = r'\d{2}/\d{2} \d{2}:\d{2}'
        
        # Puxa a última data/hora registada no bloco de texto (O ping do satélite)
        for line in reversed(lines):
            m = re.search(date_pattern, line)
            if m:
                data["Última Comunicação"] = m.group(0)
                break
                
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
                
                # Coleta ETA e SLA (1 e 2 linhas acima do status)
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
                        
                # Coleta Distância (km)
                for j in range(i+1, min(i+5, len(lines))):
                    m_dist = re.match(r'^(\d+)\s*km$', lines[j].strip())
                    if m_dist:
                        data["Distância (km)"] = int(m_dist.group(1))
                        break

        if "Não monitorado" in block or "Sem viagem ativa" in block:
            data["Ignição/Sinal"] = "--"

        # Aplicar Regras de Negócio Avançadas
        if is_early_alert(data["Previsão (SLA)"], data["ETA"], data["Ignição/Sinal"], data["Distância (km)"]):
            data["Alerta Early?"] = "Sim 🟢"
            
        if check_sem_sinal(block, data["Última Comunicação"]):
            data["Sem Sinal?"] = "Sim 🔴"

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
            st.metric("Sem Sinal/Posição (> 1h)", len(df[df["Sem Sinal?"] == "Sim 🔴"]))
        with col3:
            st.metric("Alertas Críticos de Early", len(df[df["Alerta Early?"] == "Sim 🟢"]))

        st.divider()

        # 1. Alertas de Early (Regra: Ligado, < 60km, > 30min adiantado)
        st.subheader("🟢 Alertas de Early (Risco Iminente)")
        df_early = df[df["Alerta Early?"] == "Sim 🟢"]
        if not df_early.empty:
            st.dataframe(df_early[["LT", "Motorista", "Origem", "Destino", "Previsão (SLA)", "ETA", "Distância (km)"]], use_container_width=True)
        else:
            st.info("Nenhum veículo em risco de Early neste momento.")

        # 2. Sem Sinal (> 1 hora)
        st.subheader("📡 Veículos Sem Sinal (> 1 hora sem atualização de posição)")
        df_sinal = df[df["Sem Sinal?"] == "Sim 🔴"]
        if not df_sinal.empty:
            st.dataframe(df_sinal[["LT", "Motorista", "Última Comunicação", "Origem", "Destino", "Status"]], use_container_width=True)
        else:
            st.info("Todos os veículos comunicaram na última hora.")
            
        # 3. Tendência de Atraso (Ocorrências)
        st.subheader("⚠️ Ocorrências Operacionais (Paradas/Retenções)")
        df_atraso = df[(df["Status"] != "No prazo") | (df["Motivo da Parada"] != "")]
        if not df_atraso.empty:
            st.dataframe(df_atraso[["LT", "Motorista", "Status", "Motivo da Parada", "Previsão (SLA)"]], use_container_width=True)
        else:
            st.info("Nenhuma ocorrência registada.")
            
        # 4. Tabela Completa (Para Debug ou Consulta)
        with st.expander("Ver Tabela Completa Extraída (Base de Dados)"):
            st.dataframe(df, use_container_width=True)
