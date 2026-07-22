import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# ── Conectar a MT5 ────────────────────────────────────────
if not mt5.initialize():
    print(f"Error al conectar: {mt5.last_error()}")
    quit()
print("Conectado a MT5")

# ── Paso 1: Descargar datos ───────────────────────────────
def descargar_datos(symbol="XAUUSD.sml",
                    timeframe=mt5.TIMEFRAME_M5):
    """
    20,000 velas de 5 minutos = ~70 dias de datos
    """
    print(f"Descargando {symbol} en velas de 5 minutos...")
    mt5.symbol_select(symbol, True)
    velas = mt5.copy_rates_from_pos(symbol, timeframe, 0, 20000)

    if velas is None or len(velas) == 0:
        print(f"Error: {mt5.last_error()}")
        mt5.shutdown()
        quit()

    df = pd.DataFrame(velas)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)
    df.rename(columns={"tick_volume": "volume"}, inplace=True)

    print(f"Velas descargadas: {len(df)}")
    print(f"   Desde: {df.index[0]}")
    print(f"   Hasta: {df.index[-1]}\n")
    return df

# ── Paso 2: Indicadores ───────────────────────────────────
def calcular_indicadores(df, bb_periodo=20, bb_desviacion=2,
                         rsi_periodo=14):
    """
    Bollinger Bands:
      banda_media  = SMA de 20 periodos
      banda_sup    = media + 2 desviaciones estándar
      banda_inf    = media - 2 desviaciones estándar

    RSI 14 = fuerza relativa
    """
    # Bollinger Bands
    df["bb_media"] = df["close"].rolling(bb_periodo).mean()
    std            = df["close"].rolling(bb_periodo).std()
    df["bb_sup"]   = df["bb_media"] + (bb_desviacion * std)
    df["bb_inf"]   = df["bb_media"] - (bb_desviacion * std)
    df["bb_ancho"] = df["bb_sup"] - df["bb_inf"]

    # RSI
    delta        = df["close"].diff()
    ganancia     = delta.clip(lower=0)
    perdida      = (-delta).clip(lower=0)
    avg_gain     = ganancia.ewm(span=rsi_periodo, adjust=False).mean()
    avg_loss     = perdida.ewm(span=rsi_periodo, adjust=False).mean()
    rs           = avg_gain / avg_loss
    df["rsi"]    = 100 - (100 / (1 + rs))

    df.dropna(inplace=True)
    return df

# ── Paso 3: Señales ───────────────────────────────────────
def generar_senales(df):
    """
    BUY  → precio toca o cruza banda inferior
            Y RSI < 35 (sobrevendido)

    SELL → precio toca o cruza banda superior
            Y RSI > 65 (sobrecomprado)

    Lógica: el precio tiende a volver al centro
    después de tocar los extremos (mean reversion)
    """
    df["senal"] = "HOLD"

    condicion_buy = (
        (df["close"] <= df["bb_inf"]) &
        (df["rsi"] < 35)
    )
    condicion_sell = (
        (df["close"] >= df["bb_sup"]) &
        (df["rsi"] > 65)
    )

    df.loc[condicion_buy,  "senal"] = "BUY"
    df.loc[condicion_sell, "senal"] = "SELL"

    return df

# ── Paso 4: Backtesting ───────────────────────────────────
def backtesting(df, capital_inicial=10000, lote=0.01,
                stop_loss_usd=15, take_profit_usd=30):
    """
    En el Oro el precio se mide en USD por onza.
    En lugar de pips usamos USD directamente.

    stop_loss_usd   = cerrar si pierde $15 por onza
    take_profit_usd = cerrar si gana $30 por onza

    Con micro lote (0.01) cada $1 de movimiento = $0.01
    """
    capital        = capital_inicial
    en_posicion    = False
    tipo_pos       = None
    precio_entrada = None
    operaciones    = []
    historico      = []

    for timestamp, fila in df.iterrows():
        precio = fila["close"]
        senal  = fila["senal"]

        if en_posicion:
            if tipo_pos == "BUY":
                movimiento = precio - precio_entrada
            else:
                movimiento = precio_entrada - precio

            ganancia_usd = movimiento * lote * 100

            # Stop-loss
            if movimiento <= -stop_loss_usd:
                capital += ganancia_usd
                operaciones[-1].update({
                    "fecha_venta"  : timestamp,
                    "precio_venta" : precio,
                    "movimiento"   : movimiento,
                    "ganancia_usd" : ganancia_usd,
                    "cierre"       : "STOP-LOSS"
                })
                en_posicion = False
                print(f"  Stop-loss   | "
                      f"Mov: ${movimiento:.2f} | "
                      f"P&L: ${ganancia_usd:.2f}")

            # Take-profit
            elif movimiento >= take_profit_usd:
                capital += ganancia_usd
                operaciones[-1].update({
                    "fecha_venta"  : timestamp,
                    "precio_venta" : precio,
                    "movimiento"   : movimiento,
                    "ganancia_usd" : ganancia_usd,
                    "cierre"       : "TAKE-PROFIT"
                })
                en_posicion = False
                print(f"  Take-profit | "
                      f"Mov: ${movimiento:.2f} | "
                      f"P&L: ${ganancia_usd:.2f}")

            # Señal contraria
            elif (tipo_pos == "BUY"  and senal == "SELL") or \
                 (tipo_pos == "SELL" and senal == "BUY"):
                capital += ganancia_usd
                operaciones[-1].update({
                    "fecha_venta"  : timestamp,
                    "precio_venta" : precio,
                    "movimiento"   : movimiento,
                    "ganancia_usd" : ganancia_usd,
                    "cierre"       : "SENAL"
                })
                en_posicion = False

        if senal == "BUY" and not en_posicion:
            en_posicion    = True
            tipo_pos       = "BUY"
            precio_entrada = precio
            operaciones.append({
                "tipo"         : "BUY",
                "fecha_compra" : timestamp,
                "precio_compra": precio,
            })

        elif senal == "SELL" and not en_posicion:
            en_posicion    = True
            tipo_pos       = "SELL"
            precio_entrada = precio
            operaciones.append({
                "tipo"         : "SELL",
                "fecha_compra" : timestamp,
                "precio_compra": precio,
            })

        historico.append({
            "fecha"  : timestamp,
            "capital": capital,
            "precio" : precio
        })

    mt5.shutdown()
    return capital, operaciones, pd.DataFrame(historico)

# ── Paso 5: Metricas ──────────────────────────────────────
def calcular_metricas(capital_final, capital_inicial,
                      operaciones, historico):
    retorno_total = ((capital_final / capital_inicial) - 1) * 100
    cerradas      = [o for o in operaciones if "movimiento" in o]

    if cerradas:
        movimientos   = [o["movimiento"]   for o in cerradas]
        ganancias     = [o["ganancia_usd"] for o in cerradas]
        ganadoras     = [g for g in ganancias if g > 0]
        win_rate      = (len(ganadoras) / len(cerradas)) * 100
        mejor         = max(movimientos)
        peor          = min(movimientos)
        promedio      = sum(ganancias) / len(ganancias)
        total_ganancia= sum(ganancias)
        por_sl        = sum(1 for o in cerradas
                           if o.get("cierre") == "STOP-LOSS")
        por_tp        = sum(1 for o in cerradas
                           if o.get("cierre") == "TAKE-PROFIT")
    else:
        win_rate = mejor = peor = promedio = total_ganancia = 0
        por_sl = por_tp = 0

    pico     = historico["capital"].cummax()
    drawdown = ((historico["capital"] - pico) / pico) * 100
    max_dd   = drawdown.min()

    return {
        "capital_inicial" : capital_inicial,
        "capital_final"   : capital_final,
        "retorno_total"   : retorno_total,
        "operaciones"     : len(cerradas),
        "win_rate"        : win_rate,
        "mejor_trade"     : mejor,
        "peor_trade"      : peor,
        "promedio_trade"  : promedio,
        "total_ganancia"  : total_ganancia,
        "max_drawdown"    : max_dd,
        "stop_losses"     : por_sl,
        "take_profits"    : por_tp,
    }

# ── Paso 6: Grafica ───────────────────────────────────────
def graficar(historico, metricas):
    fig = plt.figure(figsize=(18, 9), facecolor="#0f0f0f")
    gs  = gridspec.GridSpec(2, 1, height_ratios=[2, 1],
                            hspace=0.08)

    C_CAPITAL = "#f0a500"
    C_PRECIO  = "#555555"
    C_SELL    = "#ff4444"
    C_PANEL   = "#161616"
    C_GRID    = "#222222"
    C_TEXTO   = "#aaaaaa"

    ax1 = fig.add_subplot(gs[0])
    ax1.set_facecolor(C_PANEL)

    precio_norm = (
        historico["precio"] / historico["precio"].iloc[0]
    ) * metricas["capital_inicial"]

    ax1.plot(historico["fecha"], historico["capital"],
             color=C_CAPITAL, linewidth=1.5,
             label="Capital", zorder=3)
    ax1.plot(historico["fecha"], precio_norm,
             color=C_PRECIO, linewidth=1, linestyle="--",
             label="XAU/USD (normalizado)", zorder=2)
    ax1.axhline(metricas["capital_inicial"],
                color=C_TEXTO, linewidth=0.7,
                linestyle=":", alpha=0.5,
                label="Capital inicial")

    retorno = metricas["retorno_total"]
    ax1.set_title(
        f"Backtesting XAU/USD (5min + BB + RSI)  |  "
        f"Retorno: {retorno:+.2f}%  |  "
        f"Ops: {metricas['operaciones']}  |  "
        f"Win rate: {metricas['win_rate']:.1f}%  |  "
        f"SL: {metricas['stop_losses']}  "
        f"TP: {metricas['take_profits']}  |  "
        f"Drawdown: {metricas['max_drawdown']:.2f}%",
        color="white", fontsize=10, pad=12
    )
    ax1.set_ylabel("Capital (USD)", color=C_TEXTO, fontsize=11)
    ax1.tick_params(colors=C_TEXTO, labelbottom=False)
    ax1.grid(color=C_GRID, linewidth=0.5)
    ax1.legend(facecolor="#1e1e1e", labelcolor=C_TEXTO,
               fontsize=10)

    pico     = historico["capital"].cummax()
    drawdown = ((historico["capital"] - pico) / pico) * 100

    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax2.set_facecolor(C_PANEL)
    ax2.fill_between(historico["fecha"], drawdown, 0,
                     color=C_SELL, alpha=0.4)
    ax2.plot(historico["fecha"], drawdown,
             color=C_SELL, linewidth=1)
    ax2.set_ylabel("Drawdown %", color=C_TEXTO, fontsize=11)
    ax2.tick_params(colors=C_TEXTO)
    ax2.grid(color=C_GRID, linewidth=0.5)
    plt.xticks(rotation=30, ha="right",
               color=C_TEXTO, fontsize=9)

    plt.savefig("backtest_xauusd.png", dpi=150,
                bbox_inches="tight", facecolor="#0f0f0f")
    print("Grafica guardada como backtest_xauusd.png")

# ── Ejecutar ──────────────────────────────────────────────
df = descargar_datos("XAUUSD.sml", mt5.TIMEFRAME_M5)
df = calcular_indicadores(df)
df = generar_senales(df)

resumen = df["senal"].value_counts()
print(f"BUY signals : {resumen.get('BUY', 0)}")
print(f"SELL signals: {resumen.get('SELL', 0)}")
print(f"HOLD signals: {resumen.get('HOLD', 0)}\n")

capital_final, operaciones, historico = backtesting(
    df,
    capital_inicial  = 10000,
    lote             = 0.01,
    stop_loss_usd    = 15,
    take_profit_usd  = 30
)

metricas = calcular_metricas(
    capital_final, 10000, operaciones, historico
)

print("=" * 55)
print("   BACKTESTING XAU/USD (5min + BB + RSI)")
print("=" * 55)
print(f"  Capital inicial   : ${metricas['capital_inicial']:,.2f}")
print(f"  Capital final     : ${metricas['capital_final']:,.2f}")
print(f"  Retorno total     : {metricas['retorno_total']:+.2f}%")
print(f"  Operaciones       : {metricas['operaciones']}")
print(f"  Stop-losses       : {metricas['stop_losses']}")
print(f"  Take-profits      : {metricas['take_profits']}")
print(f"  Win rate          : {metricas['win_rate']:.1f}%")
print(f"  Ganancia total    : ${metricas['total_ganancia']:,.2f}")
print(f"  Promedio/trade    : ${metricas['promedio_trade']:,.2f}")
print(f"  Mejor trade       : ${metricas['mejor_trade']:,.2f}")
print(f"  Peor trade        : ${metricas['peor_trade']:,.2f}")
print(f"  Max drawdown      : {metricas['max_drawdown']:.2f}%")
print("=" * 55)

# Rendimiento diario
historico["fecha"] = pd.to_datetime(historico["fecha"])
historico["dia"]   = historico["fecha"].dt.date
por_dia            = historico.groupby("dia")["capital"].last()
retorno_diario     = por_dia.pct_change() * 100

print("\n── Rendimiento diario ──────────────────────")
print(f"  Dias operados        : {len(por_dia)}")
print(f"  Dias ganadores       : {(retorno_diario > 0).sum()}")
print(f"  Dias perdedores      : {(retorno_diario < 0).sum()}")
print(f"  Retorno diario prom  : {retorno_diario.mean():+.4f}%")
print(f"  Mejor dia            : {retorno_diario.max():+.4f}%")
print(f"  Peor dia             : {retorno_diario.min():+.4f}%")
print(f"  Retorno mensual prom : {retorno_diario.mean() * 21:+.2f}%")
print(f"  Retorno anual prom   : {retorno_diario.mean() * 252:+.2f}%")
print("────────────────────────────────────────────")

graficar(historico, metricas)