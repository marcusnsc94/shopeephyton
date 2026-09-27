import streamlit as st
import pandas as pd
import re
from datetime import datetime, timedelta

st.set_page_config(page_title="Gerador de Relatórios - Torre de Controle", layout="wide")

# --- ESTILIZAÇÃO CSS (Botão Laranja Shopee) ---
st.markdown(
    """
    <style>
    div.stButton > button {
        background-color: #ee4d2d !important;
        color: white !important;
        font-weight: bold !important;
        border: none !important;
        border-radius: 6px !important;
        width: 100%;
        padding: 0.6rem 1rem;
        font-size: 16px;
    }
    div.stButton > button:hover {
        background-color: #d73a1d !important;
        color: white !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# --- FUNÇÕES DE PROCESSAMENTO (Declaradas primeiro) ---
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
        if not eta_str or eta_str == '-': return None
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
            "SLA": "", "ETA": "", "Velocidade": 0, "Distancia_Raw": 0,
            "Distancia_Corrigida": 0, "Fator_Correcao": "",
            "Status_Movimento": "", "Tempo_Str": "", "Tempo_Horas": 0.0,
            "Motivo_Parada": "", "Ultima_Atualizacao_Str": "", "Sem_Sinal": False,
            "Status_Operacional": "Normal", "Motivo_Risco": "",
            "Margem_Minutos": 0, "Tempo_Disponivel_Min": 0, "Tempo_Necessario_Min": 0
        }
        
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        
        first_line = lines[0].split('\t')
        data["LT_Full"] = first_line[0]
        data["LT_Short"] = data["LT_Full"][-5:]
        if len(first_line) > 1:
            data["Motorista"] = first_line[1]
            
        for line in lines:
            if re.match(r'^\d{3,6}$', line):
                data["Pacotes"] = int(line)
                break
                
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
                if i >= 1 and (re.match(date_pattern, lines[i-1]) or lines[i-1] == '—'):
                    data["ETA"] = lines[i-1]
                if i >= 2 and re.match(date_pattern, lines[i-2]):
                    data["SLA"] = lines[i-2]

        # Correção de distância (+30% para MA, +25% para os demais)
        if "MA" in data["Destino"]:
            data["Distancia_Corrigida"] = data["Distancia_Raw"] * 1.30
            data["Fator_Correcao"] = "(MA)"
        else:
            data["Distancia_Corrigida"] = data["Distancia_Raw"] * 1.25
            data["Fator_Correcao"] = ""
            
        # --- MOTOR DE ANÁLISE RIGOROSO (Matemática + Comportamento) ---
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

    report += "📦 **TOP 5 — MAIOR VOLUME DE PACOTES**\n"
    top5 = df.sort_values(by="Pacotes", ascending=False).head(5)
    report += "| Rank | LT | Motorista | Pacotes | Status | ETA |\n"
    report += "|---|---|---|---|---|---|\n"
    medalhas = ["🥇", "🥈", "🥉", "4", "5"]
    for i, (_, row) in enumerate(top5.iterrows()):
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
        
    # --- NOVO GRUPO: VERIFICAR PARADA INDEVIDA ---
    report += "\nVerificar parada indevida:\n"
    # Condição: Parado há mais de 1h30 (1.5 horas), não chegou ao destino (distância raw > 0 ou não finalizado) e ETA ainda válido (margem >= 0)
    paradas_indevidas = df[(df["Status_Movimento"] == "Parado") & (df["Tempo_Horas"] > 1.5) & (df["Margem_Minutos"] >= 0)].copy()
    if not paradas_indevidas.empty:
        for _, row in paradas_indevidas.iterrows():
            report += f"{row['LT_Full']} (Parado há {row['Tempo_Str']}, Distância: {row['Distancia_Raw']} km, ETA: {row['ETA']})\n"
    else:
        report += "Nenhum\n"
        
    report += "----------------\n"
    
    return report

# --- INTERFACE DO USUÁRIO (Executada após as funções) ---
st.title("🚛 Gerador de Relatórios Automatizado - Shopee")
st.markdown("Cole os dados do Losung Web e clique no botão para gerar o relatório operacional.")

if "relatorio_gerado" not in st.session_state:
    st.session_state["relatorio_gerado"] = ""
if "df_parsed" not in st.session_state:
    st.session_state["df_parsed"] = None

raw_text = st.text_area("Cole os dados do Dashboard aqui:", height=150)

# Botão Laranja para acionar a geração
if st.button("Gerar relatório agora!"):
    if raw_text.strip():
        df_parsed = process_data_local(raw_text)
        if df_parsed.empty:
            st.error("Nenhum dado válido encontrado. Verifique se copiou corretamente.")
            st.session_state["relatorio_gerado"] = ""
            st.session_state["df_parsed"] = None
        else:
            st.session_state["relatorio_gerado"] = generate_report_text(df_parsed)
            st.session_state["df_parsed"] = df_parsed
    else:
        st.warning("Por favor, cole os dados do dashboard na caixa de texto acima antes de gerar o relatório.")

# Exibir resultado guardado no session_state se existir
if st.session_state["relatorio_gerado"]:
    st.success("Dados lidos com sucesso! Relatório atualizado com o grupo 'Verificar parada indevida'.")
    st.text_area("Copie o texto abaixo (Ctrl+A e Ctrl+C):", value=st.session_state["relatorio_gerado"], height=600)
    
    with st.expander("Ver base de dados extraída (Para conferência)"):
        st.dataframe(st.session_state["df_parsed"])
