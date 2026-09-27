import streamlit as st
import pandas as pd
import re

# Configuração da página
st.set_page_config(page_title="Painel de Monitoramento - Losung", layout="wide")

st.title("🚛 Torre de Controle - Análise Rápida de LTs")
st.caption("Cole a tabela do Losung Web para gerar o relatório operacional automatizado.")

# Área de Texto para Copiar e Colar
dados_brutos = st.text_area(
    "Cole os dados do Dashboard aqui (Ctrl+A no site -> Ctrl+C -> Ctrl+V aqui):", 
    height=150,
    placeholder="Cole o conteúdo da tabela..."
)

def extrair_minutos_sem_sinal(texto_posicionamento):
    """Calcula minutos desde o último posicionamento do GPS."""
    if not texto_posicionamento or pd.isna(texto_posicionamento):
        return 0
    m = re.search(r'(\d+)\s*h', str(texto_posicionamento).lower())
    m_min = re.search(r'(\d+)\s*min', str(texto_posicionamento).lower())
    
    horas = int(m.group(1)) if m else 0
    minutos = int(m_min.group(1)) if m_min else 0
    
    return (horas * 60) + minutos

def processar_dados(texto):
    linhas = [l.strip().split('\t') for l in texto.strip().split('\n') if l.strip()]
    if not linhas or len(linhas[0]) < 10:
        linhas = [re.split(r'\s{2,}', l.strip()) for l in texto.strip().split('\n') if l.strip()]

    dados = []
    for row in linhas:
        # Trava de segurança: ignora a linha se você copiar o cabeçalho sem querer
        if len(row) > 0 and "LR TRIP" in str(row[0]).upper():
            continue
            
        if len(row) >= 14:
            lt = row[0]
            motorista = row[1]
            status = row[2]
            origem = row[3]
            destino = row[4]
            pacotes_str = re.sub(r'\D', '', row[7]) if len(row) > 7 else '0'
            pacotes = int(pacotes_str) if pacotes_str else 0
            
            proximidade_str = re.sub(r'[^\d,.]', '', row[13]).replace(',', '.') if len(row) > 13 else '0'
            proximidade = float(proximidade_str) if proximidade_str else 0.0
            
            posicionamento = row[14] if len(row) > 14 else ""
            
            is_ma = "MA" in destino.upper() or "MARANHAO" in destino.upper() or "MARANHÃO" in destino.upper()
            fator_correcao = 1.35 if is_ma else 1.25
            km_corrigido = proximidade * fator_correcao
            
            minutos_sem_sinal = extrair_minutos_sem_sinal(posicionamento)
            
            dados.append({
                "LT": lt,
                "Motorista": motorista,
                "Status": status,
                "Origem": origem,
                "Destino": destino,
                "Pacotes": pacotes,
                "Km_Original": proximidade,
                "Km_Corrigido": round(km_corrigido, 1),
                "Posicionamento": posicionamento,
                "Minutos_Sem_Sinal": minutos_sem_sinal
            })
    return pd.DataFrame(dados)

if dados_brutos:
    try:
        df = processar_dados(dados_brutos)
        
        if df.empty:
            st.warning("Nenhum dado válido encontrado. Verifique a cópia.")
        else:
            df_sem_sinal = df[df['Minutos_Sem_Sinal'] >= 60]
            df_atrasados = df[df['Status'].str.contains("Atrasa|atrasa", case=False, na=False)]
            df_tendencia = df[(df['Status'].str.contains("Parado|parado", case=False, na=False)) & 
                              (~df['LT'].isin(df_atrasados['LT'])) & 
                              (df['Km_Corrigido'] > 30)]

            df_sp_rj = df[(df['Destino'].str.contains("SP|RJ", case=False, na=False)) & (df['Km_Corrigido'] <= 50)]
            df_carga_alta = df[df['Pacotes'] >= 6000]
            
            st.divider()

            # PARTE 1
            st.subheader("🚨 PARTE 1: Plano de Ação Imediato (Resolver em até 15 min)")
            acoes = []
            for _, row in df_sem_sinal.iterrows():
                acoes.append({"LT": row['LT'], "Condutor": row['Motorista'], "O que fazer": "Ligar / Acionar sirene via BRK", "Por quê": f"Sem sinal GPS há {row['Posicionamento']}."})
            for _, row in df_sp_rj.iterrows():
                acoes.append({"LT": row['LT'], "Condutor": row['Motorista'], "O que fazer": "Solicitar liberação na base", "Por quê": f"Veículo a {row['Km_Corrigido']} km do destino ({row['Destino']})."})
            for _, row in df_tendencia.iterrows():
                acoes.append({"LT": row['LT'], "Condutor": row['Motorista'], "O que fazer": "Cobrar reinício de viagem", "Por quê": f"Parado com {row['Km_Corrigido']} km restantes."})

            if acoes:
                st.table(pd.DataFrame(acoes))
            else:
                st.success("Nenhuma ação crítica urgente detectada!")

            # PARTE 2
            st.subheader("⏱️ PARTE 2: Atrasos Confirmados e Tendências")
            col1, col2 = st.columns(2)
            with col1:
                st.error(f"🔴 LTs em DELAY ({len(df_atrasados)})")
                if not df_atrasados.empty: st.dataframe(df_atrasados[['LT', 'Motorista', 'Destino', 'Km_Corrigido']], use_container_width=True)
            with col2:
                st.warning(f"🟠 Tendência de Atraso ({len(df_tendencia)})")
                if not df_tendencia.empty: st.dataframe(df_tendencia[['LT', 'Motorista', 'Destino', 'Km_Corrigido', 'Status']], use_container_width=True)

            # PARTE 3
            st.subheader("👁️ PARTE 3: Pontos de Atenção (Monitoramento)")
            st.markdown("**1. Próximos de SP/RJ (Necessitam Liberação de Portão):**")
            if not df_sp_rj.empty: st.dataframe(df_sp_rj[['LT', 'Motorista', 'Destino', 'Km_Corrigido']], use_container_width=True)
            st.markdown("**2. Cargas Críticas (> 6.000 Pacotes):**")
            if not df_carga_alta.empty: st.dataframe(df_carga_alta[['LT', 'Motorista', 'Destino', 'Pacotes']], use_container_width=True)

            # PARTE 4
            st.subheader("📋 PARTE 4: Listas Rápidas (Para Copiar e Colar)")
            c_del, c_ten, c_sin = st.columns(3)
            with c_del:
                st.markdown("**LTs em DELAY:**")
                st.code("\n".join(df_atrasados['LT'].tolist()) if not df_atrasados.empty else "Nenhuma", language="text")
            with c_ten:
                st.markdown("**LTs com Tendência:**")
                st.code("\n".join(df_tendencia['LT'].tolist()) if not df_tendencia.empty else "Nenhuma", language="text")
            with c_sin:
                st.markdown("**LTs Sem Sinal:**")
                st.code("\n".join(df_sem_sinal['LT'].tolist()) if not df_sem_sinal.empty else "Nenhuma", language="text")

    except Exception as e:
        st.error("Erro ao processar. Certifique-se de colar os resultados das colunas certinho.")
