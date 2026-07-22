import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from datetime import datetime
import pytz

# ── Conectar a MT5 ────────────────────────────────────────
if not mt5.initialize():
    print(f"Error al conectar: {mt5.last_error()}")
    quit()
print("Conectado a MT5")

# ── Paso 1: Descargar datos en 1 minuto ───────────────────
def descargar_datos(symbol="EURUSD.sml",
                    timeframe=mt5.TIMEFRAME_M1):
    """
    Descarga las ultimas 20,000 velas de 1 minuto.
    20,000 velas de 1min = ~14 dias de datos
    """
    print(f"Descargando {symbol} en velas de 1 minuto...")
    mt5.symbol_select(symbol, True)
    velas = mt5.copy_rates_from_pos(symbol, timeframe, 0, 99000)

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
def calcular_indicadores(df):
    """
    Mismos indicadores pero en velas de 1 minuto.
    EMA9  = 9 minutos de tendencia
    EMA21 = 21 minutos de tendencia
    """
    df["ema9"]   = df["close"].ewm(span=9,  adjust=False).mean()
    df["ema21"]  = df["close"].ewm(span=21, adjust=False).mean()
    ema12        = df["close"].ewm(span=12, adjust=False).mean()
    ema26        = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"]   = ema12 - ema26
    df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["hist"]   = df["macd"] - df["signal"]
    df.dropna(inplace=True)
    return df

# ── Paso 3: Señales ───────────────────────────────────────
def generar_senales(df):
    df["senal"] = "HOLD"

    cruce_alcista = (
        (df["ema9"] > df["ema21"]) &
        (df["ema9"].shift(1) < df["ema21"].shift(1)) &
        (df["hist"] > 0)
    )
    cruce_bajista = (
        (df["ema9"] < df["ema21"]) &
        (df["ema9"].shift(1) > df["ema21"].shift(1)) &
        (df["hist"] < 0)
    )

    df.loc[cruce_alcista, "senal"] = "BUY"
    df.loc[cruce_bajista, "senal"] = "SELL"

    return df

# ── Paso 4: Backtesting ───────────────────────────────────
def backtesting(df, capital_inicial=10000, lote=0.01,
                stop_loss_pips=7, take_profit_pips=21):
    """
    Mismos parametros ganadores del backtesting de 5min.
    Con 1 minuto el SL/TP se revisa 5 veces mas seguido.
    """
    PIP         = 0.00001
    VALOR_PIP   = 0.10
    capital     = capital_inicial
    en_posicion = False
    tipo_pos    = None
    precio_entrada = None
    operaciones = []
    historico   = []

    for timestamp, fila in df.iterrows():
        precio = fila["close"]
        senal  = fila["senal"]

        if en_posicion:
            if tipo_pos == "BUY":
                pips = (precio - precio_entrada) / PIP
            else:
                pips = (precio_entrada - precio) / PIP

            if pips <= -stop_loss_pips:
                ganancia = pips * VALOR_PIP
                capital += ganancia
                operaciones[-1].update({
                    "fecha_venta"  : timestamp,
                    "precio_venta" : precio,
                    "pips"         : pips,
                    "ganancia_usd" : ganancia,
                    "cierre"       : "STOP-LOSS"
                })
                en_posicion = False
                print(f"  Stop-loss   | Pips: {pips:.1f} | P&L: ${ganancia:.2f}")

            elif pips >= take_profit_pips:
                ganancia = pips * VALOR_PIP
                capital += ganancia
                operaciones[-1].update({
                    "fecha_venta"  : timestamp,
                    "precio_venta" : precio,
                    "pips"         : pips,
                    "ganancia_usd" : ganancia,
                    "cierre"       : "TAKE-PROFIT"
                })
                en_posicion = False
                print(f"  Take-profit | Pips: {pips:.1f} | P&L: ${ganancia:.2f}")

            elif (tipo_pos == "BUY"  and senal == "SELL") or \
                 (tipo_pos == "SELL" and senal == "BUY"):
                ganancia = pips * VALOR_PIP
                capital += ganancia
                operaciones[-1].update({
                    "fecha_venta"  : timestamp,
                    "precio_venta" : precio,
                    "pips"         : pips,
                    "ganancia_usd" : ganancia,
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
    cerradas      = [o for o in operaciones if "pips" in o]

    if cerradas:
        pips_list     = [o["pips"] for o in cerradas]
        ganancias     = [o["ganancia_usd"] for o in cerradas]
        ganadoras     = [g for g in ganancias if g > 0]
        win_rate      = (len(ganadoras) / len(cerradas)) * 100
        mejor         = max(pips_list)
        peor          = min(pips_list)
        promedio_pips = sum(pips_list) / len(pips_list)
        total_pips    = sum(pips_list)
        por_sl        = sum(1 for o in cerradas
                           if o.get("cierre") == "STOP-LOSS")
        por_tp        = sum(1 for o in cerradas
                           if o.get("cierre") == "TAKE-PROFIT")
    else:
        win_rate = mejor = peor = promedio_pips = total_pips = 0
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
        "promedio_pips"   : promedio_pips,
        "total_pips"      : total_pips,
        "max_drawdown"    : max_dd,
        "stop_losses"     : por_sl,
        "take_profits"    : por_tp,
    }

# ── Paso 6: Grafica ───────────────────────────────────────
def graficar(historico, metricas):
    fig = plt.figure(figsize=(18, 9), facecolor="#0f0f0f")
    gs  = gridspec.GridSpec(2, 1, height_ratios=[2, 1],
                            hspace=0.08)

    C_CAPITAL = "#4a9eff"
    C_SELL    = "#ff4444"
    C_PANEL   = "#161616"
    C_GRID    = "#222222"
    C_TEXTO   = "#aaaaaa"

    ax1 = fig.add_subplot(gs[0])
    ax1.set_facecolor(C_PANEL)
    ax1.plot(historico["fecha"], historico["capital"],
             color=C_CAPITAL, linewidth=1.5,
             label="Capital", zorder=3)
    ax1.axhline(metricas["capital_inicial"],
                color=C_TEXTO, linewidth=0.7,
                linestyle=":", alpha=0.5,
                label="Capital inicial")

    retorno = metricas["retorno_total"]
    ax1.set_title(
        f"Backtesting EUR/USD (1min scalping)  |  "
        f"Retorno: {retorno:+.2f}%  |  "
        f"Ops: {metricas['operaciones']}  |  "
        f"Win rate: {metricas['win_rate']:.1f}%  |  "
        f"Pips: {metricas['total_pips']:+.1f}  |  "
        f"SL: {metricas['stop_losses']}  "
        f"TP: {metricas['take_profits']}",
        color="white", fontsize=10, pad=12
    )
    ax1.set_ylabel("Capital (USD)", color=C_TEXTO, fontsize=11)
    ax1.tick_params(colors=C_TEXTO, labelbottom=False)
    ax1.grid(color=C_GRID, linewidth=0.5)
    ax1.legend(facecolor="#1e1e1e", labelcolor=C_TEXTO, fontsize=10)

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

    plt.savefig("backtest_1min.png", dpi=150,
                bbox_inches="tight", facecolor="#0f0f0f")
    print("Grafica guardada como backtest_1min.png")

# ── Ejecutar ──────────────────────────────────────────────
df = descargar_datos("EURUSD.sml", mt5.TIMEFRAME_M1)
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
    stop_loss_pips   = 7,
    take_profit_pips = 21
)

metricas = calcular_metricas(
    capital_final, 10000, operaciones, historico
)

print("=" * 55)
print("   BACKTESTING EUR/USD (1min scalping)")
print("=" * 55)
print(f"  Capital inicial   : ${metricas['capital_inicial']:,.2f}")
print(f"  Capital final     : ${metricas['capital_final']:,.2f}")
print(f"  Retorno total     : {metricas['retorno_total']:+.2f}%")
print(f"  Operaciones       : {metricas['operaciones']}")
print(f"  Stop-losses       : {metricas['stop_losses']}")
print(f"  Take-profits      : {metricas['take_profits']}")
print(f"  Win rate          : {metricas['win_rate']:.1f}%")
print(f"  Pips totales      : {metricas['total_pips']:+.1f}")
print(f"  Promedio pips     : {metricas['promedio_pips']:+.2f}")
print(f"  Mejor trade       : {metricas['mejor_trade']:+.1f} pips")
print(f"  Peor trade        : {metricas['peor_trade']:+.1f} pips")
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