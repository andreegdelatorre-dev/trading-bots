import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import datetime

# ── Parametros de la estrategia ───────────────────────────
SYMBOL          = "XAUUSD.sml"
TIMEFRAME       = mt5.TIMEFRAME_M5
LOTE            = 0.01
STOP_LOSS_USD   = 15
TAKE_PROFIT_USD = 30
BB_PERIODO      = 20
BB_DESVIACION   = 2
RSI_PERIODO     = 14
LOG_FILE        = "log_xauusd.txt"

# ── Logging ───────────────────────────────────────────────
def log(mensaje):
    ahora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linea = f"[{ahora}] {mensaje}"
    print(linea)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(linea + "\n")

# ── Conectar a MT5 ────────────────────────────────────────
def conectar():
    if not mt5.initialize():
        log(f"Error al conectar: {mt5.last_error()}")
        return False
    mt5.symbol_select(SYMBOL, True)
    info = mt5.account_info()
    log("=" * 50)
    log("   BOT INICIADO - XAU/USD OANDA Demo")
    log(f"   Par      : {SYMBOL}")
    log(f"   Lote     : {LOTE}")
    log(f"   SL / TP  : ${STOP_LOSS_USD} / ${TAKE_PROFIT_USD}")
    log(f"   Balance  : ${info.balance:,.2f}")
    log(f"   Servidor : {info.server}")
    log("=" * 50)
    return True

# ── Obtener datos ─────────────────────────────────────────
def get_data():
    velas = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, 100)
    if velas is None or len(velas) == 0:
        log(f"Error al obtener datos: {mt5.last_error()}")
        return None
    df = pd.DataFrame(velas)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)
    return df

# ── Calcular indicadores ──────────────────────────────────
def calcular_indicadores(df):
    df["bb_media"] = df["close"].rolling(BB_PERIODO).mean()
    std            = df["close"].rolling(BB_PERIODO).std()
    df["bb_sup"]   = df["bb_media"] + (BB_DESVIACION * std)
    df["bb_inf"]   = df["bb_media"] - (BB_DESVIACION * std)

    delta        = df["close"].diff()
    ganancia     = delta.clip(lower=0)
    perdida      = (-delta).clip(lower=0)
    avg_gain     = ganancia.ewm(span=RSI_PERIODO, adjust=False).mean()
    avg_loss     = perdida.ewm(span=RSI_PERIODO, adjust=False).mean()
    rs           = avg_gain / avg_loss
    df["rsi"]    = 100 - (100 / (1 + rs))

    df.dropna(inplace=True)
    return df

# ── Generar señal ─────────────────────────────────────────
def get_senal(df):
    ultima = df.iloc[-1]
    precio = ultima["close"]
    rsi    = ultima["rsi"]
    bb_sup = ultima["bb_sup"]
    bb_inf = ultima["bb_inf"]

    log(f"Precio: {precio:.2f} | RSI: {rsi:.2f} | "
        f"BB inf: {bb_inf:.2f} | BB sup: {bb_sup:.2f}")

    if precio <= bb_inf and rsi < 35:
        return "BUY", precio
    elif precio >= bb_sup and rsi > 65:
        return "SELL", precio
    return "HOLD", precio

# ── Verificar posicion abierta ────────────────────────────
def get_posicion():
    posiciones = mt5.positions_get(symbol=SYMBOL)
    if posiciones and len(posiciones) > 0:
        return posiciones[0]
    return None

# ── Abrir posicion ────────────────────────────────────────
def abrir_posicion(senal, precio):
    tipo = mt5.ORDER_TYPE_BUY if senal == "BUY" else mt5.ORDER_TYPE_SELL

    if senal == "BUY":
        sl = precio - STOP_LOSS_USD
        tp = precio + TAKE_PROFIT_USD
    else:
        sl = precio + STOP_LOSS_USD
        tp = precio - TAKE_PROFIT_USD

    # Probar los tres modos de filling automaticamente
    modos = [
        mt5.ORDER_FILLING_IOC,
        mt5.ORDER_FILLING_FOK,
        mt5.ORDER_FILLING_RETURN
    ]

    for modo in modos:
        request = {
            "action"      : mt5.TRADE_ACTION_DEAL,
            "symbol"      : SYMBOL,
            "volume"      : LOTE,
            "type"        : tipo,
            "price"       : precio,
            "sl"          : round(sl, 2),
            "tp"          : round(tp, 2),
            "deviation"   : 20,
            "magic"       : 654321,
            "comment"     : "bot_xauusd",
            "type_time"   : mt5.ORDER_TIME_GTC,
            "type_filling": modo,
        }

        resultado = mt5.order_send(request)

        if resultado.retcode == mt5.TRADE_RETCODE_DONE:
            log(f"Posicion abierta | {senal} | "
                f"Precio: {precio:.2f} | "
                f"SL: {round(sl,2)} | TP: {round(tp,2)} | "
                f"Modo: {modo}")
            return True
        elif resultado.retcode != 10030:
            log(f"Error al abrir: {resultado.retcode} - "
                f"{resultado.comment}")
            return False

    log("Error: ningún modo de filling funciono")
    return False

# ── Cerrar posicion ───────────────────────────────────────
def cerrar_posicion(posicion):
    tipo_cierre = (
        mt5.ORDER_TYPE_SELL
        if posicion.type == mt5.ORDER_TYPE_BUY
        else mt5.ORDER_TYPE_BUY
    )
    precio = (
        mt5.symbol_info_tick(SYMBOL).bid
        if tipo_cierre == mt5.ORDER_TYPE_SELL
        else mt5.symbol_info_tick(SYMBOL).ask
    )

    modos = [
        mt5.ORDER_FILLING_IOC,
        mt5.ORDER_FILLING_FOK,
        mt5.ORDER_FILLING_RETURN
    ]

    for modo in modos:
        request = {
            "action"      : mt5.TRADE_ACTION_DEAL,
            "symbol"      : SYMBOL,
            "volume"      : posicion.volume,
            "type"        : tipo_cierre,
            "position"    : posicion.ticket,
            "price"       : precio,
            "deviation"   : 20,
            "magic"       : 654321,
            "comment"     : "bot_cierre",
            "type_time"   : mt5.ORDER_TIME_GTC,
            "type_filling": modo,
        }

        resultado = mt5.order_send(request)

        if resultado.retcode == mt5.TRADE_RETCODE_DONE:
            log(f"Posicion cerrada | P&L: ${posicion.profit:.2f}")
            return True
        elif resultado.retcode != 10030:
            log(f"Error al cerrar: {resultado.retcode} - "
                f"{resultado.comment}")
            return False

    log("Error: ningún modo de filling funciono al cerrar")
    return False

# ── Loop principal ────────────────────────────────────────
def run():
    if not conectar():
        return

    while True:
        try:
            log("-- Revisando mercado --")

            df = get_data()
            if df is None:
                time.sleep(60)
                continue

            df            = calcular_indicadores(df)
            senal, precio = get_senal(df)
            posicion      = get_posicion()

            info = mt5.account_info()
            log(f"Balance: ${info.balance:,.2f} | "
                f"Equity: ${info.equity:,.2f} | "
                f"En posicion: {'Si' if posicion else 'No'}")

            if posicion:
                tipo_pos = "BUY" if posicion.type == 0 else "SELL"
                log(f"Posicion activa: {tipo_pos} | "
                    f"P&L actual: ${posicion.profit:.2f}")

                if (tipo_pos == "BUY"  and senal == "SELL") or \
                   (tipo_pos == "SELL" and senal == "BUY"):
                    log(f"Senal contraria — cerrando {tipo_pos}")
                    if cerrar_posicion(posicion):
                        time.sleep(1)
                        abrir_posicion(senal, precio)
                else:
                    log(f"Manteniendo posicion {tipo_pos}")
            else:
                if senal in ["BUY", "SELL"]:
                    log(f"Senal detectada: {senal} — abriendo posicion")
                    abrir_posicion(senal, precio)
                else:
                    log("Senal: HOLD — esperando")

            log(f"Proxima revision en 5 minutos\n")
            time.sleep(300)

        except KeyboardInterrupt:
            log("Bot detenido manualmente")
            mt5.shutdown()
            break

        except Exception as e:
            log(f"Error: {e}")
            log("Reintentando en 60 segundos...")
            time.sleep(60)

# ── Ejecutar ──────────────────────────────────────────────
if __name__ == "__main__":
    run()