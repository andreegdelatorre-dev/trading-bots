import MetaTrader5 as mt5
import pytz
from datetime import datetime

mt5.initialize()

symbol = "EURUSD.sml"

# Activar símbolo
mt5.symbol_select(symbol, True)

# Ver info del símbolo
info = mt5.symbol_info(symbol)
print(f"Símbolo encontrado: {info is not None}")
print(f"Visible: {info.visible}")

# Intentar descargar solo 10 velas recientes
velas = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 10)
print(f"Velas M5 recientes: {len(velas) if velas is not None else 'None'}")

# Intentar con H1 que ya está abierto en MT5
velas_h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 10)
print(f"Velas H1 recientes: {len(velas_h1) if velas_h1 is not None else 'None'}")

mt5.shutdown()