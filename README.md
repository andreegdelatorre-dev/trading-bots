# Trading Bots MT5

Sistema automatizado de trading desarrollado en Python que opera simultáneamente en dos brokers (XM y OANDA) usando la API de MetaTrader 5.

## Estrategia

- **Indicadores:** Bandas de Bollinger + RSI
- **Activos:** Oro (XAUUSD), Forex (EURUSD), Cripto (ETH)
- **Gestión de riesgo:** Stop Loss y Take Profit dinámicos
- **Filtros de sesión:** por activo y horario de mercado

## Características

- Manejo de múltiples posiciones simultáneas
- Aislamiento de conexiones entre terminales MT5
- Scripts de backtest incluidos
- Compatible con cuentas demo y live

## Tecnologías

- Python
- MetaTrader 5 API
- Pandas / NumPy

## Requisitos

- MetaTrader 5 instalado
- Python 3.10+
- Cuenta en XM o OANDA

## Instalación

```bash
pip install MetaTrader5 pandas numpy
```

## Aviso

Este proyecto es de uso educativo y personal. El trading automatizado conlleva riesgos financieros.