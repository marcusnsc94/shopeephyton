import streamlit as st
import pandas as pd
import re
from datetime import datetime, timedelta

st.set_page_config(page_title="Gerador de Relatórios - Torre de Controle", layout="wide")

st.title("🚛 Gerador de Relatórios Automatizado - Shopee")
st.markdown("Cole os dados do Losung Web para gerar o texto do relatório operacional.")

raw_text = st.text_area("Cole os dados do Dashboard aqui:", height=150)

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

def process_data(text):
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
            "Risco_Atraso": False, "Motivo_Risco": ""
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
            
        # --- MOTOR DE CÁLCULO DE TENDÊNCIA DE ATRASO (RIGOROSO) ---
        eta_dt = parse_eta_to_datetime(data["ETA"], ano_atual)
        if eta_dt and data["Distancia_Raw"] > 0:
            vel_calculo = data["Velocidade"] if data["Velocidade"] > 10 else 50
            horas_necessarias = data["Distancia_Corrigida"] / vel_calculo
            eta_calculado = agora_br + timedelta(hours=horas_necessarias)
            
            margem_minutos = (eta_dt - eta_calculado).total_seconds() / 60
            
            # Critérios inteligentes e rígidos:
            # 1. Margem de folga inferior a 30 min (ou cerca de 10 min)
            if margem_minutos < 30:
                data["Risco_Atraso"] = True
                data["Motivo_Risco"] = f"Margem de ETA muito justa ({int(margem_minutos)} min de folga estimada)."
            
            # 2. Distância longa (> 600 km) com folga inferior a 2 horas (120 min)
            elif data["Distancia_Raw"] > 600 and margem_minutos < 120:
                data["Risco_Atraso"] = True
                data["Motivo_Risco"] = f"Distância longa ({data['Distancia_Raw']} km) com margem reduzida ({int(margem_minutos/60)}h), sujeito a paragens de percurso."
            
            # 3. Veículo parado há muito tempo com impacto no ETA
            elif data["Status_Movimento"] == "Parado" and data["Tempo_Horas"] > 2.0 and margem_minutos < 180:
                data["Risco_Atraso"] = True
                data["Motivo_Risco"] = f"Parado há {data['Tempo_Str']} com risco de comprometer o ETA."

        parsed_data.append(data)
        
    return pd.DataFrame(parsed_data)

def generate_report_text(df):
    agora = datetime.utcnow() - timedelta(hours=3)
    data_hora_str = agora.strftime("%d/%m/%Y · %H:%M")
    
    report = f"**MONITORAMENTO OPERACIONAL — {data_hora_str}**\n"
    report += f"Total no recorte: {len(df)} LTs\n"
    report += "Referência: ETA oficial = primeiro horário informado.\n"
    report += "Cálculo: 60 km/h ≈ 1 km/min, com distância corrigida em +25%; rotas para MA em +30%.\n"
    report += "Observação: não vou considerar “Parada programada — intervalo/refeição” como causa de atraso.\n\n"
    
    criticos = df[(df["Distancia_Raw"] <= 50) & (df["Distancia_Raw"] > 0) & (df["Velocidade"] < 20)].copy()
    
    report += "🚨 **DELAY / ATRASO**\n"
    if criticos.empty:
        report += "Neste recorte, nenhuma LT está matematicamente em DELAY pelo ETA.\n"
        report += "Os ETAs mais próximos ainda têm margem suficiente, mas há algumas situações que exigem cobrança preventiva.\n\n"
    else:
        for _, row in criticos.iterrows():
            report += f"⚠️ **{row['LT_Short']} — {row['Motorista']}**\n"
            report += f"ETA: {row['ETA']}\n"
            report += f"Distância: {row['Distancia_Raw']} km → ~{row['Distancia_Corrigida']:.1f} km corrigido {row['Fator_Correcao']}\n"
            report += f"Velocidade: {row['Velocidade']} km/h\n"
            report += f"Pacotes: {row['Pacotes']:,}\n"
            report += "Está praticamente no destino e o ETA está no limite.\n"
            report += "Ação: cobrar confirmação de chegada.\n\n"

    report += "⚠️ **TENDÊNCIA / RISCO OPERACIONAL**\n"
    
    riscos = df[df["Risco_Atraso"] == True].copy()
    
    if not criticos.empty:
        riscos = riscos[~riscos['LT_Full'].isin(criticos['LT_Full'])]
        
    if riscos.empty:
        report += "Nenhuma LT apresenta tendência de atraso com base na análise dinâmica de distância, velocidade e margem de ETA.\n\n"
    else:
        count_risco = 1
        for _, row in riscos.iterrows():
            report += f"{count_risco}. **{row['LT_Short']} — {row['Motorista']}**\n"
            report += f"{row['Pacotes']:,} pacotes\n"
            report += f"ETA {row['ETA']}\n"
            report += f"{row['Distancia_Raw']} km → {row['Distancia_Corrigida']:.1f} km corrigidos {row['Fator_Correcao']}\n"
            report += f"{row['Velocidade']} km/h\n"
            
            if row['Status_Movimento'] == 'Parado':
                report += f"Parado há {row['Tempo_Str']}\n"
            
            if row['Motivo_Parada']: report += f"{row['Motivo_Parada']}\n"
            
            if row['Sem_Sinal']:
                report += f"A última atualização do veículo foi em {row['Ultima_Atualizacao_Str']}, portanto a comunicação merece atenção.\n"
                
            report += f"Análise de Risco: {row['Motivo_Risco']}\n"
            
            report += "Ação: "
            if row['Sem_Sinal']: report += "verificar posicionamento/comunicação imediatamente.\n\n"
            elif "Retenção" in row['Motivo_Parada']: report += "acompanhar liberação e retomada.\n\n"
            elif "Manutenção" in row['Motivo_Parada']: report += "cobrar previsão de liberação se continuar parado.\n\n"
            elif row['Status_Movimento'] == 'Parado': report += "confirmar se a parada é operacionalmente válida e cobrar retomada.\n\n"
            else: report += "acompanhar retomada e velocidade para evitar estouro de ETA.\n\n"
            count_risco += 1

    report += "🚨 **VEÍCULOS PARADOS — RISCO OPERACIONAL**\n"
    parados = df[(df["Status_Movimento"] == "Parado") & (df["Tempo_Horas"] >= 1.0)].copy()
    if not parados.empty:
        report += "| LT | Pacotes | Parado | Situação | Ação |\n"
        report += "|---|---|---|---|---|\n"
        for _, row in parados.iterrows():
            sit = "Parada programada" if "programada" in row['Motivo_Parada'].lower() else "Posto fiscal" if "fiscal" in row['Motivo_Parada'].lower() else "Manutenção/Outros"
            acao = "Cobrar retomada" if row['Tempo_Horas'] > 3 else "Monitorar"
            report += f"| {row['LT_Short']} | {row['Pacotes']:,} | {row['Tempo_Str']} | {sit} | {acao} |\n"
    else:
        report += "Nenhum veículo parado há mais de 1 hora.\n"
    report += "\n"

    report += "📦 **TOP 5 — MAIOR VOLUME DE PACOTES**\n"
    top5 = df.sort_values(by="Pacotes", ascending=False).head(5)
    report += "| Rank | LT | Motorista | Pacotes | ETA |\n"
    report += "|---|---|---|---|---|\n"
    medalhas = ["🥇", "🥈", "🥉", "4", "5"]
    for i, (_, row) in enumerate(top5.iterrows()):
        report += f"| {medalhas[i]} | {row['LT_Short']} | {row['Motorista']} | {row['Pacotes']:,} | {row['ETA']} |\n"
    report += "\n"

    report += "🎯 **PLANO DE AÇÃO IMEDIATO**\n"
    report += "🔴 **Cobrar agora**\n"
    for _, row in df[df["Sem_Sinal"] == True].iterrows():
        report += f"- {row['LT_Short']} → verificar comunicação/posicionamento; a última atualização do veículo foi em {row['Ultima_Atualizacao_Str']}.\n"
    for _, row in df[(df["Status_Movimento"] == "Parado") & (df["Tempo_Horas"] >= 4.0)].iterrows():
        report += f"- {row['LT_Short']} → cobrar retomada após mais de {row['Tempo_Str']} parado.\n"
    
    report += "\n🟠 **Monitorar próximos 30 min**\n"
    for _, row in df[(df["Status_Movimento"] == "Parado") & (df["Tempo_Horas"] >= 1.0) & (df["Tempo_Horas"] < 4.0)].iterrows():
        report += f"- {row['LT_Short']} — parada de {row['Tempo_Str']}.\n"
    for _, row in df[(df["Status_Movimento"] == "Em trânsito") & (df["Velocidade"] > 0) & (df["Velocidade"] < 30)].iterrows():
        report += f"- {row['LT_Short']} — velocidade {row['Velocidade']} km/h.\n"

    report += "\n🟡 **Escalar se não houver evolução**\n"
    report += "As LTs listadas em 'Cobrar agora' que não apresentarem mudança de status na próxima hora.\n\n"
    
    report += "🟢 **Sem necessidade de ação imediata**\n"
    report += "As demais LTs apresentam margem de ETA compatível com a distância restante e/ou estão em velocidade suficiente no momento.\n\n"

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
            report += f"{row['LT_Full']}\n"
    else:
        report += "Nenhuma\n"
        
    report += "\nSem sinal:\n"
    sem_sinal_df = df[df["Sem_Sinal"] == True]
    if not sem_sinal_df.empty:
        for _, row in sem_sinal_df.iterrows():
            report += f"{row['LT_Full']}\n"
    else:
        report += "Nenhum\n"
        
    report += "----------------\n"
    
    return report

if raw_text:
    df_parsed = process_data(raw_text)
    
    if df_parsed.empty:
        st.error("Nenhum dado válido. Verifique se copiou corretamente.")
    else:
        st.success("Dados lidos com sucesso! Relatório gerado abaixo.")
        relatorio_final = generate_report_text(df_parsed)
        st.text_area("Copie o texto abaixo (Ctrl+A e Ctrl+C):", value=relatorio_final, height=600)
        
        with st.expander("Ver base de dados extraída (Para conferência)"):
            st.dataframe(df_parsed)
