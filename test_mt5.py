import MetaTrader5 as mt5

# Conectar a MT5
if not mt5.initialize():
    print(f"Error al conectar: {mt5.last_error()}")
else:
    print("Conectado a MT5")

# Ver info de la cuenta
info = mt5.account_info()
print(f"Balance    : ${info.balance:,.2f}")
print(f"Equity     : ${info.equity:,.2f}")
print(f"Servidor   : {info.server}")
print(f"Moneda     : {info.currency}")

# Cerrar conexion
mt5.shutdown()