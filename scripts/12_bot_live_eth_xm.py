import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import datetime

# ── Parametros de la estrategia ───────────────────────────
SYMBOL          = "ETHUSD#"
TIMEFRAME       = mt5.TIMEFRAME_M5
LOTE            = 0.05
STOP_LOSS_USD   = 30
TAKE_PROFIT_USD = 90
BB_PERIODO      = 20
BB_DESVIACION   = 2
RSI_PERIODO     = 14
MAX_POSICIONES  = 2
MIN_GANANCIA_P1 = 0.50
LOG_FILE        = "log_xm_eth.txt"

# ── Horario de operacion (dos ventanas) ───────────────────
# Ventana 1: 7:00 AM – 2:00 PM Guadalajara = 13:00–20:00 UTC
# Ventana 2: 8:00 PM – 2:00 AM Guadalajara = 02:00–08:00 UTC
VENTANA_1_INICIO = 13
VENTANA_1_FIN    = 20
VENTANA_2_INICIO = 2
VENTANA_2_FIN    = 8

# ── Logging ───────────────────────────────────────────────
def log(mensaje):
    ahora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linea = f"[{ahora}] {mensaje}"
    print(linea)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(linea + "\n")

# ── Verificar si el mercado esta abierto ──────────────────
def mercado_abierto():
    """
    ETH opera 24/7 pero solo operamos en dos ventanas:
    Ventana 1: 13:00–20:00 UTC = 7:00 AM–2:00 PM Guadalajara
    Ventana 2: 02:00–08:00 UTC = 8:00 PM–2:00 AM Guadalajara
    Se omiten sabados y domingos por bajo volumen institucional.
    """
    ahora_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    dia        = ahora_utc.weekday()
    hora_utc   = ahora_utc.hour

    if dia == 5 or dia == 6:
        return False

    en_ventana_1 = VENTANA_1_INICIO <= hora_utc < VENTANA_1_FIN
    en_ventana_2 = VENTANA_2_INICIO <= hora_utc < VENTANA_2_FIN

    return en_ventana_1 or en_ventana_2

# ── Conectar a MT5 ────────────────────────────────────────
def conectar():
    if not mt5.initialize(path="C:\\Program Files\\XM Global MT5\\terminal64.exe"):
        log(f"Error al conectar: {mt5.last_error()}")
        return False
    mt5.symbol_select(SYMBOL, True)
    info = mt5.account_info()
    log("=" * 50)
    log("   BOT INICIADO - ETH/USD XM Real")
    log(f"   Par      : {SYMBOL}")
    log(f"   Lote     : {LOTE}")
    log(f"   SL / TP  : ${STOP_LOSS_USD} / ${TAKE_PROFIT_USD}")
    log(f"   Max pos  : {MAX_POSICIONES}")
    log(f"   Balance  : ${info.balance:,.2f}")
    log(f"   Servidor : {info.server}")
    log(f"   Opera    : Lun-Vie 7AM-2PM y 8PM-2AM Guadalajara")
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

# ── Obtener todas las posiciones abiertas ─────────────────
def get_posiciones():
    posiciones = mt5.positions_get(symbol=SYMBOL)
    if posiciones and len(posiciones) > 0:
        return list(posiciones)
    return []

# ── Abrir posicion ────────────────────────────────────────
def abrir_posicion(senal, precio):
    tipo = mt5.ORDER_TYPE_BUY if senal == "BUY" else mt5.ORDER_TYPE_SELL

    if senal == "BUY":
        sl = precio - STOP_LOSS_USD
        tp = precio + TAKE_PROFIT_USD
    else:
        sl = precio + STOP_LOSS_USD
        tp = precio - TAKE_PROFIT_USD

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
            "magic"       : 111222,
            "comment"     : "bot_eth_xm",
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

    log("Error: ningun modo de filling funciono")
    return False

# ── Cerrar posicion ───────────────────────────────────────
def cerrar_posicion(posicion, motivo="señal"):
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
            "magic"       : 111222,
            "comment"     : "bot_cierre",
            "type_time"   : mt5.ORDER_TIME_GTC,
            "type_filling": modo,
        }

        resultado = mt5.order_send(request)

        if resultado.retcode == mt5.TRADE_RETCODE_DONE:
            log(f"Posicion cerrada | Ticket: {posicion.ticket} | "
                f"Motivo: {motivo} | P&L: ${posicion.profit:.2f}")
            return True
        elif resultado.retcode != 10030:
            log(f"Error al cerrar: {resultado.retcode} - "
                f"{resultado.comment}")
            return False

    log("Error: ningun modo de filling funciono al cerrar")
    return False

# ── Cerrar todas las posiciones ───────────────────────────
def cerrar_todas(posiciones, motivo="señal contraria"):
    for pos in posiciones:
        cerrar_posicion(pos, motivo=motivo)
        time.sleep(0.5)

# ── Loop principal ────────────────────────────────────────
def run():
    if not conectar():
        return

    while True:
        try:
            if not mercado_abierto():
                posiciones = get_posiciones()
                if posiciones:
                    log("Fuera de horario — cerrando posiciones abiertas")
                    cerrar_todas(posiciones, motivo="cierre de sesion")

                log("Fuera de horario — esperando proxima ventana")
                time.sleep(300)
                continue

            log("-- Revisando mercado --")

            df = get_data()
            if df is None:
                time.sleep(60)
                continue

            df            = calcular_indicadores(df)
            senal, precio = get_senal(df)
            posiciones    = get_posiciones()
            n_pos         = len(posiciones)

            info = mt5.account_info()
            log(f"Balance: ${info.balance:,.2f} | "
                f"Equity: ${info.equity:,.2f} | "
                f"Posiciones abiertas: {n_pos}/{MAX_POSICIONES}")

            ganancia_total = 0
            for pos in posiciones:
                tipo_pos = "BUY" if pos.type == 0 else "SELL"
                log(f"  Pos {pos.ticket} | {tipo_pos} | "
                    f"P&L: ${pos.profit:.2f}")
                ganancia_total += pos.profit

            if n_pos > 0:
                log(f"  P&L total flotante: ${ganancia_total:.2f}")

            if n_pos == 0:
                if senal in ["BUY", "SELL"]:
                    log(f"Senal detectada: {senal} — abriendo posicion 1")
                    abrir_posicion(senal, precio)
                else:
                    log("Senal: HOLD — esperando")

            elif n_pos == 1:
                pos1     = posiciones[0]
                tipo_pos = "BUY" if pos1.type == 0 else "SELL"

                if (tipo_pos == "BUY" and senal == "SELL") or \
                   (tipo_pos == "SELL" and senal == "BUY"):
                    log(f"Senal contraria — cerrando pos1 y abriendo {senal}")
                    if cerrar_posicion(pos1, motivo="senal contraria"):
                        time.sleep(1)
                        abrir_posicion(senal, precio)

                elif senal == tipo_pos:
                    if pos1.profit >= MIN_GANANCIA_P1:
                        log(f"Pos1 en ganancia (${pos1.profit:.2f}) — "
                            f"abriendo posicion 2")
                        abrir_posicion(senal, precio)
                    else:
                        log(f"Senal {senal} pero pos1 aun no alcanza "
                            f"ganancia minima (${pos1.profit:.2f} / "
                            f"${MIN_GANANCIA_P1}) — esperando")
                else:
                    log(f"Manteniendo posicion 1 ({tipo_pos})")

            elif n_pos >= MAX_POSICIONES:
                tipo_pos = "BUY" if posiciones[0].type == 0 else "SELL"

                if (tipo_pos == "BUY" and senal == "SELL") or \
                   (tipo_pos == "SELL" and senal == "BUY"):
                    log(f"Senal contraria con {n_pos} posiciones — "
                        f"cerrando todas y abriendo {senal}")
                    cerrar_todas(posiciones, motivo="senal contraria")
                    time.sleep(1)
                    abrir_posicion(senal, precio)
                else:
                    log(f"Maximo de posiciones alcanzado ({n_pos}) — "
                        f"manteniendo")

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