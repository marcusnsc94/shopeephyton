def generate_report_text(df):
    agora = datetime.utcnow() - timedelta(hours=3)
    data_hora_str = agora.strftime("%d/%m/%Y · %H:%M")
    
    report = f"📊 *MONITORAMENTO OPERACIONAL — TORRE DE CONTROLE*\n"
    report += f"🕒 Atualização: {data_hora_str}\n"
    report += f"📦 Total de LTs no recorte do plantão: {len(df)}\n\n"
    
    # 1. Delays / Atrasos Matemáticos
    criticos = df[df["Status_Operacional"] == "Delay"].copy()
    report += "🚨 *DELAY / ATRASO MATEMÁTICO*\n"
    if criticos.empty:
        report += "• Nenhuma LT em delay neste recorte.\n\n"
    else:
        for _, row in criticos.iterrows():
            report += f"• *{row['LT_Short']}* | Motorista: {row['Motorista']} | Pcts: {row['Pacotes']:,} | ETA: {row['ETA']} | Destino: {row['Destino']}\n"
            report += f"  _Ação/Motivo: {row['Motivo_Risco']}_\n\n"

    # 2. Tendência de Atraso / Riscos
    riscos = df[df["Status_Operacional"] == "Tendência"].copy()
    report += "⚠️ *TENDÊNCIA DE ATRASO / ALERTAS*\n"
    if riscos.empty:
        report += "• Nenhuma tendência de atraso identificada.\n\n"
    else:
        for _, row in riscos.iterrows():
            report += f"• *{row['LT_Short']}* | Motorista: {row['Motorista']} | Pcts: {row['Pacotes']:,} | Margem: {row['Margem_Minutos']} min\n"
            report += f"  _Evidência: {row['Motivo_Risco']}_\n\n"

    # 3. Veículos Parados com destaque de tempo
    parados = df[df["Status_Movimento"] == "Parado"].copy()
    report += "🛑 *VEÍCULOS PARADOS*\n"
    if parados.empty:
        report += "• Nenhum veículo parado no momento.\n\n"
    else:
        for _, row in parados.iterrows():
            report += f"• *{row['LT_Short']}* | Parado há: {row['Tempo_Str']} | Pcts: {row['Pacotes']:,} | Destino: {row['Destino']}\n"
            report += f"  _Motivo Parada: {row['Motivo_Parada'] or 'Não informado'}_\n\n"

    # 4. Resumo por Rota / Performance UFs
    report += "🌐 *RESUMO POR ROTA (UF)*\n"
    ufs_disponiveis = df["UF"].unique()
    for uf in sorted(ufs_disponiveis):
        df_uf = df[df["UF"] == uf]
        total_lts_uf = len(df_uf)
        total_pcts_uf = df_uf["Pacotes"].sum()
        report += f"• *{uf}*: {total_lts_uf} LTs | {total_pcts_uf:,} pacotes\n"
    
    report += "\n----------------------------------------\n"
    report += "⚡ *Plano de Ação:* Acionar motoristas em tendência de atraso e verificar retenções nos trechos críticos.\n"
    return report
